#!/usr/bin/env python3
"""Check that the public site serves the files of site/ over HTTPS.

Fetches the root URL and every page of site/ (*.htm, *.html, *.shtml) and
compares each body with the repository copy. Retries for a while, since a
deployment or purge takes some time to reach every CDN edge. No secret needed.
"""

from __future__ import annotations

import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import bunny

ATTEMPTS = 6
DELAY = 20  # seconds between attempts
PAGES = ("*.htm", "*.html", "*.shtml")
INDEX = ("index.html", "index.htm")


def fetch(url: str) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": "smoke-test", "Cache-Control": "no-cache"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except OSError as e:
        return 0, str(e).encode()


def check(base: str) -> list[str]:
    errors = []
    pages = sorted({p for pat in PAGES for p in bunny.SITE_DIR.rglob(pat)})
    index = next((bunny.SITE_DIR / i for i in INDEX if (bunny.SITE_DIR / i).is_file()), None)
    targets = [("/", index)] + [("/" + p.relative_to(bunny.SITE_DIR).as_posix(), p) for p in pages]
    for path, local in targets:
        status, body = fetch(base + urllib.parse.quote(path))
        if status != 200:
            errors.append(f"{path}: HTTP {status}")
        elif local is not None and body != local.read_bytes():
            errors.append(f"{path}: content differs from site/{local.relative_to(bunny.SITE_DIR)}")
    return errors


def main() -> int:
    base = "https://" + bunny.site_config()["hostname"]
    for attempt in range(1, ATTEMPTS + 1):
        errors = check(base)
        if not errors:
            print(f"{base}: every page served as in site/.")
            return 0
        print(f"Attempt {attempt}/{ATTEMPTS}: {len(errors)} problem(s).", flush=True)
        if attempt < ATTEMPTS:
            time.sleep(DELAY)
    print("\n".join(errors))
    return 1


if __name__ == "__main__":
    sys.exit(main())
