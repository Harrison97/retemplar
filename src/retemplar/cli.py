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

import typer

app = typer.Typer(add_completion=False, help="Fleet-scale repository templating (RAT).")


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
        typer.echo(f"[verbose] {msg}")


def _todo(feature: str) -> None:
    typer.echo(f"TODO: {feature} not implemented yet.")


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

    # TODO:
    # - Parse & validate `template` (kind=rat|pack, repo/ref)
    # - Render baseline for fingerprinting
    # - Write `.retemplar.lock` (managed/ignore, fingerprint, lineage)
    _todo("adopt")


@app.command()
def plan(
    ctx: typer.Context,
    to: str = typer.Option(
        ...,
        "--to",
        help="Target template ref/version, e.g. 'rat:gh:org/repo@v2025.09.01'.",
    ),
    json: bool = typer.Option(False, "--json", help="Emit machine-readable plan JSON."),
):
    """Preview the upgrade plan (old → new) for managed paths/sections."""
    _log(ctx, f"repo={ctx.obj.repo_path}")
    _log(ctx, f"target={to}")
    _log(ctx, f"dry_run={ctx.obj.dry_run}")

    # TODO:
    # - Read `.retemplar.lock` (base template/ref + scopes)
    # - Render template@old and template@new with same variables
    # - Compute delta (moves/renames/patches); 3-way preview
    if json:
        _todo("plan --json")
    else:
        typer.echo("Plan (preview):")
        typer.echo("  [CI] Move workflow: pytest.yml → ci.yml")
        typer.echo("  [pyproject.toml] tool.ruff.version: 0.3.0 → 0.5.0")
        typer.echo("  [NOTE] Conflicts detected: 1")


@app.command()
def apply(
    ctx: typer.Context,
    to: Optional[str] = typer.Option(
        None,
        "--to",
        help="Target template ref/version (omit to use last planned).",
    ),
    interactive: bool = typer.Option(
        False,
        "--interactive",
        help="Review and accept/reject hunks before writing.",
    ),
):
    """Apply the plan to the repo (3-way merge, overlays, hooks)."""
    _log(ctx, f"repo={ctx.obj.repo_path}")
    _log(ctx, f"target={to or '(use last plan)'}")
    _log(ctx, f"interactive={interactive}, dry_run={ctx.obj.dry_run}")

    if ctx.obj.dry_run:
        typer.echo("[dry-run] No changes written.")
        return

    # TODO:
    # - Resolve target ref/version (from --to or last plan)
    # - Execute per-file strategy: enforce/preserve/merge/patch
    # - Write changes or present interactive hunk chooser
    # - Commit to branch; (PR integration later)
    _todo("apply")


@app.command()
def drift(
    ctx: typer.Context,
    json: bool = typer.Option(
        False, "--json", help="Emit machine-readable drift JSON."
    ),
):
    """Report drift between the lockfile baseline and current repo."""
    _log(ctx, f"repo={ctx.obj.repo_path}")

    # TODO:
    # - Render baseline from lockfile (template@applied)
    # - Compare managed paths/sections to working copy
    # - Summarize: template-only, local-only, conflicts
    if json:
        _todo("drift --json")
    else:
        typer.echo("Drift report:")
        typer.echo("  [CI] .github/workflows/ci.yml — template-only changes")
        typer.echo("  [pyproject.toml] tool.ruff.line-length — both changed (conflict)")
        typer.echo("  [README.md] — unmanaged")


@app.command()
def version() -> None:
    """Print retemplar version."""
    typer.echo("retemplar 0.0.1")


# Support `python -m retemplar`
def _main() -> None:
    app()


if __name__ == "__main__":
    _main()
