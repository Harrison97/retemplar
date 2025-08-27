"""Essential tests for managed path precedence."""

import tempfile
from pathlib import Path

from retemplar.core import RetemplarCore
from retemplar.lockfile import LockfileManager


def test_basic_managed_paths():
    """Test basic managed path functionality."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        template_dir = tmpdir / "template"
        template_dir.mkdir()
        (template_dir / "README.md").write_text("Template content")

        repo_dir = tmpdir / "repo"
        repo_dir.mkdir()

        lockfile_manager = LockfileManager(repo_dir)
        lock = lockfile_manager.create_adoption_lock(
            template_ref=f"rat:{template_dir}",
            managed_paths=["README.md"],
        )
        lockfile_manager.write(lock)

        core = RetemplarCore(repo_dir)
        plan = core.plan_upgrade(f"rat:{template_dir}")

        assert len(plan["changes"]) == 1
        assert plan["changes"][0]["file"] == "README.md"
        assert plan["changes"][0]["strategy"] == "enforce"
