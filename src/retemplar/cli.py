# src/retemplar/cli.py
"""
Minimal retemplar CLI (Typer, MVP)

Commands:
- adopt : attach a repo to a template/ref and create `.retemplar.lock`
- plan  : compute template delta (old → new), cheap structural preview
- apply : apply template changes (conflict markers for merge)
- drift : report drift (stub until 3-way baseline)
"""

from __future__ import annotations

import json
import traceback
from pathlib import Path
from typing import List

import typer
from rich.console import Console

from .core import RetemplarCore
from .lockfile import LockfileError

app = typer.Typer(
    add_completion=False,
    help="Fleet-scale repository templating (RAT).",
)
console = Console()


# ----------------------------
# Global context
# ----------------------------


class Ctx:
    def __init__(self, repo_path: Path, verbose: bool):
        self.repo_path = repo_path
        self.verbose = verbose


@app.callback()
def main(
    ctx: typer.Context,
    repo: Path = typer.Option(
        Path("."),
        "--repo",
        "-R",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        resolve_path=True,
        help="Path to the target repository (default: current directory).",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose logs.",
    ),
):
    """Initialize global context. Access via ctx.obj"""
    ctx.obj = Ctx(repo_path=repo, verbose=verbose)


def _print_json(data) -> None:
    try:
        console.print_json(data=data)
    except Exception:
        console.print(json.dumps(data, indent=2))


def _handle_error(e: Exception, verbose: bool) -> None:
    if isinstance(e, LockfileError):
        console.print(f"[bold red]Error:[/bold red] {e}")
    else:
        console.print(f"[bold red]Unexpected error:[/bold red] {e}")
    if verbose:
        console.print("[dim]" + traceback.format_exc() + "[/dim]")
    raise typer.Exit(1)


def _parse_render_opts(opts: List[str]) -> List[dict]:
    """Parse --render specs like FROM:TO or re:PATTERN:TO"""
    rules: List[dict] = []
    for spec in opts:
        if spec.startswith("re:"):
            body = spec[3:]
            if ":" not in body:
                raise typer.BadParameter(
                    f"Regex rule must be 're:PATTERN:REPLACEMENT': {spec}",
                )
            pattern, replacement = body.split(":", 1)
            rules.append(
                {
                    "pattern": pattern,
                    "replacement": replacement,
                    "literal": False,
                },
            )
        else:
            if ":" not in spec:
                raise typer.BadParameter(
                    f"Render rule must be 'FROM:TO' or 're:PATTERN:TO': {spec}",
                )
            pattern, replacement = spec.split(":", 1)
            rules.append(
                {
                    "pattern": pattern,
                    "replacement": replacement,
                    "literal": True,
                },
            )
    return rules


# ----------------------------
# Commands
# ----------------------------


@app.command()
def adopt(
    ctx: typer.Context,
    template: str = typer.Option(
        ...,
        "--template",
        "-t",
        help="Template source, e.g. 'rat:./template-dir@v0'.",
    ),
    managed: List[str] = typer.Option(
        [],
        "--managed",
        "-m",
        help="Glob(s) or path(s) to manage. Repeatable.",
    ),
    ignore: List[str] = typer.Option(
        [],
        "--ignore",
        "-i",
        help="Glob(s) or path(s) to ignore. Repeatable.",
    ),
    render: List[str] = typer.Option(
        [],
        "--render",
        "-r",
        help="Render rule (FROM:TO or re:PATTERN:TO). Repeatable.",
    ),
):
    """Attach the repo to a template/ref and create `.retemplar.lock`."""
    try:
        render_rules = _parse_render_opts(render)
        core = RetemplarCore(ctx.obj.repo_path)
        core.adopt_template(
            template,
            managed_paths=managed,
            ignore_paths=ignore,
            render_rules=render_rules,
        )
        console.print(f"[green]✓[/green] Adopted template: {template}")
        console.print(
            f"[dim]Created .retemplar.lock in {ctx.obj.repo_path}[/dim]",
        )
    except Exception as e:
        _handle_error(e, ctx.obj.verbose)


@app.command()
def plan(
    ctx: typer.Context,
    to: str = typer.Option(
        ...,
        "--to",
        help="Target template ref/version, e.g. 'rat:./template-dir@v1'.",
    ),
):
    """Preview structural upgrade plan (cheap, no file diffs)."""
    try:
        core = RetemplarCore(ctx.obj.repo_path)
        plan_result = core.plan_upgrade(target_ref=to)
        _print_json(plan_result)
    except Exception as e:
        _handle_error(e, ctx.obj.verbose)


@app.command()
def apply(
    ctx: typer.Context,
    to: str = typer.Option(
        ...,
        "--to",
        help="Target template ref/version to apply.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Preview actual changes and conflicts.",
    ),
):
    """Apply template changes (with content merge)."""
    try:
        core = RetemplarCore(ctx.obj.repo_path)
        if dry_run:
            console.print("[yellow][dry-run][/yellow] Previewing changes...")
            result = core.apply_changes(
                target_ref=to,
                dry_run=dry_run,
            )  # but don’t write
            _print_json(result)
            return
        result = core.apply_changes(target_ref=to)
        console.print("[green]✓[/green] Applied template changes")
        if result.get("conflicts_resolved", 0) > 0:
            console.print(
                f"[yellow]![/yellow] {result['conflicts_resolved']} file(s) contain conflict markers",
            )
    except Exception as e:
        _handle_error(e, ctx.obj.verbose)


@app.command()
def drift(
    ctx: typer.Context,
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable drift JSON.",
    ),
):
    """Report drift between the lockfile baseline and current repo (stub)."""
    console.print("Drift detection is a work in progress.", style="white on red")
    try:
        core = RetemplarCore(ctx.obj.repo_path)
        drift_result = core.detect_drift()
        if as_json:
            _print_json(drift_result)
        else:
            console.print("[bold]Drift Report (MVP):[/bold]")
            _print_json(drift_result)
    except Exception as e:
        _handle_error(e, ctx.obj.verbose)


@app.command()
def version() -> None:
    """Print retemplar version."""
    try:
        from importlib.metadata import version as _pkg_version

        typer.echo(f"retemplar {_pkg_version('retemplar')}")
    except Exception:
        typer.echo("retemplar 0.0.1")


def _main() -> None:
    app()


if __name__ == "__main__":
    _main()
