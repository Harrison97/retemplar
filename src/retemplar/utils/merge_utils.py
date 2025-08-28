# src/retemplar/utils/merge_utils.py
"""
Clean, minimal merge utilities for retemplar.
Implements "theirs as structural base" merge with ignore block support.
"""

import difflib
import shutil
from pathlib import Path
from typing import Optional, List

from retemplar.schema import RenderRule
from retemplar.utils.fs_utils import (
    apply_render_rules_text,
    read_text,
    write_text,
)

from .blockprotect import (
    enforce_ours_blocks,
    find_ignore_blocks,
)


def copy_with_render_and_blockprotect(
    src: Path,
    dst: Path,
    rules: Optional[List[RenderRule]],
    repo_root: Path,
) -> None:
    """Copy text/binary; apply render rules; then enforce consumer block protection."""
    try:
        tpl = src.read_text(encoding="utf-8")
        tpl = apply_render_rules_text(tpl, rules)
        if dst.exists():
            ours = read_text(dst)
            if ours is not None:
                tpl, report = enforce_ours_blocks(ours, tpl)
        write_text(dst, tpl)
        shutil.copystat(src, dst, follow_symlinks=False)
    except UnicodeDecodeError:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def merge_with_conflicts(ours: str, theirs: str) -> str:
    """
    Simple merge with ignore block support:
    - Template content wins by default (theirs as structural base)
    - Ignore blocks from ours are auto-accepted
    - Other ours additions create conflicts
    """
    ours_lines = ours.splitlines(keepends=True)
    theirs_lines = theirs.splitlines(keepends=True)
    ours_blocks = find_ignore_blocks(ours)

    if not ours_blocks:
        result_lines = _merge_simple(ours_lines, theirs_lines)
    else:
        result_lines = _merge_with_blocks(ours_lines, theirs_lines, ours_blocks)

    result = "".join(result_lines)
    return _normalize_trailing_newline(result, theirs)


def _normalize_trailing_newline(result: str, template: str) -> str:
    """Follow template's trailing newline behavior."""
    if not template:
        return result

    if template.endswith("\n"):
        return result if result.endswith("\n") else result + "\n"
    else:
        return result.rstrip("\n")


def _merge_simple(ours_lines: list[str], theirs_lines: list[str]) -> list[str]:
    """Simple text merge with 'theirs as base' strategy."""
    result = []
    sm = difflib.SequenceMatcher(None, ours_lines, theirs_lines)

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            result.extend(ours_lines[i1:i2])
        elif tag == "insert":
            result.extend(theirs_lines[j1:j2])
        elif tag in ("delete", "replace"):
            ours_chunk = ours_lines[i1:i2]
            theirs_chunk = theirs_lines[j1:j2] if tag == "replace" else []

            # Edge case: ignore trivial trailing newline differences
            if _is_trivial_trailing_newline_diff(
                ours_chunk,
                theirs_chunk,
                i2,
                j2,
                ours_lines,
                theirs_lines,
            ):
                result.extend(theirs_chunk)
            elif _is_only_trailing_newline_addition(ours_chunk, i2, ours_lines):
                pass  # Skip ours addition of just trailing newline
            else:
                # Real conflict
                result.extend(_create_conflict(ours_chunk, theirs_chunk))

    return result


def _merge_with_blocks(
    ours_lines: list[str],
    theirs_lines: list[str],
    blocks: dict,
) -> list[str]:
    """Merge with ignore block awareness."""
    result = []
    sm = difflib.SequenceMatcher(None, ours_lines, theirs_lines)

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            result.extend(ours_lines[i1:i2])
        else:
            ours_chunk = ours_lines[i1:i2]
            theirs_chunk = theirs_lines[j1:j2]
            overlapping = _find_overlapping_blocks(i1, i2, blocks)

            if not overlapping:
                result.extend(_merge_simple(ours_chunk, theirs_chunk))
            else:
                result.extend(
                    _split_around_blocks(
                        i1,
                        ours_chunk,
                        theirs_chunk,
                        overlapping,
                    ),
                )

    return result


def _find_overlapping_blocks(start: int, end: int, blocks: dict) -> list:
    """Find blocks overlapping with line range [start, end)."""
    return [
        (bid, span)
        for bid, span in blocks.items()
        if span.start < end and span.end >= start
    ]


def _split_around_blocks(
    start_line: int,
    ours_chunk: list[str],
    theirs_chunk: list[str],
    overlapping: list,
) -> list[str]:
    """Split chunk around ignore blocks, auto-accepting blocks."""
    result = []
    pos = start_line

    for block_id, span in sorted(overlapping, key=lambda x: x[1].start):
        # Handle content before block
        if pos < span.start:
            pre_ours = ours_chunk[pos - start_line : span.start - start_line]
            pre_theirs = (
                theirs_chunk[pos - start_line : span.start - start_line]
                if len(theirs_chunk) > (pos - start_line)
                else []
            )
            if pre_ours or pre_theirs:
                result.extend(_merge_simple(pre_ours, pre_theirs))

        # Auto-accept ignore block (with proper separation)
        block_start = max(0, span.start - start_line)
        block_end = min(len(ours_chunk), span.end + 1 - start_line)
        block_lines = ours_chunk[block_start:block_end]

        if block_lines:
            # Ensure newline separation before ignore blocks
            if result and result[-1] and not result[-1].endswith("\n"):
                result[-1] += "\n"
            result.extend(block_lines)

        pos = span.end + 1

    # Handle remaining content after last block
    if pos < start_line + len(ours_chunk):
        post_ours = ours_chunk[pos - start_line :]
        post_theirs = (
            theirs_chunk[pos - start_line :]
            if len(theirs_chunk) > (pos - start_line)
            else []
        )
        if post_ours or post_theirs:
            result.extend(_merge_simple(post_ours, post_theirs))

    return result


def _create_conflict(
    ours_chunk: list[str],
    theirs_chunk: list[str],
) -> list[str]:
    """Create conflict markers with proper newline handling."""
    conflict = ["<<<<<<< LOCAL\n"]
    conflict.extend(ours_chunk)

    # Ensure newline before separator
    if conflict and not conflict[-1].endswith("\n"):
        conflict[-1] += "\n"

    conflict.append("=======\n")
    conflict.extend(theirs_chunk)

    # Ensure newline before end marker
    if conflict and not conflict[-1].endswith("\n"):
        conflict[-1] += "\n"

    conflict.append(">>>>>>> TEMPLATE\n")
    return conflict


def _is_trivial_trailing_newline_diff(
    ours_chunk: list[str],
    theirs_chunk: list[str],
    i2: int,
    j2: int,
    ours_lines: list[str],
    theirs_lines: list[str],
) -> bool:
    """Check if difference is just trailing newline variation."""
    return (
        len(ours_chunk) == 1
        and len(theirs_chunk) == 1
        and ours_chunk[0].rstrip("\n") == theirs_chunk[0].rstrip("\n")
        and i2 == len(ours_lines)
        and j2 == len(theirs_lines)
    )


def _is_only_trailing_newline_addition(
    ours_chunk: list[str],
    i2: int,
    ours_lines: list[str],
) -> bool:
    """Check if ours only adds a trailing newline."""
    return len(ours_chunk) == 1 and ours_chunk[0] == "\n" and i2 == len(ours_lines)
