"""
Core retemplar operations (MVP).

Surgical refactor: simplified, readable, ready for 3-way merge + baseline.
"""

import difflib
import re
import shutil
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath
from typing import Dict, Any, Iterable, Optional, List, Tuple

from .blockprotect import enforce_ours_blocks, find_ignore_blocks

try:
    from .schema import RenderRule
except ImportError:
    RenderRule = Dict[str, Any]  # type: ignore# =============================================================================
# Pure helpers (top of file)
# =============================================================================


def posix(p: Path | str) -> str:
    """Normalize path to POSIX string."""
    return PurePosixPath(str(p)).as_posix()


def match(path: str, pattern: str) -> bool:
    """Glob match with basic '**' support."""
    path = posix(path)
    pattern = posix(pattern)
    if pattern.endswith("/**"):
        return path == pattern[:-3] or path.startswith(pattern[:-3] + "/")
    return fnmatch(path, pattern)


def best_rule(path: str, managed_rules: Iterable[Any]) -> Optional[Any]:
    """Pick most specific managed rule for a path (exact > /** > *)."""
    matches = [r for r in managed_rules if match(path, r.path)]
    if not matches:
        return None

    def key(r: Any) -> Tuple[int, int]:
        p = posix(r.path)
        if p == posix(path):
            return (0, -len(p))  # exact match, highest
        if p.endswith("/**"):
            return (1, -len(p))  # dir glob
        if "*" in p:
            return (2, -len(p))  # wildcard
        return (3, -len(p))  # other (rare)

    return sorted(matches, key=key)[0]


def list_files(root: Path) -> List[str]:
    """All file paths under root (relative, POSIX)."""
    if not root.exists():
        return []

    files = []
    for path in root.rglob("*"):
        if path.is_file():
            rel_path = path.relative_to(root)
            files.append(posix(rel_path))
    return files


def read_text(path: Path) -> Optional[str]:
    """Return file contents as text, or None if binary."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None


def write_text(path: Path, text: str) -> None:
    """Write text to path, creating directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def delete_file(path: Path) -> None:
    if path.exists():
        path.unlink()
        # best-effort prune
        try:
            path.parent.rmdir()
        except OSError:
            pass


def is_ignored(rel: str, ignore_patterns: List[str]) -> bool:
    return any(match(rel, pat) for pat in ignore_patterns)


def apply_render_rules_text(s: str, rules: Optional[List[RenderRule]]) -> str:
    """Apply render rules to text content."""
    if not rules:
        return s
    out = s
    for r in rules:
        # Support dict or object
        pattern = r.get("pattern") if isinstance(r, dict) else r.pattern
        replacement = r.get("replacement") if isinstance(r, dict) else r.replacement
        literal = (
            r.get("literal", False)
            if isinstance(r, dict)
            else getattr(r, "literal", False)
        )
        if literal:
            out = out.replace(pattern, replacement)
        else:
            try:
                out = re.sub(pattern, replacement, out)
            except re.error as e:
                raise ValueError(
                    f"Invalid regex pattern '{pattern}': {e}",
                ) from e
    return out


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
                # optional: print or log report.enforced / report.warnings
        write_text(dst, tpl)
        shutil.copystat(src, dst, follow_symlinks=False)
    except UnicodeDecodeError:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def merge_with_conflicts(ours: str, theirs: str) -> str:
    """
    Merge ours vs theirs, but carve out ignore blocks:
      - Outside blocks → normal diff/merge with conflict markers
      - Inside blocks  → always keep ours verbatim
    """
    ours_lines = ours.splitlines(keepends=True)
    theirs_lines = theirs.splitlines(keepends=True)

    # Find ignore block spans (start/end indices inclusive)
    spans = list(find_ignore_blocks(ours).values())
    spans.sort(key=lambda s: s.start)

    result: list[str] = []
    ours_idx = 0
    theirs_idx = 0

    def emit_diff(ours_chunk, theirs_chunk):
        sm = difflib.SequenceMatcher(None, ours_chunk, theirs_chunk)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                result.extend(ours_chunk[i1:i2])
            else:
                result.append("<<<<<<< LOCAL\n")
                result.extend(ours_chunk[i1:i2])
                if not ours_chunk[i1:i2] or not ours_chunk[i1:i2][-1].endswith(
                    "\n",
                ):
                    result.append("\n")
                result.append("=======\n")
                result.extend(theirs_chunk[j1:j2])
                if not theirs_chunk[j1:j2] or not theirs_chunk[j1:j2][-1].endswith(
                    "\n"
                ):
                    result.append("\n")
                result.append(">>>>>>> TEMPLATE\n")
                if not result[-1].endswith("\n"):
                    result.append("\n")

    for span in spans:
        # diff before block
        ours_chunk = ours_lines[ours_idx : span.start]
        theirs_chunk = theirs_lines[theirs_idx : theirs_idx + len(ours_chunk)]
        emit_diff(ours_chunk, theirs_chunk)

        # add a newline if last line didn't end cleanly
        if result and not result[-1].endswith("\n"):
            result.append("\n")

        # add the ignore block verbatim
        block_lines = ours_lines[span.start : span.end + 1]
        if (
            block_lines
            and not block_lines[0].startswith("\n")
            and result
            and result[-1] != "\n"
        ):
            result.append("\n")
        result.extend(block_lines)
        if not block_lines[-1].endswith("\n"):
            result.append("\n")

        ours_idx = span.end + 1
        theirs_idx += len(ours_chunk)

    # diff after last block
    ours_chunk = ours_lines[ours_idx:]
    theirs_chunk = theirs_lines[theirs_idx : theirs_idx + len(ours_chunk)]
    emit_diff(ours_chunk, theirs_chunk)

    return "".join(result)


# =============================================================================
# Template loading
# =============================================================================


def resolve_template_path(template_repo: str) -> Path:
    """
    Local folder only:
      - "./template-dir", "/abs/path", ".<something>/..."
    GH refs still TODO (raise).
    """
    p = Path(template_repo)
    if p.exists() and p.is_dir():
        return p.resolve()
    s = str(template_repo)
    if s.startswith("gh:"):
        raise NotImplementedError("GitHub repos not supported yet in MVP")
    raise ValueError(f"Unsupported repo format: {template_repo}")
