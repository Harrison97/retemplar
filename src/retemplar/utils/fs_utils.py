# src/retemplar/utils/fs_utils.py
"""
File system utilities for retemplar.
"""

import re
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Optional, List, Tuple
from ..schema import RenderRule


# =============================================================================
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
