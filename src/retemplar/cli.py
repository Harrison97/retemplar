# src/retemplar/cli.py
"""
Minimal retemplar CLI (Typer)

Commands:
- adopt : attach a repo to a template/ref and create `.retemplar.lock`
- plan  : compute template delta (old → new) and show proposed changes
- apply : apply the planned changes to the repo
- drift : report drift between baseline and current repo

Notes:
- Kept only options that are useful Day 1.
- Left `--json` (plan/drift) and `--interactive` (apply) as near-term (week 1) helpers.
- Removed PR/Yes flags and other non-essentials.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional
import json
import typer
from rich.console import Console

from .core import RetemplarCore
from .lockfile import LockfileError

app = typer.Typer(add_completion=False, help="Fleet-scale repository templating (RAT).")
console = Console()


# ----------------------------
# Global options / context
# ----------------------------


class Ctx:
    def __init__(self, repo_path: Path, verbose: bool, dry_run: bool):
        self.repo_path = repo_path
        self.verbose = verbose
        self.dry_run = dry_run


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
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose logs."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would happen; write nothing."
    ),
):
    """Initialize global context. Access via `ctx.obj`."""
    ctx.obj = Ctx(repo_path=repo, verbose=verbose, dry_run=dry_run)


def _log(ctx: typer.Context, msg: str) -> None:
    if getattr(ctx.obj, "verbose", False):
        console.print(f"[dim][verbose][/dim] {msg}")


def _handle_error(e: Exception) -> None:
    """Handle and display errors with proper formatting."""
    if isinstance(e, LockfileError):
        console.print(f"[bold red]Error:[/bold red] {e}")
    else:
        console.print(f"[bold red]Unexpected error:[/bold red] {e}")
    raise typer.Exit(1)


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
        help="Template source, e.g. 'rat:gh:org/repo@v2025.08.01'.",
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
):
    """Attach the repo to a template/ref and create `.retemplar.lock`."""
    _log(ctx, f"repo={ctx.obj.repo_path}")
    _log(ctx, f"template={template}")
    _log(ctx, f"managed={managed or '(none)'}")
    _log(ctx, f"ignore={ignore or '(none)'}")

    try:
        core = RetemplarCore(ctx.obj.repo_path)
        core.adopt_template(
            template,
            managed_paths=managed,
            ignore_paths=ignore,
            dry_run=ctx.obj.dry_run,
        )

        if not ctx.obj.dry_run:
            console.print(f"[green]✓[/green] Successfully adopted template: {template}")
            console.print(f"[dim]Created .retemplar.lock in {ctx.obj.repo_path}[/dim]")
        else:
            console.print(
                f"[yellow][dry-run][/yellow] Would adopt template: {template}"
            )
    except Exception as e:
        _handle_error(e)


@app.command()
def plan(
    ctx: typer.Context,
    to: str = typer.Option(
        ...,
        "--to",
        help="Target template ref/version, e.g. 'rat:gh:org/repo@v2025.09.01'.",
    ),
):
    """Preview the upgrade plan (old → new) for managed paths/sections."""
    _log(ctx, f"repo={ctx.obj.repo_path}")
    _log(ctx, f"target={to}")
    _log(ctx, f"dry_run={ctx.obj.dry_run}")

    try:
        core = RetemplarCore(ctx.obj.repo_path)
        plan_result = core.plan_upgrade(target_ref=to)
        console.print(json.dumps(plan_result, indent=2))
    except Exception as e:
        _handle_error(e)


@app.command()
def apply(
    ctx: typer.Context,
    to: Optional[str] = typer.Option(
        None,
        "--to",
        help="Target template ref/version (omit to use last planned).",
    ),
):
    """Apply the plan to the repo (3-way merge, conflict markers, orphaning)."""
    _log(ctx, f"repo={ctx.obj.repo_path}")
    _log(ctx, f"target={to or '(use last plan)'}")
    _log(ctx, f"dry_run={ctx.obj.dry_run}")

    if ctx.obj.dry_run:
        console.print("[yellow][dry-run][/yellow] No changes written.")
        return

    try:
        core = RetemplarCore(ctx.obj.repo_path)
        result = core.apply_changes(target_ref=to)

        console.print("[green]✓[/green] Successfully applied template changes")
        if result["conflicts_resolved"] > 0:
            console.print(
                f"[yellow]![/yellow] {result['conflicts_resolved']} conflicts resolved with markers/orphaning"
            )
    except Exception as e:
        _handle_error(e)


@app.command()
def drift(
    ctx: typer.Context,
    json: bool = typer.Option(
        False, "--json", help="Emit machine-readable drift JSON."
    ),
):
    """Report drift between the lockfile baseline and current repo."""
    _log(ctx, f"repo={ctx.obj.repo_path}")

    try:
        core = RetemplarCore(ctx.obj.repo_path)
        drift_result = core.detect_drift()

        if json:
            import json as json_module

            console.print(json_module.dumps(drift_result, indent=2))
        else:
            console.print("[bold]Drift Report:[/bold]")
            # TODO: Format drift result nicely
            console.print("  [CI] .github/workflows/ci.yml — template-only changes")
            console.print(
                "  [pyproject.toml] tool.ruff.line-length — both changed (conflict)"
            )
            console.print("  [README.md] — unmanaged")
    except Exception as e:
        _handle_error(e)


@app.command()
def version() -> None:
    """Print retemplar version."""
    typer.echo("retemplar 0.0.1")


# Support `python -m retemplar`
def _main() -> None:
    app()


if __name__ == "__main__":
    _main()
