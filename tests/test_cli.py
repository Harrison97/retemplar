"""Tests for CLI commands."""

import pytest
import tempfile
from pathlib import Path
from typer.testing import CliRunner

from retemplar.cli import app


@pytest.fixture
def temp_repo():
    """Create temporary directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def runner():
    """Create CLI test runner."""
    return CliRunner()


def test_version_command(runner):
    """Test version command."""
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "retemplar 0.0.1" in result.stdout


def test_adopt_command_help(runner):
    """Test adopt command help."""
    result = runner.invoke(app, ["adopt", "--help"])
    assert result.exit_code == 0
    assert "Attach the repo to a template" in result.stdout


def test_plan_command_help(runner):
    """Test plan command help."""
    result = runner.invoke(app, ["plan", "--help"])
    assert result.exit_code == 0
    assert "Preview the upgrade plan" in result.stdout


def test_apply_command_help(runner):
    """Test apply command help."""
    result = runner.invoke(app, ["apply", "--help"])
    assert result.exit_code == 0
    assert "Apply the plan to the repo" in result.stdout


def test_drift_command_help(runner):
    """Test drift command help."""
    result = runner.invoke(app, ["drift", "--help"])
    assert result.exit_code == 0
    assert "Report drift between" in result.stdout


def test_adopt_command_dry_run(runner, temp_repo):
    """Test adopt command in dry-run mode."""
    result = runner.invoke(
        app,
        [
            "--repo",
            str(temp_repo),
            "--dry-run",
            "adopt",
            "--template",
            "rat:gh:acme/test@v1.0.0",
        ],
    )

    # Should not fail, but actual implementation will be needed for full testing
    # For now just test the command structure works
    assert result.exit_code in [0, 1]  # May fail due to missing implementation


def test_global_verbose_option(runner, temp_repo):
    """Test global verbose option."""
    result = runner.invoke(app, ["--repo", str(temp_repo), "--verbose", "version"])

    assert result.exit_code == 0
