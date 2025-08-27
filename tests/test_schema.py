"""Tests for lockfile schema validation (MVP)."""

import pytest
from pydantic import ValidationError

from retemplar.schema import RetemplarLock, TemplateSource, ManagedPath


def test_rat_template_source():
    """Test RAT template source validation."""
    source = TemplateSource(repo="gh:acme/main-svc", ref="v2025.08.01")
    assert source.kind == "rat"  # Default
    assert source.repo == "gh:acme/main-svc"
    assert source.ref == "v2025.08.01"


def test_template_source_invalid_repo():
    """Test template source with invalid repo format."""
    with pytest.raises(
        ValidationError,
        match="repo must start with 'gh:', './', '/', or a dotted local path containing '/'",
    ):
        TemplateSource(repo="invalid:format", ref="v1.0.0")


def test_managed_path_enforce_strategy():
    """Test managed path with enforce strategy."""
    managed_path = ManagedPath(path=".github/workflows/**", strategy="enforce")
    assert managed_path.path == ".github/workflows/**"
    assert managed_path.strategy == "enforce"


def test_complete_lockfile():
    """Test complete lockfile validation."""
    template = TemplateSource(repo="gh:acme/main-svc", ref="v2025.08.01")

    managed_path = ManagedPath(path=".github/workflows/**", strategy="enforce")

    lock = RetemplarLock(
        template=template,
        version="rat@v2025.08.01",
        managed_paths=[managed_path],
    )

    assert lock.schema_version == "0.1.0"
    assert lock.template.kind == "rat"
    assert lock.version == "rat@v2025.08.01"
    assert len(lock.managed_paths) == 1
    assert lock.applied_ref == "v2025.08.01"  # Should default to template.ref


def test_version_string_computation():
    """Test version string is computed correctly."""
    template = TemplateSource(repo="gh:acme/main-svc", ref="v2025.08.01")

    lock = RetemplarLock(
        template=template,
        version="wrong-version",  # Will be auto-corrected
    )

    # Should auto-correct version
    assert lock.version == "rat@v2025.08.01"
