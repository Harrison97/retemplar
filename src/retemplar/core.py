"""
Core retemplar operations (MVP).
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import logging

from .lockfile import LockfileManager, LockfileNotFoundError
from .utils.blockprotect import enforce_ours_blocks, find_ignore_blocks

from .utils import fs_utils
from .utils import merge_utils

logger = logging.getLogger(__name__)


@dataclass
class PlanItem:
    path: str
    strategy: str  # "enforce" | "preserve" | "merge"
    kind: str  # "create" | "overwrite" | "edit" | "delete" | "keep"
    note: str = ""
    had_conflict: bool = False


class RetemplarCore:
    """Core orchestrator for retemplar operations (refactored MVP)."""

    def __init__(self, repo_path: Path):
        self.repo_path = Path(repo_path).resolve()
        self.lockfile_manager = LockfileManager(self.repo_path)

    # ----- Public ops -----

    def adopt_template(
        self,
        template_ref: str,
        managed_paths: Optional[List[str]] = None,
        ignore_paths: Optional[List[str]] = None,
        render_rules: Optional[List[Dict[str, str]]] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Create initial .retemplar.lock (no baseline yet)."""
        if self.lockfile_manager.exists():
            raise ValueError("Repository already has .retemplar.lock")

        lock = self.lockfile_manager.create_adoption_lock(
            template_ref=template_ref,
            managed_paths=managed_paths,
            ignore_paths=ignore_paths,
            render_rules=render_rules,
        )

        if not dry_run:
            self.lockfile_manager.write(lock)

        return {
            "template": template_ref,
            "managed_paths": managed_paths or [],
            "ignore_paths": ignore_paths or [],
            "render_rules": render_rules or [],
            "lockfile_created": not dry_run,
        }

    def plan_upgrade(self, target_ref: str) -> Dict[str, Any]:
        """Compute a human-readable plan. 2-way semantics for now."""
        if not self.lockfile_manager.exists():
            raise LockfileNotFoundError(
                "No .retemplar.lock found. Run 'retemplar adopt' first.",
            )

        lock = self.lockfile_manager.read()
        target_src = self.lockfile_manager._parse_template_ref(target_ref)  # type: ignore[attr-defined]
        tpl_root = fs_utils.resolve_template_path(target_src.repo)

        # Template file set (relative posix)
        tpl_files = set(fs_utils.list_files(tpl_root))
        # Repo file set
        repo_files = set(fs_utils.list_files(self.repo_path))

        # Union for consideration
        candidate_files = sorted(tpl_files | repo_files)

        items: List[PlanItem] = []
        conflicts = 0

        for rel in candidate_files:
            if fs_utils.is_ignored(
                rel,
                getattr(lock, "ignore_paths", []) or [],
            ):
                continue
            rule = fs_utils.best_rule(
                rel,
                getattr(lock, "managed_paths", []) or [],
            )
            if not rule:
                continue

            strategy = getattr(rule, "strategy", "merge")
            in_tpl = rel in tpl_files
            in_repo = rel in repo_files

            if strategy == "preserve":
                if in_tpl and not in_repo:
                    items.append(
                        PlanItem(
                            rel,
                            strategy,
                            "create",
                            "template will create (preserve local thereafter)",
                        ),
                    )
                else:
                    items.append(
                        PlanItem(
                            rel,
                            strategy,
                            "keep",
                            "preserve local content",
                        ),
                    )
                continue

            if strategy == "enforce":
                if in_tpl and in_repo:
                    items.append(
                        PlanItem(
                            rel,
                            strategy,
                            "overwrite",
                            "template will overwrite local file",
                        ),
                    )
                elif in_tpl and not in_repo:
                    items.append(
                        PlanItem(
                            rel,
                            strategy,
                            "create",
                            "template will create file",
                        ),
                    )
                elif not in_tpl and in_repo:
                    items.append(
                        PlanItem(
                            rel,
                            strategy,
                            "delete",
                            "template removed file; will delete locally",
                        ),
                    )
                continue

            # strategy == "merge"
            if in_tpl and in_repo:  # Plan for actual file diffs
                ours = fs_utils.read_text(self.repo_path / rel)
                theirs = fs_utils.apply_render_rules_text(
                    fs_utils.read_text(tpl_root / rel) or "",
                    getattr(lock, "render_rules", None),
                )
                if ours is None or theirs is None:
                    had_conflict = True  # binary/unreadable
                else:
                    had_conflict = ours != theirs
                items.append(
                    PlanItem(
                        rel,
                        strategy,
                        "edit",
                        "merge changes",
                        had_conflict=had_conflict,
                    ),
                )
                if had_conflict:
                    conflicts += 1
            elif in_tpl and not in_repo:
                items.append(
                    PlanItem(
                        rel,
                        strategy,
                        "create",
                        "template adds file; adopt it",
                    ),
                )
            elif not in_tpl and in_repo:
                items.append(
                    PlanItem(
                        rel,
                        strategy,
                        "delete",
                        "template removed file; will delete",
                    ),
                )

        # Plan block-protection preview (consumer-side markers)
        block_events = self._scan_block_protection(
            getattr(lock, "managed_paths", []) or [],
        )

        return {
            "current_version": getattr(lock, "version", None),
            "target_version": target_ref,
            "changes": [
                {
                    "file": item.path,
                    "strategy": item.strategy,
                    "type": item.kind,
                    "note": item.note,
                    "had_conflict": item.had_conflict,
                    "matched_rule": fs_utils.best_rule(
                        item.path,
                        getattr(lock, "managed_paths", []) or [],
                    ).path,
                }
                for item in items
            ],
            "conflicts": conflicts,
            "block_protection": block_events,
        }

    def apply_changes(
        self,
        target_ref: str,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Apply the plan (non-interactive). 2-way for now; conflict markers on merge."""
        if not self.lockfile_manager.exists():
            raise LockfileNotFoundError(
                "No .retemplar.lock found. Run 'retemplar adopt' first.",
            )
        if not target_ref:
            raise ValueError("target_ref is required for apply")

        plan = self.plan_upgrade(target_ref)
        lock = self.lockfile_manager.read()
        target_src = self.lockfile_manager._parse_template_ref(target_ref)  # type: ignore[attr-defined]
        tpl_root = fs_utils.resolve_template_path(target_src.repo)

        files_changed = 0
        conflicts = 0

        for change in plan["changes"]:
            rel = change["file"]
            strat = change["strategy"]
            kind = change["type"]

            repo_p = self.repo_path / rel
            tpl_p = tpl_root / rel

            if strat == "preserve":
                if kind == "create" and not repo_p.exists():
                    if not dry_run:
                        merge_utils.copy_with_render_and_blockprotect(
                            tpl_p,
                            repo_p,
                            getattr(lock, "render_rules", None),
                            self.repo_path,
                        )
                    files_changed += 1
                continue

            if strat == "enforce":
                if kind in ("create", "overwrite"):
                    if not dry_run:
                        merge_utils.copy_with_render_and_blockprotect(
                            tpl_p,
                            repo_p,
                            getattr(lock, "render_rules", None),
                            self.repo_path,
                        )
                    files_changed += 1
                elif kind == "delete":
                    if not dry_run:
                        fs_utils.delete_file(repo_p)
                    files_changed += 1
                continue

            # merge
            if kind == "create":
                if not dry_run:
                    merge_utils.copy_with_render_and_blockprotect(
                        tpl_p,
                        repo_p,
                        getattr(lock, "render_rules", None),
                        self.repo_path,
                    )
                files_changed += 1
                continue

            if kind == "delete":
                if not dry_run:
                    fs_utils.delete_file(repo_p)
                files_changed += 1
                continue

            if kind == "edit":
                ours = fs_utils.read_text(repo_p)
                theirs = fs_utils.read_text(tpl_p)
                if ours is None or theirs is None:
                    # binary or unreadable → keep local, flag conflict
                    print(
                        f"[WARN] binary merge unsupported: {rel} (kept local)",
                    )
                    conflicts += 1
                    # do not overwrite; user can switch strategy to 'enforce' if desired
                    continue

                theirs = fs_utils.apply_render_rules_text(
                    theirs,
                    getattr(lock, "render_rules", None),
                )
                if ours == theirs:
                    # No change → skip writing, no conflict
                    continue

                # 2-way conflict markers (MVP)
                merged = merge_utils.merge_with_conflicts(ours, theirs)
                # post-merge: enforce consumer-side ignore blocks
                final, _report = enforce_ours_blocks(ours, merged)
                if not dry_run:
                    fs_utils.write_text(repo_p, final)
                conflicts += 1
                files_changed += 1
                continue

        # Best-effort lockfile update
        try:
            lock = self.lockfile_manager.read()

            # bring template source forward to the target
            new_template = lock.template.model_copy(
                update={
                    "repo": getattr(target_src, "repo", lock.template.repo),
                    "ref": getattr(target_src, "ref", lock.template.ref),
                    "commit": getattr(
                        target_src,
                        "commit",
                        lock.template.commit,
                    ),
                },
            )

            # recompute the human-readable version string
            new_version = f"{new_template.kind}@{new_template.ref}"

            updated = lock.model_copy(
                update={
                    "template": new_template,
                    "applied_ref": new_template.ref,
                    "applied_commit": new_template.commit,
                    "version": new_version,
                    # optionally set these if/when you wire them:
                    # "consumer_commit": current_repo_head_sha_or_none,
                    # "baseline_ref": None,  # for 2-way MVP leave unset
                },
            )

            self.lockfile_manager.write(updated)

        except Exception:
            # non-fatal: keep changes on disk even if lock update fails
            pass

        return {
            "applied_version": target_ref,
            "files_changed": files_changed,
            "conflicts_resolved": conflicts,
        }

    def detect_drift(self) -> Dict[str, Any]:
        """Detect drift between repo and baseline (placeholder for 3-way)."""

        if not self.lockfile_manager.exists():
            raise LockfileNotFoundError(
                "No .retemplar.lock found. Run 'retemplar adopt' first.",
            )

        current_lock = self.lockfile_manager.read()

        # TODO: Real implementation needs:
        # - Baseline resolution from applied_ref
        # - 3-way comparison: Base vs Ours vs Theirs
        # - Categorization of changes (template-only, local-only, conflicts)

        return {
            "baseline_version": current_lock.applied_ref or current_lock.template.ref,
            "template_only_changes": [],  # TODO: implement with baseline
            "local_only_changes": [],  # TODO: implement with baseline
            "conflicts": [],  # TODO: implement with baseline
            "unmanaged_files": [],  # TODO: implement
        }

    def _scan_block_protection(
        self,
        managed_rules: List[Any],
    ) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        ignore_patterns = (
            getattr(self.lockfile_manager.read(), "ignore_paths", [])
            if self.lockfile_manager.exists()
            else []
        )
        for rel in sorted(set(fs_utils.list_files(self.repo_path))):
            if any(fs_utils.match(rel, pat) for pat in ignore_patterns):
                continue
            rule = fs_utils.best_rule(rel, managed_rules)
            if not rule:
                continue
            p = self.repo_path / rel
            s = fs_utils.read_text(p)
            if s is None:
                continue
            blocks = find_ignore_blocks(s)
            if blocks:
                events.append(
                    {
                        "file": rel,
                        "blocks": [
                            {
                                "id": bid,
                                "start": span.start + 1,
                                "end": span.end + 1,
                            }
                            for bid, span in blocks.items()
                        ],
                    },
                )
        return events
