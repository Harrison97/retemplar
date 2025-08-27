"""Essential tests for plan and apply functionality."""

import tempfile
from pathlib import Path

from retemplar.core import RetemplarCore
from retemplar.lockfile import LockfileManager


def test_plan_and_apply_basic():
    """Test basic plan and apply functionality."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Create template directory
        template_dir = tmpdir / "template"
        template_dir.mkdir()
        (template_dir / "config.yaml").write_text(
            "template: config\nversion: 2.0",
        )
        (template_dir / "src").mkdir()
        (template_dir / "src" / "main.py").write_text("# Template main file")

        # Create repo directory
        repo_dir = tmpdir / "repo"
        repo_dir.mkdir()

        # Use rat: prefix format
        template_ref = f"rat:{template_dir}"

        # Create lockfile
        lockfile_manager = LockfileManager(repo_dir)
        lock = lockfile_manager.create_adoption_lock(
            template_ref=template_ref,
            managed_paths=["config.yaml", "src/**"],
        )
        lockfile_manager.write(lock)

        core = RetemplarCore(repo_dir)

        # Test plan
        plan = core.plan_upgrade(template_ref)
        assert len(plan["changes"]) == 2  # config.yaml and src/main.py

        changes_by_file = {change["file"]: change for change in plan["changes"]}
        assert "config.yaml" in changes_by_file
        assert "src/main.py" in changes_by_file

        # Test apply
        result = core.apply_changes(template_ref)
        assert result["files_changed"] == 2
        assert result["conflicts_resolved"] == 0

        # Verify files were created
        assert (repo_dir / "config.yaml").exists()
        assert (repo_dir / "src" / "main.py").exists()
        assert "template: config" in (repo_dir / "config.yaml").read_text()


def test_enforce_strategy_overwrites():
    """Test that enforce strategy overwrites existing files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        template_dir = tmpdir / "template"
        template_dir.mkdir()
        (template_dir / "config.yaml").write_text(
            "template: config\nversion: 2.0",
        )

        repo_dir = tmpdir / "repo"
        repo_dir.mkdir()

        # Create existing file with different content
        (repo_dir / "config.yaml").write_text("local: config")

        template_ref = f"rat:{template_dir}"

        lockfile_manager = LockfileManager(repo_dir)
        lock = lockfile_manager.create_adoption_lock(
            template_ref=template_ref,
            managed_paths=["config.yaml"],
        )
        lockfile_manager.write(lock)

        core = RetemplarCore(repo_dir)
        result = core.apply_changes(template_ref)

        assert result["files_changed"] == 1

        # Should overwrite with template content
        content = (repo_dir / "config.yaml").read_text()
        assert "template: config" in content
        assert "version: 2.0" in content
