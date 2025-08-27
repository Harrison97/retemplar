"""Tests for lockfile manager operations."""

import pytest
import tempfile
from pathlib import Path

from retemplar.lockfile import (
    LockfileManager,
    LockfileNotFoundError,
)


@pytest.fixture
def temp_repo():
    """Create temporary directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def test_lockfile_manager_initialization(temp_repo):
    """Test lockfile manager initialization."""
    manager = LockfileManager(temp_repo)
    assert manager.repo_root == temp_repo
    assert manager.lockfile_path == temp_repo / ".retemplar.lock"


def test_lockfile_exists_false_initially(temp_repo):
    """Test lockfile doesn't exist initially."""
    manager = LockfileManager(temp_repo)
    assert not manager.exists()


def test_read_nonexistent_lockfile_raises_error(temp_repo):
    """Test reading non-existent lockfile raises error."""
    manager = LockfileManager(temp_repo)

    with pytest.raises(LockfileNotFoundError):
        manager.read()


def test_create_adoption_lock_rat():
    """Test creating adoption lockfile for RAT template."""
    manager = LockfileManager(Path("/tmp"))  # Dummy path for testing

    lock = manager.create_adoption_lock("rat:gh:acme/main-svc@v2025.08.01")

    assert lock.template.kind == "rat"
    assert lock.template.repo == "gh:acme/main-svc"
    assert lock.template.ref == "v2025.08.01"
    assert lock.version == "rat@v2025.08.01"
    assert lock.applied_ref == "v2025.08.01"


def test_create_adoption_lock_local():
    """Test creating adoption lockfile for local RAT template."""
    manager = LockfileManager(Path("/tmp"))

    lock = manager.create_adoption_lock("rat:/path/to/template@main")

    assert lock.template.kind == "rat"
    assert lock.template.repo == "/path/to/template"
    assert lock.template.ref == "main"
    assert lock.version == "rat@main"


def test_invalid_template_ref_format():
    """Test invalid template reference format."""
    manager = LockfileManager(Path("/tmp"))

    with pytest.raises(Exception, match="MVP only supports RAT templates"):
        manager.create_adoption_lock("pack:python-service@1.0.0")


def test_write_and_read_lockfile(temp_repo):
    """Test writing and reading lockfile."""
    manager = LockfileManager(temp_repo)

    # Create a lockfile
    lock = manager.create_adoption_lock("rat:gh:acme/main-svc@v2025.08.01")

    # Write it
    manager.write(lock)
    assert manager.exists()

    # Read it back
    read_lock = manager.read()
    assert read_lock.template.kind == "rat"
    assert read_lock.template.repo == "gh:acme/main-svc"
    assert read_lock.version == "rat@v2025.08.01"


def test_validate_lockfile():
    """Test lockfile validation."""
    manager = LockfileManager(Path("/tmp"))

    # Create valid lockfile
    lock = manager.create_adoption_lock("rat:gh:acme/main-svc@v2025.08.01")
    errors = manager.validate(lock)
    assert len(errors) == 0

    # Create invalid lockfile (this would need more specific validation logic)
    # For now, just test the validation interface works
    assert isinstance(errors, list)
