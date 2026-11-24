#!/usr/bin/env bash
# Build site/ from the raw store, add robots.txt and sitemap.xml, run the checks.
# It does not deploy anything: merging to main deploys through GitHub Actions.
set -euo pipefail
cd "$(dirname "$0")"
python3 -I scripts/build.py "$@"
python3 -I scripts/seo.py
python3 -I scripts/verify_build.py
python3 -I scripts/check_excludes.py
