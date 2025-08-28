# src/retemplar/blockprotect.py
"""
Consumer-side block protection for retemplar.

Preserves sections in the consumer repo marked as "ignore" during template upgrades.

Markers (line-oriented):
  # retemplar:begin id=<ID> mode=ignore
  ...
  # retemplar:end id=<ID>

Notes:
- We preserve existing newline style by using splitlines(keepends=True).
- IDs may contain [A-Za-z0-9_.-]
- Comment leader is flexible: '#', '//', ';', '--' (optional).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Tuple


@dataclass
class BlockSpan:
    start: int  # inclusive (0-based line index of the BEGIN marker)
    end: int  # inclusive (0-based line index of the END marker)


@dataclass
class BlockEvent:
    id: str
    start: int  # 1-based line index for human display
    end: int  # 1-based line index for human display


@dataclass
class BlockReport:
    enforced: List[BlockEvent]
    warnings: List[str]


# Accept common comment leaders before the marker (optional)
# Examples matched:
#   "# retemplar:begin id=x mode=ignore"
#   "// retemplar:begin id=x mode=ignore"
#   "; retemplar:end id=x"
COMMENT_LEADER = r"(?:#|//|;|--)?"

BEGIN_PATTERN = re.compile(
    rf"^\s*{COMMENT_LEADER}\s*retemplar:begin\s+id=([A-Za-z0-9_.-]+)\s+mode=(?:ignore|ours)\s*$",
)
END_PATTERN = re.compile(
    rf"^\s*{COMMENT_LEADER}\s*retemplar:end\s+id=([A-Za-z0-9_.-]+)\s*$",
)


def find_ignore_blocks(text: str) -> Dict[str, BlockSpan]:
    """
    Parse ignore blocks:
      retemplar:begin id=<id> mode=ignore
      ...
      retemplar:end id=<id>
    Returns: {id: BlockSpan(start_line_idx, end_line_idx)} using 0-based indices.
    """
    lines = text.splitlines(keepends=True)
    blocks: Dict[str, BlockSpan] = {}
    open_blocks: Dict[str, int] = {}  # id -> start_line_idx

    for line_idx, line in enumerate(lines):
        m = BEGIN_PATTERN.match(line)
        if m:
            block_id = m.group(1)
            # If already open, we’ll warn later in _validate_blocks
            if block_id not in open_blocks:
                open_blocks[block_id] = line_idx
            continue

        m = END_PATTERN.match(line)
        if m:
            block_id = m.group(1)
            start_line = open_blocks.pop(block_id, None)
            if start_line is not None:
                blocks[block_id] = BlockSpan(start=start_line, end=line_idx)
            # If there was no matching begin, we warn in _validate_blocks

    return blocks


def enforce_ours_blocks(
    ours_text: str,
    merged_text: str,
) -> Tuple[str, BlockReport]:
    """
    Preserve consumer (Ours) ignore blocks in the merged result:
      - If Merged contains a matching block id, replace the inner content (between markers) with Ours’s inner content.
      - If Merged lacks that id, warn and skip (MVP).
      - If Merged has a block id that Ours lacks, warn (MVP), do nothing.

    Returns: (new_text, BlockReport)
    """
    ours_blocks = find_ignore_blocks(ours_text)
    merged_blocks = find_ignore_blocks(merged_text)

    ours_lines = ours_text.splitlines(keepends=True)
    merged_lines = merged_text.splitlines(keepends=True)

    enforced: List[BlockEvent] = []
    warnings: List[str] = []

    # Syntax/structure checks
    _validate_blocks(ours_text, "consumer repo", warnings)
    _validate_blocks(merged_text, "merged result", warnings)

    # Warn for ids present in merged but missing in ours (consumer hasn't adopted markers yet)
    for bid in merged_blocks.keys():
        if bid not in ours_blocks:
            warnings.append(
                f"Block id '{bid}' exists in merged result but not in consumer repo; left unchanged",
            )

    # Prepare replacements (work from bottom to top to avoid index shifting)
    replacements: List[Tuple[str, BlockSpan, BlockSpan]] = []
    for block_id, ours_span in ours_blocks.items():
        if block_id in merged_blocks:
            replacements.append((block_id, ours_span, merged_blocks[block_id]))
        else:
            warnings.append(
                f"Block id '{block_id}' exists in consumer repo but not in merged result; skipped",
            )

    replacements.sort(key=lambda t: t[2].start, reverse=True)

    result_lines = merged_lines[:]  # copy
    for block_id, ours_span, merged_span in replacements:
        # Inner content (exclude the marker lines themselves)
        ours_inner = ours_lines[ours_span.start + 1 : ours_span.end]
        # Replace merged inner content
        del result_lines[merged_span.start + 1 : merged_span.end]
        for i, line in enumerate(ours_inner):
            result_lines.insert(merged_span.start + 1 + i, line)

        enforced.append(
            BlockEvent(
                id=block_id,
                start=ours_span.start + 1,
                end=ours_span.end + 1,
            ),
        )

    return "".join(result_lines), BlockReport(
        enforced=enforced,
        warnings=warnings,
    )


def _validate_blocks(text: str, source_name: str, warnings: List[str]) -> None:
    """Validate well-formedness: duplicates, unclosed, stray ends."""
    lines = text.splitlines(keepends=True)
    open_blocks: Dict[str, int] = {}

    for line_idx, line in enumerate(lines):
        m = BEGIN_PATTERN.match(line)
        if m:
            block_id = m.group(1)
            if block_id in open_blocks:
                warnings.append(
                    f"Duplicate begin marker for id '{block_id}' at line {line_idx + 1} in {source_name}",
                )
            else:
                open_blocks[block_id] = line_idx

        m = END_PATTERN.match(line)
        if m:
            block_id = m.group(1)
            if block_id not in open_blocks:
                warnings.append(
                    f"End marker for id '{block_id}' at line {line_idx + 1} has no matching begin marker in {source_name}",
                )
            else:
                open_blocks.pop(block_id, None)

    for block_id, start_line in open_blocks.items():
        warnings.append(
            f"Unclosed block with id '{block_id}' starting at line {start_line + 1} in {source_name}",
        )
