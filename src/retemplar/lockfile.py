"""
Lockfile management for .retemplar.lock files (MVP).

Simple read/write/validate operations for MVP RAT lockfiles.
"""

from pathlib import Path
from typing import List, Optional

import yaml
from pydantic import ValidationError

from .schema import RetemplarLock, TemplateSource, ManagedPath


class LockfileError(Exception):
    """Base exception for lockfile operations."""

    pass


class LockfileNotFoundError(LockfileError):
    """Raised when lockfile doesn't exist."""

    pass


class LockfileValidationError(LockfileError):
    """Raised when lockfile validation fails."""

    pass


class LockfileManager:
    """Manages .retemplar.lock file operations."""

    LOCKFILE_NAME = ".retemplar.lock"

    def __init__(self, repo_root: Path):
        """Initialize with repository root path."""
        self.repo_root = Path(repo_root).resolve()
        self.lockfile_path = self.repo_root / self.LOCKFILE_NAME

    def exists(self) -> bool:
        """Check if lockfile exists."""
        return self.lockfile_path.exists()

    def read(self) -> RetemplarLock:
        """Read and parse lockfile."""
        if not self.exists():
            raise LockfileNotFoundError(f"Lockfile not found at {self.lockfile_path}")

        try:
            content = self.lockfile_path.read_text(encoding="utf-8")
            data = yaml.safe_load(content)
            return RetemplarLock.model_validate(data)
        except yaml.YAMLError as e:
            raise LockfileValidationError(f"Invalid YAML in lockfile: {e}")
        except ValidationError as e:
            raise LockfileValidationError(f"Invalid lockfile schema: {e}")
        except Exception as e:
            raise LockfileError(f"Failed to read lockfile: {e}")

    def write(self, lock: RetemplarLock) -> None:
        """Write lockfile with atomic operation."""
        try:
            # Validate before writing
            validation_errors = self.validate(lock)
            if validation_errors:
                raise LockfileValidationError(f"Validation errors: {validation_errors}")

            # Atomic write using temp file
            temp_path = self.lockfile_path.with_suffix(".tmp")

            # Convert to dict and write as YAML
            data = lock.model_dump(by_alias=True, exclude_none=True)
            content = yaml.dump(data, default_flow_style=False, sort_keys=False)

            temp_path.write_text(content, encoding="utf-8")
            temp_path.rename(self.lockfile_path)

        except Exception as e:
            # Clean up temp file if it exists
            temp_path = self.lockfile_path.with_suffix(".tmp")
            if temp_path.exists():
                temp_path.unlink()
            raise LockfileError(f"Failed to write lockfile: {e}")

    def validate(self, lock: RetemplarLock) -> List[str]:
        """Validate lockfile and return list of error messages."""
        errors = []

        try:
            # Pydantic validation
            lock.model_validate(lock.model_dump())
        except ValidationError as e:
            for error in e.errors():
                errors.append(
                    f"{'.'.join(str(x) for x in error['loc'])}: {error['msg']}"
                )

        # Additional business logic validation
        if lock.managed_paths:
            seen_paths = set()
            for managed_path in lock.managed_paths:
                if managed_path.path in seen_paths:
                    errors.append(f"Duplicate managed path: {managed_path.path}")
                seen_paths.add(managed_path.path)

        return errors

    def create_adoption_lock(
        self,
        template_ref: str,
        managed_paths: Optional[List[str]] = None,
        ignore_paths: Optional[List[str]] = None,
    ) -> RetemplarLock:
        """Create initial lockfile for template adoption."""

        template_source = self._parse_template_ref(template_ref)

        # Convert managed paths to ManagedPath objects (default strategy: enforce)
        managed_path_objects = []
        for path in managed_paths or []:
            managed_path_objects.append(ManagedPath(path=path, strategy="enforce"))

        return RetemplarLock(
            template=template_source,
            version=f"{template_source.kind}@{template_source.ref}",
            managed_paths=managed_path_objects,
            ignore_paths=ignore_paths or [],
        )

    def _parse_template_ref(self, template_ref: str) -> TemplateSource:
        """Parse RAT template reference string."""

        # MVP: RAT format only: "rat:gh:org/repo@ref" or "rat:local:/path@ref"
        if not template_ref.startswith("rat:"):
            raise LockfileError(f"MVP only supports RAT templates: {template_ref}")

        ref_part = template_ref[4:]  # Remove "rat:" prefix

        if "@" not in ref_part:
            raise LockfileError(
                f"RAT template ref must include @version: {template_ref}"
            )

        repo_part, ref = ref_part.rsplit("@", 1)

        return TemplateSource(repo=repo_part, ref=ref)
