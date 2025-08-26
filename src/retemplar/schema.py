# src/retemplar/lock_schema.py
"""
Minimal lockfile schema for retemplar MVP (RAT-only, file-level ownership).

Deliberately omitted for v0:
- Template Packs (name/version)
- Section rules / 'patch' strategy
- Variables
- Lineage/audit trail
- Fingerprints/snapshots (we rely on a git ref/commit)
"""

from __future__ import annotations
from typing import List, Literal, Optional
from pydantic import BaseModel, field_validator, model_validator


# ----- Template source (RAT-only) -----


class TemplateSource(BaseModel):
    kind: Literal["rat"] = "rat"
    repo: str  # e.g. 'gh:org/repo' (MVP: GitHub only)
    ref: str  # tag or SHA at adopt/upgrade
    commit: Optional[str] = None  # resolved SHA; set by adopt/apply

    @field_validator("repo")
    @classmethod
    def _validate_repo(cls, v: str) -> str:
        # MVP: support GitHub and local paths for testing
        if not (
            v.startswith("gh:") or v.startswith("github:") or v.startswith("local:")
        ):
            raise ValueError(
                "repo must start with 'gh:', 'github:', or 'local:' in MVP"
            )
        return v

    @model_validator(mode="after")
    def _ensure_commit_if_sha(self) -> "TemplateSource":
        # Optional: if 'ref' looks like a full SHA, mirror into 'commit'
        if (
            self.commit is None
            and len(self.ref) in (40, 64)
            and all(c in "0123456789abcdef" for c in self.ref.lower())
        ):
            self.commit = self.ref
        return self


# ----- Ownership configuration (file-level only) -----

Strategy = Literal["enforce", "merge", "preserve"]  # MVP: no 'patch' yet


class ManagedPath(BaseModel):
    path: str
    strategy: Strategy


# ----- Root lockfile -----


class RetemplarLock(BaseModel):
    schema_version: str = "0.1.0"  # MVP schema version
    template: TemplateSource

    # Display/helper field (derived). Keep in file for readability, but
    # we recompute on load if it doesn’t match.
    version: str

    # Scope
    managed_paths: List[ManagedPath] = []
    ignore_paths: List[str] = []

    # The last applied ref/commit we actually merged from (Base of 3-way)
    applied_ref: Optional[str] = None
    applied_commit: Optional[str] = None

    @model_validator(mode="after")
    def _sync_version(self) -> "RetemplarLock":
        expected = f"{self.template.kind}@{self.template.ref}"
        if self.version != expected:
            self.version = expected
        return self

    @model_validator(mode="after")
    def _sync_applied_defaults(self) -> "RetemplarLock":
        # On first adopt, default applied_* to template values
        if self.applied_ref is None:
            self.applied_ref = self.template.ref
        if self.applied_commit is None:
            self.applied_commit = self.template.commit
        return self
