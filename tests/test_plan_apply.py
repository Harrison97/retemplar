"""Tests for plan and apply functionality."""

import pytest
import tempfile
from pathlib import Path

from retemplar.core import RetemplarCore
from retemplar.lockfile import LockfileManager


@pytest.fixture
def temp_setup():
    """Create temporary directories for testing plan/apply."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Create template directory
        template_dir = tmpdir / "template"
        template_dir.mkdir()

        # Create some template files
        (template_dir / "config.yaml").write_text("template: config\nversion: 2.0")
        (template_dir / "src").mkdir()
        (template_dir / "src" / "main.py").write_text("# Template main file")

        # Create repo directory
        repo_dir = tmpdir / "repo"
        repo_dir.mkdir()

        # Create lockfile with managed paths
        lockfile_manager = LockfileManager(repo_dir)
        lock = lockfile_manager.create_adoption_lock(
            template_ref=f"rat:local:{template_dir}@v1.0",
            managed_paths=["config.yaml", "src/**"],
        )
        lockfile_manager.write(lock)

        yield {
            "template_dir": template_dir,
            "repo_dir": repo_dir,
            "lockfile_manager": lockfile_manager,
        }


def test_plan_with_new_files(temp_setup):
    """Test planning upgrade with new files from template."""
    repo_dir = temp_setup["repo_dir"]
    template_dir = temp_setup["template_dir"]

    core = RetemplarCore(repo_dir)

    # Plan upgrade to same version (should show files to create)
    plan = core.plan_upgrade(f"rat:local:{template_dir}@v2.0")

    assert plan["current_version"] == "rat@v1.0"
    assert plan["target_version"] == f"rat:local:{template_dir}@v2.0"
    assert len(plan["changes"]) == 2  # config.yaml and src/main.py

    # Check individual changes
    changes_by_file = {change["file"]: change for change in plan["changes"]}

    assert "config.yaml" in changes_by_file
    assert changes_by_file["config.yaml"]["type"] == "create"
    assert changes_by_file["config.yaml"]["strategy"] == "enforce"

    assert "src/main.py" in changes_by_file
    assert changes_by_file["src/main.py"]["type"] == "create"
    assert changes_by_file["src/main.py"]["strategy"] == "enforce"


def test_plan_with_existing_files(temp_setup):
    """Test planning upgrade with existing local files."""
    repo_dir = temp_setup["repo_dir"]
    template_dir = temp_setup["template_dir"]

    # Create some existing files in repo
    (repo_dir / "config.yaml").write_text("local: config\nversion: 1.0")
    (repo_dir / "src").mkdir()
    (repo_dir / "src" / "main.py").write_text("# Local main file")

    core = RetemplarCore(repo_dir)
    plan = core.plan_upgrade(f"rat:local:{template_dir}@v2.0")

    changes_by_file = {change["file"]: change for change in plan["changes"]}

    # Should show overwrite for existing files with enforce strategy
    assert changes_by_file["config.yaml"]["type"] == "overwrite"
    assert changes_by_file["src/main.py"]["type"] == "overwrite"


def test_apply_enforce_strategy(temp_setup):
    """Test applying changes with enforce strategy."""
    repo_dir = temp_setup["repo_dir"]
    template_dir = temp_setup["template_dir"]

    # Create existing file with different content
    (repo_dir / "config.yaml").write_text("local: config")

    core = RetemplarCore(repo_dir)
    result = core.apply_changes(f"rat:local:{template_dir}@v2.0")

    assert result["files_changed"] == 2  # config.yaml and src/main.py
    assert result["conflicts_resolved"] == 0

    # Check files were copied from template
    assert (repo_dir / "config.yaml").read_text() == "template: config\nversion: 2.0"
    assert (repo_dir / "src" / "main.py").read_text() == "# Template main file"

    # Check lockfile was updated
    lockfile_manager = LockfileManager(repo_dir)
    updated_lock = lockfile_manager.read()
    assert updated_lock.applied_ref == "v2.0"


def test_apply_preserve_strategy(temp_setup):
    """Test applying changes with preserve strategy."""
    repo_dir = temp_setup["repo_dir"]
    template_dir = temp_setup["template_dir"]

    # Update lockfile to use preserve strategy
    lockfile_manager = LockfileManager(repo_dir)
    lock = lockfile_manager.read()
    lock.managed_paths[0].strategy = "preserve"  # config.yaml
    lockfile_manager.write(lock)

    # Create existing file
    (repo_dir / "config.yaml").write_text("local: config")

    core = RetemplarCore(repo_dir)
    result = core.apply_changes(f"rat:local:{template_dir}@v2.0")

    # config.yaml should be preserved, src/main.py should be created
    assert result["files_changed"] == 1  # Only src/main.py

    # Check local file was preserved
    assert (repo_dir / "config.yaml").read_text() == "local: config"
    # But new file was still created
    assert (repo_dir / "src" / "main.py").read_text() == "# Template main file"
