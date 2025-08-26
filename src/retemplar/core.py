"""
Core retemplar operations (MVP).

Simple orchestration of lockfile operations for RAT adoption and basic operations.
"""

import shutil
import difflib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .lockfile import LockfileManager, LockfileNotFoundError


class RetemplarCore:
    """Core orchestrator for retemplar operations."""

    def __init__(self, repo_path: Path):
        """Initialize with repository root path."""
        self.repo_path = Path(repo_path).resolve()
        self.lockfile_manager = LockfileManager(self.repo_path)

    def _resolve_template_path(self, template_repo: str) -> Path:
        """Resolve template repo string to filesystem path."""
        if template_repo.startswith("local:"):
            # Handle local:path format
            local_path = template_repo[6:]  # Remove "local:" prefix
            return Path(local_path).resolve()
        elif template_repo.startswith(("gh:", "github:")):
            # TODO: Clone/fetch GitHub repo for real implementation
            raise NotImplementedError("GitHub repos not supported yet in MVP")
        else:
            raise ValueError(f"Unsupported repo format: {template_repo}")

    def _get_template_files(self, template_path: Path) -> Dict[str, Path]:
        """Get all files in template directory."""
        files = {}
        if not template_path.exists():
            raise ValueError(f"Template path does not exist: {template_path}")

        for file_path in template_path.rglob("*"):
            if file_path.is_file():
                # Store relative path as key
                rel_path = file_path.relative_to(template_path)
                files[str(rel_path)] = file_path

        return files

    def adopt_template(
        self,
        template_ref: str,
        managed_paths: Optional[List[str]] = None,
        ignore_paths: Optional[List[str]] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Adopt a RAT template and create .retemplar.lock file."""

        if self.lockfile_manager.exists():
            raise ValueError("Repository already has .retemplar.lock file")

        lock = self.lockfile_manager.create_adoption_lock(
            template_ref=template_ref,
            managed_paths=managed_paths,
            ignore_paths=ignore_paths,
        )

        if not dry_run:
            self.lockfile_manager.write(lock)

        return {
            "template": template_ref,
            "managed_paths": managed_paths or [],
            "ignore_paths": ignore_paths or [],
            "lockfile_created": not dry_run,
        }

    def plan_upgrade(self, target_ref: str) -> Dict[str, Any]:
        """Plan upgrade to new RAT version."""

        if not self.lockfile_manager.exists():
            raise LockfileNotFoundError(
                "No .retemplar.lock found. Run 'retemplar adopt' first."
            )

        current_lock = self.lockfile_manager.read()

        # Parse target template reference
        target_source = self.lockfile_manager._parse_template_ref(target_ref)

        # Get current and target template files
        current_template_path = self._resolve_template_path(current_lock.template.repo)
        target_template_path = self._resolve_template_path(target_source.repo)

        current_files = self._get_template_files(current_template_path)
        target_files = self._get_template_files(target_template_path)

        # Plan changes based on managed paths with proper precedence
        changes = []
        conflicts = 0
        processed_files = set()

        # Handle files that exist in new template (additions/modifications)
        for file_rel_path in target_files:
            # Check if file should be ignored (highest precedence)
            if self._is_ignored(file_rel_path, current_lock.ignore_paths):
                continue

            # Find the most specific matching managed path rule
            matching_rule = self._find_best_matching_rule(
                file_rel_path, current_lock.managed_paths
            )

            if not matching_rule:
                # File not managed, skip it
                continue

            if file_rel_path in processed_files:
                continue
            processed_files.add(file_rel_path)

            repo_file = self.repo_path / file_rel_path
            strategy = matching_rule.strategy

            change = {
                "file": file_rel_path,
                "strategy": strategy,
                "type": "unknown",
                "matched_rule": matching_rule.path,
            }

            if strategy == "enforce":
                if repo_file.exists():
                    change["type"] = "overwrite"
                    change["description"] = (
                        f"Template will overwrite local file (rule: {matching_rule.path})"
                    )
                else:
                    change["type"] = "create"
                    change["description"] = (
                        f"Template will create new file (rule: {matching_rule.path})"
                    )

            elif strategy == "preserve":
                if repo_file.exists():
                    change["type"] = "skip"
                    change["description"] = (
                        f"Local file preserved, template ignored (rule: {matching_rule.path})"
                    )
                else:
                    change["type"] = "create"
                    change["description"] = (
                        f"Template will create new file, no conflict (rule: {matching_rule.path})"
                    )

            elif strategy == "merge":
                if repo_file.exists():
                    change["type"] = "conflict"
                    change["description"] = (
                        f"Manual merge required (rule: {matching_rule.path})"
                    )
                    conflicts += 1
                else:
                    change["type"] = "create"
                    change["description"] = (
                        f"Template will create new file (rule: {matching_rule.path})"
                    )

            changes.append(change)

        # Handle files that are managed but no longer exist in template (deletions)
        # Check all managed paths to see if their files are missing from the new template
        for managed_path in current_lock.managed_paths:
            # Find all files that match this managed path pattern
            repo_files_matching_pattern = []

            # Check all files in repo directory that match the pattern
            for repo_file in self.repo_path.rglob("*"):
                if repo_file.is_file():
                    rel_path = repo_file.relative_to(self.repo_path)
                    if self._matches_pattern(str(rel_path), managed_path.path):
                        repo_files_matching_pattern.append(str(rel_path))

            # For each file matching the pattern, check if it's missing from template
            for file_rel_path in repo_files_matching_pattern:
                # Skip if file still exists in new template (already handled above)
                if file_rel_path in target_files:
                    continue

                # Skip if file should be ignored
                if self._is_ignored(file_rel_path, current_lock.ignore_paths):
                    continue

                if file_rel_path in processed_files:
                    continue
                processed_files.add(file_rel_path)

                repo_file = self.repo_path / file_rel_path
                if not repo_file.exists():
                    # File doesn't exist in repo anyway, no action needed
                    continue

                strategy = managed_path.strategy

                change = {
                    "file": file_rel_path,
                    "strategy": strategy,
                    "type": "unknown",
                    "matched_rule": managed_path.path,
                }

                if strategy == "enforce":
                    change["type"] = "delete"
                    change["description"] = (
                        f"File no longer in template, will delete locally (rule: {managed_path.path})"
                    )

                elif strategy == "preserve":
                    change["type"] = "keep"
                    change["description"] = (
                        f"File no longer in template, but preserved locally (rule: {managed_path.path})"
                    )

                elif strategy == "merge":
                    # Check if file was modified since last apply (simplified: always consider it modified for MVP)
                    if self._file_was_modified_locally(repo_file, current_lock):
                        change["type"] = "orphan"
                        change["description"] = (
                            f"File no longer in template, but locally modified - marked as orphaned (rule: {managed_path.path})"
                        )
                        conflicts += 1
                    else:
                        change["type"] = "delete"
                        change["description"] = (
                            f"File no longer in template, no local changes - will delete (rule: {managed_path.path})"
                        )

                changes.append(change)

        return {
            "current_version": current_lock.version,
            "target_version": target_ref,
            "changes": changes,
            "conflicts": conflicts,
        }

    def _matches_pattern(self, file_path: str, pattern: str) -> bool:
        """Simple pattern matching for MVP."""
        if pattern.endswith("/**"):
            # Directory glob like "src/**"
            dir_prefix = pattern[:-3]  # Remove "/**"
            return file_path.startswith(dir_prefix + "/") or file_path == dir_prefix
        elif "*" in pattern:
            # Simple wildcard (not implemented yet)
            return False
        else:
            # Exact match
            return file_path == pattern

    def _is_ignored(self, file_path: str, ignore_patterns: List[str]) -> bool:
        """Check if file should be ignored."""
        for pattern in ignore_patterns:
            if self._matches_pattern(file_path, pattern):
                return True
        return False

    def _find_best_matching_rule(self, file_path: str, managed_paths):
        """Find the most specific rule that matches this file."""
        matching_rules = []

        for managed_path in managed_paths:
            if self._matches_pattern(file_path, managed_path.path):
                matching_rules.append(managed_path)

        if not matching_rules:
            return None

        # Return the most specific rule (exact matches beat globs)
        # Sort by specificity: exact matches first, then by length (more specific paths)
        def rule_specificity(rule):
            path = rule.path
            if "/**" in path:
                return (1, len(path))  # Directory glob
            elif "*" in path:
                return (2, len(path))  # Other glob
            else:
                return (0, len(path))  # Exact match (highest priority)

        return sorted(matching_rules, key=rule_specificity)[0]

    def _file_was_modified_locally(self, repo_file: Path, current_lock) -> bool:
        """Check if file was modified since last apply (simplified for MVP)."""
        # TODO: For full implementation, compare against baseline from applied_ref
        # For MVP, assume all existing files were modified (conservative approach)
        return repo_file.exists()

    def apply_changes(self, target_ref: Optional[str] = None) -> Dict[str, Any]:
        """Apply planned changes."""

        if not self.lockfile_manager.exists():
            raise LockfileNotFoundError(
                "No .retemplar.lock found. Run 'retemplar adopt' first."
            )

        if not target_ref:
            raise ValueError("target_ref is required for apply")

        # Get the plan first
        plan = self.plan_upgrade(target_ref)

        # All conflicts are now auto-resolvable:
        # - merge conflicts get conflict markers
        # - orphan conflicts get .orphaned suffix
        # No interactive mode needed

        # Parse target template reference
        target_source = self.lockfile_manager._parse_template_ref(target_ref)
        target_template_path = self._resolve_template_path(target_source.repo)

        # Read current lock for baseline access
        current_lock = self.lockfile_manager.read()

        files_changed = 0
        conflicts_resolved = 0

        # Apply each change (ignore paths are already filtered out in plan)
        for change in plan["changes"]:
            file_path = change["file"]
            strategy = change["strategy"]
            change_type = change["type"]

            repo_file_path = self.repo_path / file_path
            template_file_path = target_template_path / file_path

            if strategy == "enforce":
                if change_type in ("create", "overwrite"):
                    # Copy from template to repo
                    self._copy_file(template_file_path, repo_file_path)
                    files_changed += 1
                elif change_type == "delete":
                    # Template deleted file, enforce means delete locally too
                    self._delete_file(repo_file_path)
                    files_changed += 1

            elif strategy == "preserve":
                if change_type == "create":
                    # Only create if file doesn't exist locally
                    self._copy_file(template_file_path, repo_file_path)
                    files_changed += 1
                # Skip existing files (preserve local changes)
                # For "keep" type (template deleted but we preserve), do nothing

            elif strategy == "merge":
                if change_type == "conflict":
                    # Perform 3-way merge
                    local_content = repo_file_path.read_text(encoding="utf-8")
                    remote_content = template_file_path.read_text(encoding="utf-8")
                    baseline_content = self._get_baseline_content()

                    merged_content, has_conflicts = self._three_way_merge(
                        baseline_content, local_content, remote_content
                    )

                    # Write the merged content (with conflict markers if needed)
                    repo_file_path.write_text(merged_content, encoding="utf-8")
                    files_changed += 1

                    if has_conflicts:
                        conflicts_resolved += 1

                elif change_type == "create":
                    self._copy_file(template_file_path, repo_file_path)
                    files_changed += 1
                elif change_type == "delete":
                    # Template deleted file, no local changes, safe to delete
                    self._delete_file(repo_file_path)
                    files_changed += 1
                elif change_type == "orphan":
                    # Always orphan the file (mark with .orphaned suffix)
                    # In interactive mode, could ask user for different behavior
                    self._mark_orphaned(repo_file_path)
                    conflicts_resolved += 1

        # Update lockfile with new applied version
        current_lock = self.lockfile_manager.read()
        updated_lock = current_lock.model_copy(
            update={
                "applied_ref": target_source.ref,
                "applied_commit": target_source.commit,
            }
        )
        self.lockfile_manager.write(updated_lock)

        return {
            "applied_version": target_ref,
            "files_changed": files_changed,
            "conflicts_resolved": conflicts_resolved,
        }

    def _copy_file(self, src: Path, dst: Path) -> None:
        """Copy file from src to dst, creating parent directories if needed."""
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    def _delete_file(self, file_path: Path) -> None:
        """Delete file if it exists."""
        if file_path.exists():
            file_path.unlink()
            # Clean up empty parent directories
            try:
                file_path.parent.rmdir()
            except OSError:
                # Directory not empty or other error, ignore
                pass

    def _mark_orphaned(self, file_path: Path) -> None:
        """Mark file as orphaned by renaming with .orphaned suffix."""
        if file_path.exists():
            orphaned_path = file_path.with_suffix(file_path.suffix + ".orphaned")
            file_path.rename(orphaned_path)

    def _three_way_merge(
        self, base_content: str, local_content: str, remote_content: str
    ) -> Tuple[str, bool]:
        """
        Perform 3-way merge like git.

        Args:
            base_content: Content from baseline (applied_ref)
            local_content: Current content in repo
            remote_content: Content from new template

        Returns:
            (merged_content, has_conflicts)
        """
        base_lines = base_content.splitlines(keepends=True)
        local_lines = local_content.splitlines(keepends=True)
        remote_lines = remote_content.splitlines(keepends=True)

        # Use difflib to create a 3-way merge
        # This is a simplified version - real git merge is more complex

        # Get diffs from base to local and base to remote
        local_diff = list(difflib.unified_diff(base_lines, local_lines, n=0))
        remote_diff = list(difflib.unified_diff(base_lines, remote_lines, n=0))

        # If one side is unchanged, use the other side
        if not local_diff or local_diff == []:  # No local changes
            return remote_content, False
        if not remote_diff or remote_diff == []:  # No remote changes
            return local_content, False

        # Both sides changed - attempt automatic merge or create conflict markers
        return self._merge_with_conflicts(local_content, remote_content)

    def _merge_with_conflicts(
        self, local_content: str, remote_content: str
    ) -> Tuple[str, bool]:
        """Create merge with conflict markers when automatic merge fails."""

        # For MVP, create simple conflict markers for the entire file
        # A more sophisticated implementation would do line-by-line or hunk-by-hunk merging

        merged_lines = [
            "<<<<<<< LOCAL (current)\n",
            local_content,
            "=======\n",
            remote_content,
            ">>>>>>> REMOTE (template)\n",
        ]

        # Ensure newlines are handled correctly
        if not local_content.endswith("\n"):
            merged_lines[1] += "\n"
        if not remote_content.endswith("\n"):
            merged_lines[3] += "\n"

        return "".join(merged_lines), True

    def _get_baseline_content(self) -> str:
        """Get the baseline content for 3-way merge (simplified for MVP)."""

        # TODO: For full implementation, this would:
        # 1. Checkout the applied_ref from git
        # 2. Or read from a stored baseline snapshot
        # 3. Or reconstruct from the lockfile fingerprint

        # For MVP: assume the baseline is empty (file didn't exist before)
        # This makes it a 2-way merge in practice
        return ""

    def detect_drift(self) -> Dict[str, Any]:
        """Detect drift from applied baseline (placeholder)."""

        if not self.lockfile_manager.exists():
            raise LockfileNotFoundError(
                "No .retemplar.lock found. Run 'retemplar adopt' first."
            )

        current_lock = self.lockfile_manager.read()

        # TODO: Real implementation will compare against applied_ref baseline
        return {
            "baseline_version": current_lock.applied_ref or current_lock.template.ref,
            "template_only_changes": [],
            "local_only_changes": [],
            "conflicts": [],
            "unmanaged_files": [],
        }
