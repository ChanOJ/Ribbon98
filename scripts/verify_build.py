#!/usr/bin/env python3
"""Check the generated site/ (stdlib only, read-only). Exit 1 on any failure.

    python3 -I scripts/verify_build.py [--build site]

Checks: key pages exist, no engine files, no leftover Teleport Pro / FrontPage server artefacts
(`tppabs`, `tppmsgs`, `<form`, `<%`), no e-mail address or mailto: except the removal-request
footer, no IPv4 outside a URL host, no phone number, no age/postcode of members, no visitor host in
the statistics, charset declared, every internal link and image resolves (case-sensitive).
"""
import argparse
import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote

ENC = "iso-8859-1"
REPO = Path(__file__).resolve().parent.parent
LINK = re.compile(r"""(?ix)\b(?:href|src|background)\s*=\s*(?:(["'])(.*?)\1|([^\s"'>]+))""")
REMOVAL = re.compile(r'(?s)<div id="removal-note".*?</div>')
# nick addresses are published on purpose (2026-11-24 decision); any other address is a leak
NICK_LOCALS = ("drribbon", "poi_ribbon", "ribbon", "geek", "frigo", "lluvia", "kenetribbon", "selfmail", "dreynald")
EMAIL = re.compile(r"(?<![A-Za-z0-9._+-])(?!(?:%s)@)[A-Za-z0-9._+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+" % "|".join(NICK_LOCALS), re.I)
IPV4 = re.compile(r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\d.])")
PHONE = re.compile(r"\b0\d(?:[. ]\d\d){4}\b")
AGE = re.compile(r"(?i)\b\d{1,3}\s*ans\s*-\s*\d{5}")
LEFTOVERS = [
    ("tppabs/tppmsgs", re.compile(r"(?i)tppabs|tppmsgs")),
    ("form tag", re.compile(r"(?i)<form\b")),
    ("password input", re.compile(r"(?i)<input[^>]*type\s*=\s*\"?password[^>]*value")),
    ("asp tag", re.compile(r"<%")),
    ("mailto", re.compile(r"(?i)(?<![a-z])mailto:")),
    ("e-mail address", EMAIL),
    ("phone number", PHONE),
    ("age + postcode", AGE),
]


def rd(p):
    return Path(p).read_bytes().decode(ENC)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--build", default=str(REPO / "site"))
    a = ap.parse_args(argv)
    build = Path(a.build)
    files = sorted(Path(r, f).relative_to(build).as_posix() for r, _, fs in os.walk(build) for f in fs)
    fset = set(files)
    fails = []

    def fail(title, items):
        fails.append(title)
        print("FAIL %s: %d" % (title, len(items)))
        for i in items[:15]:
            print("   ", i)

    print("build: %d files" % len(files))
    missing = [f for f in ("index.html", "index1.html", "index2.html", "404.html", "robots.txt", "sitemap.xml",
                           "credits.html", "page/sjava/nos.html", "page/sjava/contact.html", "prods/r_area.zip") if f not in fset]
    if missing:
        fail("key files missing", missing)
    bad = [f for f in files if f.lower().endswith((".asp", ".inc", ".dll", ".exe", ".bat", ".cgi", ".psd", ".ctw", ".htm"))]
    bad += [f for f in files if f != f.lower()]
    if bad:
        fail("forbidden or non-lowercase file names", bad)
    hits, nocs, broken, ips = {}, [], [], []
    for rel in files:
        if not rel.endswith((".html", ".txt", ".xml")):
            continue
        text = rd(build / rel)
        body = REMOVAL.sub("", text)
        for label, rx in LEFTOVERS:
            if rx.search(body):
                hits.setdefault(label, []).append(rel)
        for m in IPV4.finditer(body):
            if not body[max(0, m.start() - 8):m.start()].lower().endswith("://"):
                ips.append("%s: %s" % (rel, m.group(0)))
        if rel.endswith(".html"):
            if not re.search(r"(?i)charset\s*=", text):
                nocs.append(rel)
            if rel.startswith("stats/") and re.search(r"(?i)<TD><B> </B><BR>[^<(]*\.(fr|net|com)", text):
                hits.setdefault("visitor host", []).append(rel)
            for m in LINK.finditer(text):
                raw = (m.group(2) if m.group(2) is not None else m.group(3)).strip()
                if not raw or re.match(r"(?i)^([a-z][a-z0-9+.-]*:|//|#)", raw):
                    continue
                path = unquote(raw.split("#", 1)[0].split("?", 1)[0])
                if not path:
                    continue
                t = os.path.normpath(path.lstrip("/") if path.startswith("/") else os.path.join(os.path.dirname(rel), path))
                t = "" if t == "." else t.replace(os.sep, "/")
                cands = [t]
                if t == "" or path.endswith("/") or "." not in t.rsplit("/", 1)[-1]:
                    pre = t.rstrip("/") + "/" if t.rstrip("/") else ""
                    cands = [pre + "index.html"]
                if not any(c in fset for c in cands):
                    broken.append("%s -> %s" % (rel, raw))
    for label, items in hits.items():
        fail("leftover '%s' in" % label, items)
    if ips:
        fail("IPv4 outside a URL host", ips)
    if nocs:
        fail("html without charset", nocs)
    if broken:
        fail("broken internal links", broken)
    print("RESULT:", "FAIL" if fails else "OK")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
