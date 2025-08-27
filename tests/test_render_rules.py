"""Essential tests for render rules functionality."""

import tempfile
from pathlib import Path

from retemplar.core import RetemplarCore


def test_render_rules_basic():
    """Test basic literal text replacement."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        template_dir = tmpdir / "template"
        template_dir.mkdir()
        (template_dir / "README.md").write_text(
            "# MyTemplate Project\nWelcome to MyTemplate!",
        )

        repo_dir = tmpdir / "repo"
        repo_dir.mkdir()

        core = RetemplarCore(repo_dir)

        render_rules = [
            {
                "pattern": "MyTemplate",
                "replacement": "MyProject",
                "literal": True,
            },
        ]

        core.adopt_template(
            template_ref=f"rat:{template_dir}",
            managed_paths=["README.md"],
            render_rules=render_rules,
        )

        core.apply_changes(f"rat:{template_dir}")

        content = (repo_dir / "README.md").read_text()
        assert "MyProject Project" in content
        assert "Welcome to MyProject!" in content
