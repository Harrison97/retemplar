"""Tests for handling template file deletions."""

import pytest
import tempfile
from pathlib import Path

from retemplar.core import RetemplarCore
from retemplar.lockfile import LockfileManager
from retemplar.schema import ManagedPath


@pytest.fixture
def deletion_setup():
    """Create setup for testing file deletions."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Create old template directory (v1)
        old_template_dir = tmpdir / "template_v1"
        old_template_dir.mkdir()
        (old_template_dir / "keep_file.txt").write_text("keep me")
        (old_template_dir / "delete_file.txt").write_text("delete me")
        (old_template_dir / "merge_file.txt").write_text("merge me")

        # Create new template directory (v2) - some files removed
        new_template_dir = tmpdir / "template_v2"
        new_template_dir.mkdir()
        (new_template_dir / "keep_file.txt").write_text("keep me updated")
        # delete_file.txt and merge_file.txt are deleted from template

        # Create repo directory
        repo_dir = tmpdir / "repo"
        repo_dir.mkdir()

        # Create lockfile pointing to old template
        lockfile_manager = LockfileManager(repo_dir)
        lock = lockfile_manager.create_adoption_lock(
            template_ref=f"rat:local:{old_template_dir}@v1.0"
        )

        # Add managed paths with different strategies
        lock.managed_paths = [
            ManagedPath(path="keep_file.txt", strategy="enforce"),
            ManagedPath(path="delete_file.txt", strategy="enforce"),
            ManagedPath(path="merge_file.txt", strategy="merge"),
        ]

        # Set applied_ref to v1.0 to simulate previous apply
        lock.applied_ref = "v1.0"
        lockfile_manager.write(lock)

        # Create local files in repo (as if previously applied)
        (repo_dir / "keep_file.txt").write_text("keep me")
        (repo_dir / "delete_file.txt").write_text("delete me")
        (repo_dir / "merge_file.txt").write_text(
            "merge me - locally modified!"
        )  # Modified

        yield {
            "old_template_dir": old_template_dir,
            "new_template_dir": new_template_dir,
            "repo_dir": repo_dir,
            "lockfile_manager": lockfile_manager,
        }


def test_plan_shows_deletions(deletion_setup):
    """Test that plan correctly identifies file deletions."""
    repo_dir = deletion_setup["repo_dir"]
    new_template_dir = deletion_setup["new_template_dir"]

    core = RetemplarCore(repo_dir)
    plan = core.plan_upgrade(f"rat:local:{new_template_dir}@v2.0")

    changes_by_file = {change["file"]: change for change in plan["changes"]}

    # keep_file.txt should be updated (still in template)
    assert "keep_file.txt" in changes_by_file
    assert changes_by_file["keep_file.txt"]["type"] == "overwrite"

    # delete_file.txt should be marked for deletion (enforce strategy)
    assert "delete_file.txt" in changes_by_file
    assert changes_by_file["delete_file.txt"]["type"] == "delete"
    assert changes_by_file["delete_file.txt"]["strategy"] == "enforce"

    # merge_file.txt should be marked as orphaned (merge strategy + locally modified)
    assert "merge_file.txt" in changes_by_file
    assert changes_by_file["merge_file.txt"]["type"] == "orphan"
    assert changes_by_file["merge_file.txt"]["strategy"] == "merge"

    # Should have 1 conflict (the orphaned file)
    assert plan["conflicts"] == 1


def test_apply_enforce_deletion(deletion_setup):
    """Test that enforce strategy actually deletes files."""
    repo_dir = deletion_setup["repo_dir"]
    new_template_dir = deletion_setup["new_template_dir"]

    # Verify file exists before apply
    delete_file = repo_dir / "delete_file.txt"
    assert delete_file.exists()

    core = RetemplarCore(repo_dir)
    result = core.apply_changes(f"rat:local:{new_template_dir}@v2.0")

    # File should be deleted
    assert not delete_file.exists()

    # Should report files changed (keep_file.txt updated + delete_file.txt deleted)
    assert result["files_changed"] == 2


def test_apply_merge_orphaning(deletion_setup):
    """Test that merge strategy orphans modified files."""
    repo_dir = deletion_setup["repo_dir"]
    new_template_dir = deletion_setup["new_template_dir"]

    merge_file = repo_dir / "merge_file.txt"
    assert merge_file.exists()
    assert "locally modified" in merge_file.read_text()

    core = RetemplarCore(repo_dir)
    result = core.apply_changes(f"rat:local:{new_template_dir}@v2.0")

    # Original file should be gone
    assert not merge_file.exists()

    # Should have orphaned version
    orphaned_file = repo_dir / "merge_file.txt.orphaned"
    assert orphaned_file.exists()
    assert "locally modified" in orphaned_file.read_text()

    # Should report conflict resolved
    assert result["conflicts_resolved"] == 1


def test_apply_preserve_strategy_keeps_deleted_files():
    """Test preserve strategy with deleted files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Template v1 has file, v2 deletes it
        template_v1 = tmpdir / "template_v1"
        template_v1.mkdir()
        (template_v1 / "preserve_me.txt").write_text("original")

        template_v2 = tmpdir / "template_v2"
        template_v2.mkdir()
        # preserve_me.txt deleted from template

        repo_dir = tmpdir / "repo"
        repo_dir.mkdir()

        # Create lockfile with preserve strategy
        lockfile_manager = LockfileManager(repo_dir)
        lock = lockfile_manager.create_adoption_lock(f"rat:local:{template_v1}@v1.0")
        lock.managed_paths = [ManagedPath(path="preserve_me.txt", strategy="preserve")]
        lock.applied_ref = "v1.0"
        lockfile_manager.write(lock)

        # Create local file
        preserve_file = repo_dir / "preserve_me.txt"
        preserve_file.write_text("local changes")

        # Apply upgrade
        core = RetemplarCore(repo_dir)
        plan = core.plan_upgrade(f"rat:local:{template_v2}@v2.0")

        changes_by_file = {change["file"]: change for change in plan["changes"]}
        assert changes_by_file["preserve_me.txt"]["type"] == "keep"

        # Apply changes
        result = core.apply_changes(f"rat:local:{template_v2}@v2.0")

        # File should still exist and be unchanged
        assert preserve_file.exists()
        assert preserve_file.read_text() == "local changes"
