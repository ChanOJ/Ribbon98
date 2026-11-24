#!/usr/bin/env python3
"""Synchronise site/ to the bunny.net storage zone of site.json, then purge the CDN.

- Uploads only new or changed files (SHA-256 comparison).
- Deletes remote files that are not in site/ (guarded against mass deletion).
- Purges the pull zone cache when something changed.

Environment: BUNNY_API_KEY (account API key; the storage zone password and the
pull zone id are looked up from it). DEPLOY_ENV optional label for the summary.

Usage:
  pass-cli run --env-file infra/secrets.env -- python3 scripts/deploy.py --dry-run
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import bunny

# Local files never uploaded.
SKIP = [".DS_Store", "*/.DS_Store"]

# Refuse to delete more than this share of the remote files (and at least
# MIN_DELETE_GUARD files) without --allow-mass-delete.
MAX_DELETE_RATIO = 0.25
MIN_DELETE_GUARD = 10


def local_files() -> dict[str, bytes]:
    files = {}
    for p in sorted(bunny.SITE_DIR.rglob("*")):
        rel = p.relative_to(bunny.SITE_DIR).as_posix()
        if p.is_file() and not any(fnmatch.fnmatchcase(rel, s) for s in SKIP):
            files[rel] = p.read_bytes()
    return files


def summary(lines: list[str]) -> None:
    text = "\n".join(lines)
    print(text, flush=True)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="show the plan, change nothing")
    ap.add_argument("--allow-mass-delete", action="store_true",
                    help="disable the guard on the number of deletions")
    ap.add_argument("--force-purge", action="store_true", help="purge even without changes")
    args = ap.parse_args()

    cfg = bunny.site_config()
    local = local_files()
    if not local:
        sys.exit("site/ is empty: aborting.")
    sums = {rel: hashlib.sha256(data).hexdigest().upper() for rel, data in local.items()}

    if bunny.find_storage_zone(cfg["storage_zone"]) is None:
        # A new site: the zones are created by the first apply of the infra workflow, which
        # then deploys site/ itself. Not an error (the merge of the import PR lands here).
        print(f"::notice::Storage zone {cfg['storage_zone']!r} does not exist yet: nothing deployed. "
              "Run the 'Infra: bunny.net' workflow with action 'apply'.")
        out = os.environ.get("GITHUB_OUTPUT")
        if out:
            with open(out, "a", encoding="utf-8") as f:
                f.write("skipped=true\n")
        return 0

    storage = bunny.Storage(cfg["storage_zone"])
    remote, remote_dirs = storage.list_recursive()
    uploads = sorted(rel for rel in local if remote.get(rel) != sums[rel])
    orphans = sorted(rel for rel in remote if rel not in local)
    orphan_dirs = sorted(d for d in remote_dirs if not any(r.startswith(d + "/") for r in local))
    orphan_dirs = [d for d in orphan_dirs if not any(d.startswith(o + "/") for o in orphan_dirs)]
    loose = [f for f in orphans if not any(f.startswith(d + "/") for d in orphan_dirs)]

    guard = max(MIN_DELETE_GUARD, int(len(remote) * MAX_DELETE_RATIO))
    if len(orphans) > guard and not args.allow_mass_delete:
        summary([f"**Aborted**: {len(orphans)} deletions planned (> {guard}).",
                 *[f"- `{o}`" for o in orphans],
                 "Run again with --allow-mass-delete if this is intended."])
        return 2

    label = os.environ.get("DEPLOY_ENV")
    title = ("bunny.net deployment of " + cfg["hostname"] + (f" ({label})" if label else "")
             + (" (dry run)" if args.dry_run else ""))
    lines = [f"## {title}", "",
             f"- {len(local)} local files, {len(remote)} remote files",
             f"- Files to upload: **{len(uploads)}**",
             f"- Files to delete: **{len(orphans)}**", ""]
    lines += [f"- ⬆️ `{u}`" + ("" if u in remote else " (new)") for u in uploads]
    lines += [f"- 🗑️ `{d}/` (folder)" for d in orphan_dirs]
    lines += [f"- 🗑️ `{o}`" for o in loose]
    summary(lines)
    if args.dry_run:
        return 0

    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda r: storage.upload(r, local[r], sums[r]), uploads))
        list(pool.map(storage.delete, loose))
    for d in orphan_dirs:
        storage.delete(d + "/")
    print("Storage zone up to date.")

    if uploads or orphans or args.force_purge:
        bunny.purge_pullzone(bunny.pullzone(cfg["pullzone"])["Id"])
        print("Pull zone cache purged.")
    else:
        print("No change: no purge.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
