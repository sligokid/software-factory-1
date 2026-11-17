"""Path glob matching with `**` support, independent of the current directory."""

import re
from functools import lru_cache


@lru_cache(maxsize=256)
def _compile(pattern: str) -> re.Pattern[str]:
    out = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def matches(path: str, pattern: str) -> bool:
    """True if a repo-relative POSIX path matches the pattern.

    A pattern without a slash also matches the file name in any directory (like .gitignore),
    so `*.lock` matches `web/pnpm.lock`.
    """
    if _compile(pattern).match(path):
        return True
    return "/" not in pattern and bool(_compile(pattern).match(path.rsplit("/", 1)[-1]))


def matches_any(path: str, patterns: list[str]) -> bool:
    return any(matches(path, p) for p in patterns)
