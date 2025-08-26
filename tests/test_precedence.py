"""Tests for rule precedence and ignore path handling."""

import pytest
import tempfile
from pathlib import Path

from retemplar.core import RetemplarCore
from retemplar.lockfile import LockfileManager
from retemplar.schema import ManagedPath


@pytest.fixture
def complex_setup():
    """Create setup with overlapping rules and ignore paths."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Create template directory
        template_dir = tmpdir / "template"
        template_dir.mkdir()

        # Create nested template files
        (template_dir / "config.yaml").write_text("template config")
        (template_dir / "test_folder").mkdir()
        (template_dir / "test_folder" / "file1.py").write_text("# Template file1")
        (template_dir / "test_folder" / "file2.py").write_text("# Template file2")
        (template_dir / "test_folder" / "special.py").write_text("# Template special")

        # Create repo directory
        repo_dir = tmpdir / "repo"
        repo_dir.mkdir()

        # Create lockfile with complex rules
        lockfile_manager = LockfileManager(repo_dir)
        lock = lockfile_manager.create_adoption_lock(
            template_ref=f"rat:local:{template_dir}@v1.0"
        )

        # Add complex managed paths with overlapping rules
        lock.managed_paths = [
            ManagedPath(path="test_folder/**", strategy="enforce"),  # Broad rule
            ManagedPath(
                path="test_folder/special.py", strategy="preserve"
            ),  # Specific override
            ManagedPath(path="config.yaml", strategy="enforce"),
        ]

        # Add ignore paths
        lock.ignore_paths = ["test_folder/file2.py"]  # Should be completely ignored

        lockfile_manager.write(lock)

        yield {
            "template_dir": template_dir,
            "repo_dir": repo_dir,
            "lockfile_manager": lockfile_manager,
        }


def test_ignore_paths_work(complex_setup):
    """Test that ignore paths completely exclude files."""
    repo_dir = complex_setup["repo_dir"]
    template_dir = complex_setup["template_dir"]

    core = RetemplarCore(repo_dir)
    plan = core.plan_upgrade(f"rat:local:{template_dir}@v2.0")

    # Check that ignored file is not in plan at all
    files_in_plan = {change["file"] for change in plan["changes"]}
    assert "test_folder/file2.py" not in files_in_plan

    # But other files should be there
    assert "test_folder/file1.py" in files_in_plan
    assert "test_folder/special.py" in files_in_plan
    assert "config.yaml" in files_in_plan


def test_specific_rules_override_general_ones(complex_setup):
    """Test that specific rules take precedence over general ones."""
    repo_dir = complex_setup["repo_dir"]
    template_dir = complex_setup["template_dir"]

    core = RetemplarCore(repo_dir)
    plan = core.plan_upgrade(f"rat:local:{template_dir}@v2.0")

    changes_by_file = {change["file"]: change for change in plan["changes"]}

    # test_folder/file1.py should use the general rule (enforce)
    assert changes_by_file["test_folder/file1.py"]["strategy"] == "enforce"
    assert changes_by_file["test_folder/file1.py"]["matched_rule"] == "test_folder/**"

    # test_folder/special.py should use the specific rule (preserve)
    assert changes_by_file["test_folder/special.py"]["strategy"] == "preserve"
    assert (
        changes_by_file["test_folder/special.py"]["matched_rule"]
        == "test_folder/special.py"
    )


def test_apply_respects_ignore_and_preserve(complex_setup):
    """Test that apply actually respects ignore and preserve rules."""
    repo_dir = complex_setup["repo_dir"]
    template_dir = complex_setup["template_dir"]

    # Create some existing files
    (repo_dir / "test_folder").mkdir()
    (repo_dir / "test_folder" / "file1.py").write_text("# Local file1")
    (repo_dir / "test_folder" / "special.py").write_text(
        "# Local special - should be preserved"
    )
    (repo_dir / "test_folder" / "file2.py").write_text(
        "# Local file2 - should be ignored"
    )

    core = RetemplarCore(repo_dir)
    result = core.apply_changes(f"rat:local:{template_dir}@v2.0")

    # Should change file1 (enforce), preserve special, ignore file2, create config
    assert result["files_changed"] == 2  # file1.py + config.yaml

    # Check actual file contents
    assert (repo_dir / "config.yaml").read_text() == "template config"
    assert (
        repo_dir / "test_folder" / "file1.py"
    ).read_text() == "# Template file1"  # Enforced
    assert (
        repo_dir / "test_folder" / "special.py"
    ).read_text() == "# Local special - should be preserved"  # Preserved
    assert (
        repo_dir / "test_folder" / "file2.py"
    ).read_text() == "# Local file2 - should be ignored"  # Ignored

    # file2.py from template should not have been created since it's ignored
    # (the local one remains untouched)


def test_clean_lockfile_validation():
    """Test that conflicting rules in lockfile are detected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_dir = Path(tmpdir)
        lockfile_manager = LockfileManager(repo_dir)

        # This should be valid - ignore takes precedence, so no conflict
        lock = lockfile_manager.create_adoption_lock("rat:local:/tmp@v1.0")
        lock.managed_paths = [ManagedPath(path="file.py", strategy="enforce")]
        lock.ignore_paths = ["file.py"]

        errors = lockfile_manager.validate(lock)
        # Should not have errors - ignore paths take precedence
        assert len(errors) == 0
