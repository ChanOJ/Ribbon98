#!/usr/bin/env python3
"""Fail if site/ or hosting/ contains a path matching scripts/exclude-globs.txt
(and docs/exclude-globs.txt when present).

Last line of defence before publication: the globs list what must never be
served (credentials, visitor logs, server-side code). Stdlib only.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GLOBS = [ROOT / "scripts" / "exclude-globs.txt", ROOT / "docs" / "exclude-globs.txt"]


def to_regex(glob: str) -> re.Pattern:
    out, i = "", 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif glob.startswith("**", i):
            out += ".*"
            i += 2
        elif glob[i] == "*":
            out += ".*"  # as in exclude-globs.txt: '*' crosses '/'
            i += 1
        elif glob[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(glob[i])
            i += 1
    return re.compile(out + r"\Z", re.IGNORECASE)


def main() -> int:
    patterns = []
    for f in GLOBS:
        if not f.is_file():
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                patterns.append((line, to_regex(line)))
    # A glob without "/" matches at any depth (like .gitignore).
    patterns = [(g, r if "/" in g else to_regex("**/" + g)) for g, r in patterns]
    bad = []
    for top in ("site", "hosting"):
        for p in sorted((ROOT / top).rglob("*")):
            if p.is_file():
                rel = p.relative_to(ROOT / top).as_posix()
                hit = next((g for g, r in patterns if r.match(rel)), None)
                if hit:
                    bad.append(f"{top}/{rel}  (matches {hit})")
    if bad:
        print("Excluded files found:\n" + "\n".join(bad))
        return 1
    print(f"No excluded file in site/ or hosting/ ({len(patterns)} globs).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
