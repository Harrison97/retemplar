# src/retemplar/lock_schema.py
"""
Minimal lockfile schema for retemplar MVP (RAT-only, file-level ownership).

Deliberately omitted for v0:
- Template Packs (name/version)
- Section rules / 'patch' strategy
- Variables
- Lineage/audit trail
- Content fingerprints (we can add baseline_ref later)

Notes:
- Regex replacements use Python `re.sub` semantics (backrefs like "\\1"), not "$1".
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import List, Literal, Optional

from pydantic import (
    BaseModel,
    Field,
    ConfigDict,
    field_validator,
    model_validator,
)


# -----------------------
# Helpers
# -----------------------


def _posix(s: str) -> str:
    return PurePosixPath(s).as_posix()


# -----------------------
# Template source (RAT)
# -----------------------


class TemplateSource(BaseModel):
    """Repo-as-Template (RAT) source."""

    kind: Literal["rat"] = "rat"
    # e.g. 'gh:org/repo' OR local path like './template' or '/abs/path'
    repo: str
    # display/tag or commit-ish used at adopt/upgrade (for local you may synthesize 'SNAPSHOT-<hash>')
    ref: str
    # resolved commit SHA when known (git sources)
    commit: Optional[str] = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("repo")
    @classmethod
    def _validate_repo(cls, v: str) -> str:
        if not (
            v.startswith("gh:")
            or v.startswith("./")
            or v.startswith("/")
            or (v.startswith(".") and "/" in v)
        ):
            raise ValueError(
                "repo must start with 'gh:', './', '/', or a dotted local path containing '/'.",
            )
        return v

    @model_validator(mode="after")
    def _ensure_commit_if_sha(self) -> "TemplateSource":
        # If ref looks like a 40/64-char hex, treat as commit
        if self.commit is None and re.fullmatch(
            r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}",
            self.ref or "",
        ):
            self.commit = self.ref
        return self


# -----------------------
# Ownership configuration
# -----------------------

Strategy = Literal["enforce", "merge", "preserve"]  # MVP


class RenderRule(BaseModel):
    """
    Regex/literal substitution rule applied to template files during rendering.
    - When literal=True, use plain str.replace.
    - When literal=False, use re.sub with Python backrefs (\\1, \\2).
    """

    pattern: str
    replacement: str
    literal: bool = False

    model_config = ConfigDict(extra="forbid")


class ManagedPath(BaseModel):
    """
    File/dir pattern (POSIX-style) and strategy.
    Supports '**' and trailing '/**' directory globs, e.g.:
      - "pyproject.toml"
      - ".github/workflows/**"
      - "src/**"
    """

    path: str
    strategy: Strategy

    model_config = ConfigDict(extra="forbid")

    @field_validator("path")
    @classmethod
    def _norm_path(cls, v: str) -> str:
        if not v or v.strip() == "":
            raise ValueError("managed path cannot be empty")
        return _posix(v.strip())


# -----------------------
# Root lockfile
# -----------------------


class RetemplarLock(BaseModel):
    schema_version: str = "0.1.0"
    template: TemplateSource

    # Human-friendly display (auto-synced). Optional so older files load.
    version: Optional[str] = None

    # Scope
    managed_paths: List[ManagedPath] = Field(default_factory=list)
    ignore_paths: List[str] = Field(default_factory=list)

    # Render rules (regex/literal replacements)
    render_rules: List[RenderRule] = Field(default_factory=list)

    # The last applied ref/commit actually merged (acts as Base when you add 3-way)
    applied_ref: Optional[str] = None
    applied_commit: Optional[str] = None

    # Future-proof (optional today):
    # baseline_ref: "git:<sha>" or "dir:<relpath>" — leave None for MVP.
    baseline_ref: Optional[str] = None
    # consumer_commit: repo HEAD at time of apply (git only)
    consumer_commit: Optional[str] = None

    model_config = ConfigDict(extra="forbid")

    # --- Validators / normalizers ---

    @field_validator("ignore_paths")
    @classmethod
    def _norm_ignores(cls, v: List[str]) -> List[str]:
        seen = set()
        out: List[str] = []
        for p in v or []:
            p2 = _posix(p.strip())
            if p2 and p2 not in seen:
                seen.add(p2)
                out.append(p2)
        return out

    @model_validator(mode="after")
    def _dedupe_managed(self) -> "RetemplarLock":
        # Deduplicate by path; keep the first occurrence
        seen = set()
        deduped: List[ManagedPath] = []
        for r in self.managed_paths or []:
            if r.path not in seen:
                deduped.append(r)
                seen.add(r.path)
        self.managed_paths = deduped
        return self

    @model_validator(mode="after")
    def _sync_version(self) -> "RetemplarLock":
        expected = f"{self.template.kind}@{self.template.ref}"
        if not self.version or self.version != expected:
            self.version = expected
        return self

    @model_validator(mode="after")
    def _seed_applied_defaults(self) -> "RetemplarLock":
        # On first adopt, default applied_* to template values
        if self.applied_ref is None:
            self.applied_ref = self.template.ref
        if self.applied_commit is None:
            self.applied_commit = self.template.commit
        return self

    @field_validator("baseline_ref")
    @classmethod
    def _validate_baseline_ref(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if v.startswith("git:") and len(v) > 4:
            return v
        if v.startswith("dir:") and len(v) > 4:
            return _posix(v)
        raise ValueError("baseline_ref must be 'git:<sha>' or 'dir:<relpath>'")
