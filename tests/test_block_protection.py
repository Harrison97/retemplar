"""Essential tests for block protection functionality."""

from retemplar.utils.blockprotect import (
    find_ignore_blocks,
    enforce_ours_blocks,
)


def test_find_ignore_blocks_basic():
    """Test basic ignore block detection."""
    content = """
# retemplar:begin id=config mode=ignore
config_value: local_setting
# retemplar:end id=config
""".strip()

    blocks = find_ignore_blocks(content)
    assert len(blocks) == 1
    assert "config" in blocks


def test_enforce_ours_blocks_basic():
    """Test basic block protection."""
    ours = """
# retemplar:begin id=preserve mode=ignore
local: data
# retemplar:end id=preserve
other: content
""".strip()

    merged = """
# retemplar:begin id=preserve mode=ignore
template: data
# retemplar:end id=preserve
other: new_content
""".strip()

    result, report = enforce_ours_blocks(ours, merged)

    # Should preserve the local data in the ignore block
    assert "local: data" in result
    # Should accept template changes outside the block
    assert "new_content" in result
    assert len(report.enforced) == 1
