# src/retemplar/lockfile.py
"""
Lockfile management for .retemplar.lock files (MVP).

Simple read/write/validate operations for MVP RAT lockfiles.
"""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Dict, List, Optional

import yaml
from pydantic import ValidationError

# NOTE: adjust import to your schema filename
from .schema import RetemplarLock, TemplateSource, ManagedPath, RenderRule


class LockfileError(Exception):
    """Base exception for lockfile operations."""


class LockfileNotFoundError(LockfileError):
    """Raised when lockfile doesn't exist."""


class LockfileValidationError(LockfileError):
    """Raised when lockfile validation fails."""


class LockfileManager:
    """Manages .retemplar.lock file operations."""

    LOCKFILE_NAME = ".retemplar.lock"

    def __init__(self, repo_root: Path):
        self.repo_root = Path(repo_root).resolve()
        self.lockfile_path = self.repo_root / self.LOCKFILE_NAME

    # ------------------------
    # Basic ops
    # ------------------------

    def exists(self) -> bool:
        return self.lockfile_path.exists()

    def read(self) -> RetemplarLock:
        """Read and parse lockfile."""
        if not self.exists():
            raise LockfileNotFoundError(
                f"Lockfile not found at {self.lockfile_path}",
            )

        try:
            content = self.lockfile_path.read_text(encoding="utf-8")
            data = yaml.safe_load(content)
            if data is None:
                raise LockfileValidationError("Lockfile is empty.")
            return RetemplarLock.model_validate(data)
        except yaml.YAMLError as e:
            raise LockfileValidationError(
                f"Invalid YAML in lockfile: {e}",
            ) from e
        except ValidationError as e:
            raise LockfileValidationError(
                f"Invalid lockfile schema: {e}",
            ) from e
        except Exception as e:
            raise LockfileError(f"Failed to read lockfile: {e}") from e

    def write(self, lock: RetemplarLock) -> None:
        """Atomically write lockfile to disk."""
        # Validate first (Pydantic + business rules)
        errors = self.validate(lock)
        if errors:
            raise LockfileValidationError(f"Validation errors: {errors}")

        self.lockfile_path.parent.mkdir(parents=True, exist_ok=True)

        # Dump as YAML (safe_dump, stable order off for readability)
        payload = lock.model_dump(by_alias=True, exclude_none=True)
        content = yaml.safe_dump(
            payload,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )

        # Atomic replace dance
        tmp_dir = self.lockfile_path.parent
        with NamedTemporaryFile(
            "w",
            delete=False,
            dir=tmp_dir,
            prefix=".retemplar.",
            suffix=".tmp",
            encoding="utf-8",
        ) as tf:
            tmp_name = tf.name
            tf.write(content)
            tf.flush()
            os.fsync(tf.fileno())

        try:
            os.replace(
                tmp_name,
                self.lockfile_path,
            )  # atomic on same filesystem
            # fsync the directory to persist the rename on POSIX
            dir_fd = os.open(tmp_dir, os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except Exception as e:
            # best-effort cleanup
            try:
                os.unlink(tmp_name)
            except Exception:
                pass
            raise LockfileError(f"Failed to write lockfile: {e}") from e

    def validate(self, lock: RetemplarLock) -> List[str]:
        """Validate lockfile and return list of error messages."""
        errs: List[str] = []
        try:
            # Pydantic roundtrip check
            RetemplarLock.model_validate(lock.model_dump())
        except ValidationError as e:
            for error in e.errors():
                errs.append(
                    f"{'.'.join(map(str, error.get('loc', [])))}: {error.get('msg')}",
                )

        # Business rules: duplicate managed paths (shouldn’t happen due to schema dedupe but double-check)
        seen = set()
        for mp in lock.managed_paths or []:
            if mp.path in seen:
                errs.append(f"Duplicate managed path: {mp.path}")
            seen.add(mp.path)

        return errs

    # ------------------------
    # Creation helpers
    # ------------------------

    def create_adoption_lock(
        self,
        template_ref: str,
        managed_paths: Optional[List[str]] = None,
        ignore_paths: Optional[List[str]] = None,
        render_rules: Optional[List[Dict[str, str]]] = None,
    ) -> RetemplarLock:
        """Create initial lockfile for template adoption."""
        source = self._parse_template_ref(template_ref)

        # Managed paths default to enforce
        managed = [
            ManagedPath(path=p, strategy="enforce") for p in (managed_paths or [])
        ]

        # Render rules
        rules = [
            RenderRule(
                pattern=r["pattern"],
                replacement=r["replacement"],
                literal=bool(r.get("literal", False)),
            )
            for r in (render_rules or [])
        ]

        # Version/applied are auto-synced by model validators
        return RetemplarLock(
            template=source,
            version=None,  # let model set "rat@<ref>"
            managed_paths=managed,
            ignore_paths=ignore_paths or [],
            render_rules=rules,
        )

    # ------------------------
    # Parser
    # ------------------------

    def _parse_template_ref(self, template_ref: str) -> TemplateSource:
        """
        Parse RAT template reference.
        Accepted forms (MVP):
          - rat:gh:org/repo@vX
          - rat:./template-dir@vX
          - rat:/abs/path@vX
          - rat:./template-dir           (defaults ref='local')
        """
        if not template_ref.startswith("rat:"):
            raise LockfileError(
                f"MVP only supports RAT templates: {template_ref}",
            )

        ref_part = template_ref[4:]  # strip 'rat:'

        # If explicit @ref present, split it
        if "@" in ref_part:
            repo, ref = ref_part.rsplit("@", 1)
            if not repo:
                raise LockfileError(
                    f"Invalid RAT template (empty repo): {template_ref}",
                )
            if not ref:
                raise LockfileError(
                    f"Invalid RAT template (empty ref): {template_ref}",
                )
            return TemplateSource(repo=repo, ref=ref)

        # No @ref: must be a local path; default ref label
        if ref_part.startswith(("./", "/")) or (
            ref_part.startswith(".") and "/" in ref_part
        ):
            return TemplateSource(repo=ref_part, ref="local")

        # GitHub without @ is ambiguous; require explicit ref
        if ref_part.startswith("gh:"):
            raise LockfileError(
                f"GitHub RAT template ref must include @version: {template_ref}",
            )

        raise LockfileError(f"Unsupported RAT template format: {template_ref}")
