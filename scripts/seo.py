#!/usr/bin/env python3
"""Make the static site crawlable and keep its framed pages in their frames.

Run it on the generated `site/` (idempotent; the generators and publish.sh call it):

* writes `sitemap.xml` (a sitemap index plus `sitemap-N.xml` files above 45,000 URLs) and
  `robots.txt` (allow everything, with the `Sitemap:` line), from `site.json`'s hostname;
* when `scripts/frame-restore.js` exists, copies it to `site/frame-restore.js` and adds one
  `<script src="/frame-restore.js">` tag to every HTML page, so that a framed page opened on
  its own is reloaded inside its original frames (the page itself is still served as is, so
  crawlers keep seeing its content).

Usage: python3 -I scripts/seo.py [--site DIR]
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape

REPO = Path(__file__).resolve().parent.parent
HTML_EXT = {".htm", ".html", ".shtml"}
MAX_URLS = 45000  # sitemap protocol limit is 50,000 per file
NOINDEX = re.compile(rb"<meta[^>]+name\s*=\s*[\"']?robots[\"']?[^>]*noindex", re.I)
NOINDEX_REV = re.compile(rb"<meta[^>]+noindex[^>]*name\s*=\s*[\"']?robots", re.I)
REFRESH = re.compile(rb"<meta[^>]+http-equiv\s*=\s*[\"']?refresh", re.I)
HEAD = re.compile(rb"<head[^>]*>", re.I)
HTML_TAG = re.compile(rb"<html[^>]*>", re.I)
DOCTYPE = re.compile(rb"<!doctype[^>]*>\s*", re.I)
TAG = b'<script src="/frame-restore.js"></script>'
NOT_FOUND_NAMES = {"404.htm", "404.html"}
# Alternative skins (/skin/<name>/...) duplicate the pages of the default one: not listed in the sitemap.
SKIP_PREFIXES = ("skin/",)


def html_files(site):
    for p in sorted(site.rglob("*")):
        if p.is_file() and p.suffix.lower() in HTML_EXT:
            yield p


def inject(path):
    """Add the frame-restore script tag as early as possible; True if the file changed."""
    raw = path.read_bytes()
    if b"/frame-restore.js" in raw:
        return False
    m = HEAD.search(raw) or HTML_TAG.search(raw)
    if m:
        pos = m.end()
    else:
        d = DOCTYPE.match(raw)
        pos = d.end() if d else 0
    path.write_bytes(raw[:pos] + TAG + raw[pos:])
    return True


def indexable(path):
    head = path.read_bytes()[:8192]
    return not (NOINDEX.search(head) or NOINDEX_REV.search(head) or REFRESH.search(head))


def write_sitemaps(site, host):
    urls = []
    for p in html_files(site):
        rel = p.relative_to(site).as_posix()
        if rel.lower() in NOT_FOUND_NAMES or rel.startswith(SKIP_PREFIXES) or not indexable(p):
            continue
        urls.append("/" if rel.lower() in ("index.html", "index.htm") else "/" + quote(rel))
    for old in site.glob("sitemap*.xml"):
        old.unlink()
    head = '<?xml version="1.0" encoding="UTF-8"?>\n'
    ns = 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'
    chunks = [urls[i:i + MAX_URLS] for i in range(0, len(urls), MAX_URLS)] or [[]]

    def urlset(chunk):
        body = "".join("  <url><loc>%s</loc></url>\n" % escape("https://%s%s" % (host, u)) for u in chunk)
        return "%s<urlset %s>\n%s</urlset>\n" % (head, ns, body)

    if len(chunks) == 1:
        (site / "sitemap.xml").write_text(urlset(chunks[0]), encoding="utf-8")
    else:
        index = ""
        for n, chunk in enumerate(chunks, 1):
            name = "sitemap-%d.xml" % n
            (site / name).write_text(urlset(chunk), encoding="utf-8")
            index += "  <sitemap><loc>https://%s/%s</loc></sitemap>\n" % (host, name)
        (site / "sitemap.xml").write_text("%s<sitemapindex %s>\n%s</sitemapindex>\n" % (head, ns, index),
                                          encoding="utf-8")
    return len(urls)


def write_robots(site, host):
    # Allow everything; never block. Keep the file simple and regenerate it every time.
    (site / "robots.txt").write_text(
        "User-agent: *\nAllow: /\n\nSitemap: https://%s/sitemap.xml\n" % host, encoding="ascii")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--site", type=Path, default=REPO / "site")
    args = ap.parse_args(argv)
    site = args.site.resolve()
    if not site.is_dir():
        sys.exit("no site directory: %s" % site)
    host = json.loads((REPO / "site.json").read_text(encoding="utf-8"))["hostname"]

    restore = REPO / "scripts" / "frame-restore.js"
    injected = 0
    if restore.is_file():
        shutil.copyfile(restore, site / "frame-restore.js")
        for p in html_files(site):
            if p.name.lower() not in NOT_FOUND_NAMES and inject(p):
                injected += 1
    n = write_sitemaps(site, host)
    write_robots(site, host)
    print("seo: %d URLs in sitemap, frame-restore tag added to %d page(s)" % (n, injected))


if __name__ == "__main__":
    main()
