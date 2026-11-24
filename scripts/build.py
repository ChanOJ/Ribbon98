#!/usr/bin/env python3
"""Generate site/ from the raw store (the .rIBBON! website, version 02/22/1998).

    python3 -I scripts/build.py [--raw ~/Code/Ribbon98-raw] [--out site]

Read-only on the raw store. Deterministic: the output only depends on the inputs.
Paths are lowercased, `.htm` becomes `.html` (pages keep their original paths), links are
rewritten to root-absolute paths, dead links become plain text, forms are frozen, e-mail
addresses are masked as `local＠????`, and the demo archives in `prods/` are rebuilt with
e-mail addresses and phone numbers masked inside their files.
"""
import argparse
import os
import re
import shutil
import sys
import zipfile
from pathlib import Path
from posixpath import normpath, join as pjoin, dirname
from urllib.parse import unquote, urlsplit

REPO = Path(__file__).resolve().parent.parent
ENC = "iso-8859-1"
SRC = "ribbon"  # folder of the raw store holding the 1998-02-22 version
OJ = "https://orangejuice97.sauthier.family/"

DROP_EXT = (".ctw", ".asp", ".inc", ".dll", ".cgi", ".psd")
# links to the original host that point at a demo archive under another name
ZIP_ALIASES = {
    "prods/r-id4.zip": "prods/r_id4.zip",
    "prods/r_priv.zip": "prods/r_privat.zip",
    "prods/r_btoast.zip": "prods/btoast.zip",
    "prods/r_ltp2.zip": "prods/ltp2.zip",
    "prods/ltn_ccn.zip": "prods/ltp_ccn.zip",
    "prods/ltp2tro.zip": "prods/ltp2zen.zip",
}
FROZEN_PAGES = {"page/sjava/email.htm", "page/sjava/merci.htm"}

REMOVAL_NOTE = (
    '<div id="removal-note" style="clear:both;margin:28px auto 8px;padding:6px 8px 0;width:60%;'
    'border-top:1px solid #808080;text-align:center;font:10px/14px Verdana,Arial,Helvetica,sans-serif;'
    'color:#808080;background:transparent">To be removed from this page, '
    '<a href="mailto:chandra_oj@pm.me" style="color:#808080;text-decoration:underline">contact me</a>.</div>'
)
FORM_BANNER = (
    '<div id="archive-note" style="margin:0 0 12px;padding:6px 8px;border:1px solid #808080;'
    'background:#202020;color:#c0c0c0;text-align:center;font:11px/15px Verdana,Arial,Helvetica,sans-serif">'
    "Archive of the .rIBBON! website (1998): this form is frozen and does nothing.</div>"
)
HOME_NOTE = (
    '<div id="archive-note" style="margin:20px auto 8px;padding:6px 8px 0;width:500px;'
    'border-top:1px solid #808080;text-align:center;font:11px/15px Verdana,Arial,Helvetica,sans-serif;'
    'color:#a0a0a0">Archive of the website of the demogroup .rIBBON! as it was on 1998-02-22. Read-only: '
    "forms, e-mail links and counters no longer work. Full list of the old sites: "
    '<a href="https://chanoj.github.io/" style="color:#a0a0a0">chanoj.github.io</a>.</div>'
)
NOT_FOUND = """<HTML>
<HEAD>
<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=iso-8859-1">
<TITLE>.rIBBON! - page not found</TITLE>
</HEAD>
<BODY TEXT="#FFFFFF" BGCOLOR="#000000" LINK="#FFFFFF" VLINK="#408080">
<CENTER><br><br>
<TABLE BORDER=0 CELLSPACING=0 CELLPADDING=0 WIDTH="60%" BGCOLOR="#FFCC33"><TR><TD>
<CENTER><B><FONT COLOR="#000000">404 ERROR - FILE NOT FOUND</FONT></B></CENTER>
</TD></TR></TABLE>
<br>
<B><TT>This page is not part of the archive of the .rIBBON! website (1998).
<A HREF="/">Back to the home page</A>.</TT></B>
</CENTER>
</BODY>
</HTML>
"""

TAG_A = re.compile(r"(?is)<a\b[^>]*>|</a\s*>")
TAG_AREA = re.compile(r"(?is)<area\b[^>]*>")
TAG_IMG = re.compile(r"(?is)<img\b[^>]*>")
ATTR = lambda name: re.compile(r"""(?is)(\s%s\s*=\s*)(?:"([^"]*)"|'([^']*)'|([^\s>]+))""" % name)
HREF, SRCATTR, BACKGROUND = ATTR("href"), ATTR("src"), ATTR("background")
MAILTO_A = re.compile(r"""(?is)<a\b[^>]*href\s*=\s*["']?mailto:([^"'>\s?]+)[^>]*>(.*?)</a\s*>""")
EMAIL = re.compile(r"(?i)\b([A-Za-z0-9._+-]+)@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)")
FULLWIDTH_AT = "&#65312;"

# masking inside the demo archives (bytes, same length so that nothing shifts)
B_EMAIL = re.compile(rb"([A-Za-z0-9._+-]+)@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.(?:com|net|org|edu|fr|se|fi|be|nl|de|uk|mail))\b", re.I)
# members that can hold text; image/data members are left untouched (digits there are not phone numbers)
MASK_EXT = (".nfo", ".txt", ".diz", ".exe", ".com", ".xm", ".s3m", ".mod", ".mxm", ".asc", ".doc")
B_PHONE = re.compile(rb"(?:\+\d\d[ .(-]*\(?0?\)?[ .-]*\d(?:[ .-]*\d){7,9}|\b0\d[ .-]+(?:-\s*)?\d\d(?:[ .-]+\d\d){3}\b)")


def rd(p):
    return Path(p).read_bytes().decode(ENC)


def wr(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.encode(ENC, "xmlcharrefreplace"))


def attr_value(m):
    return next(g for g in m.groups()[1:] if g is not None)


def mask_bytes(data):
    """Mask e-mail addresses and phone numbers in a binary/text file, keeping its length."""
    n = [0]

    def mail(m):
        n[0] += 1
        return m.group(1) + b"@" + b"?" * len(m.group(2))

    def phone(m):
        n[0] += 1
        return re.sub(rb"\d", b"?", m.group(0))

    data = B_EMAIL.sub(mail, data)
    data = B_PHONE.sub(phone, data)
    return data, n[0]


def rebuild_zip(src, dst, log):
    """Copy a zip with every member masked; same names, dates and order, deterministic."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(src) as zi, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zo:
        for info in zi.infolist():
            if info.is_dir():
                zo.writestr(info, b"")
                continue
            data = zi.read(info.filename)
            new, n = mask_bytes(data) if info.filename.lower().endswith(MASK_EXT) else (data, 0)
            if n:
                log.append("%s: %s (%d masked)" % (src.name, info.filename, n))
            ni = zipfile.ZipInfo(info.filename, info.date_time)
            ni.compress_type = zipfile.ZIP_DEFLATED
            ni.external_attr = info.external_attr
            zo.writestr(ni, new)


class Site:
    def __init__(self, raw):
        self.root = Path(raw).expanduser() / SRC
        self.files = {}  # virtual path (lowercase) -> source
        self.dest = {}
        for r, ds, fs in os.walk(self.root):
            ds.sort()
            for f in sorted(fs):
                p = Path(r, f)
                rel = p.relative_to(self.root).as_posix().lower()
                if f == ".DS_Store" or rel.endswith(DROP_EXT):
                    continue
                self.files[rel] = p
        for rel in self.files:
            self.dest[rel] = rel + "l" if rel.endswith(".htm") else rel
        self.unresolved = {}

    def lookup(self, v):
        v = ZIP_ALIASES.get(v, v)
        if v in ("", ".", "index.ctw"):
            v = "index.htm"
        if v in self.dest:
            u = "/" + self.dest[v]
            return "/" if u == "/index.html" else u
        return None

    def resolve(self, page, href):
        """('url', published URL) | ('keep', href) | ('drop', None)."""
        href = href.strip()
        low = href.lower()
        if low.startswith(("javascript:", "data:", "mailto:")):
            return "drop", None
        if low.startswith("#"):
            return "keep", href
        frag = ""
        if "#" in href:
            href, _, frag = href.partition("#")
            frag = "#" + frag
        if low.startswith(("http:", "https:", "ftp:", "news:", "irc:", "//")):
            u = urlsplit(href)
            host = (u.hostname or "").lower()
            if host == "ojuice.citeweb.net":
                return "url", OJ
            if host in ("www.citeweb.net", "citeweb.net"):
                path = unquote(u.path).strip("/").lower()
                if path == "ribbon":
                    return "url", "/" + frag
                if path.startswith("ribbon/"):
                    r = self.lookup(path[len("ribbon/"):])
                    if r:
                        return "url", r + frag
            return "drop", None
        path = unquote(href.split("?", 1)[0]).replace("\\", "/")
        if path == "":
            return "drop", None
        if path.startswith("/"):
            v = normpath(path.lstrip("/")).lower()
        else:
            v = normpath(pjoin(dirname(page), path)).lower()
        if v.startswith(".."):
            return "drop", None
        r = self.lookup(v)
        if r is None and v.endswith((".jpg", ".gif")):
            same = [k for k in self.dest if k.rsplit("/", 1)[-1] == v.rsplit("/", 1)[-1]]
            r = self.lookup(same[0]) if len(same) == 1 else None
        if r is None:
            self.unresolved.setdefault(v, set()).add(page)
            return "drop", None
        return "url", r + frag

    def rewrite(self, rel, text):
        def area(m):
            tag = m.group(0)
            h = HREF.search(tag)
            if not h:
                return tag
            kind, val = self.resolve(rel, attr_value(h))
            if kind in ("url", "keep"):
                return HREF.sub(lambda mm: '%s"%s"' % (mm.group(1), val), tag, count=1)
            return ""

        text = TAG_AREA.sub(area, text)

        out, pos, unwrap = [], 0, []
        for m in TAG_A.finditer(text):
            out.append(text[pos:m.start()])
            pos = m.end()
            tag = m.group(0)
            if tag.startswith("</"):
                out.append("" if unwrap and unwrap.pop() else "</a>")
                continue
            h = HREF.search(tag)
            if not h:
                out.append(tag)
                unwrap.append(False)
                continue
            kind, val = self.resolve(rel, attr_value(h))
            if kind in ("url", "keep"):
                out.append(HREF.sub(lambda mm: '%s"%s"' % (mm.group(1), val), tag, count=1))
                unwrap.append(False)
            else:
                out.append("")
                unwrap.append(True)
        out.append(text[pos:])
        text = "".join(out)

        def media(m):
            tag = re.sub(r"(?i)\s+ismap\b", "", m.group(0))
            h = SRCATTR.search(tag)
            if h:
                kind, val = self.resolve(rel, attr_value(h))
                if kind != "url":
                    return ""
                tag = SRCATTR.sub(lambda mm: '%s"%s"' % (mm.group(1), val), tag, count=1)
            return tag

        text = TAG_IMG.sub(media, text)

        def body_bg(m):
            tag = m.group(0)
            h = BACKGROUND.search(tag)
            if h:
                kind, val = self.resolve(rel, attr_value(h))
                tag = BACKGROUND.sub(lambda mm: '%s"%s"' % (mm.group(1), val) if kind == "url" else "", tag, count=1)
            return tag

        return re.sub(r"(?is)<body\b[^>]*>", body_bg, text)

    def sanitize(self, rel, text):
        # e-mail links: text kept, address shown masked (the removal footer is added later)
        def mail(m):
            local = m.group(1).split("@")[0]
            label = re.sub(r"(?:&nbsp;|\s)+$", "", m.group(2))
            return "%s (%s%s????)" % (label, local, FULLWIDTH_AT)

        text = MAILTO_A.sub(mail, text)
        if rel in FROZEN_PAGES:
            text = re.sub(r"(?is)<form\b[^>]*>", '<div class="frozen-form">', text)
            text = re.sub(r"(?is)</form\s*>", "</div>", text)
            text = re.sub(r"(?is)<(input|select|textarea)\b", r"<\1 disabled", text)
            text = re.sub(r"(?is)(<body\b[^>]*>)", lambda m: m.group(1) + FORM_BANNER, text, count=1)
        text = EMAIL.sub(lambda m: m.group(1) + FULLWIDTH_AT + "????", text)
        if not re.search(r"(?i)charset\s*=", text):
            text = re.sub(r"(?i)(<head[^>]*>)", r'\1<meta http-equiv="Content-Type" content="text/html; charset=iso-8859-1">', text, count=1)
        return text

    @staticmethod
    def _append(text, note):
        m = re.search(r"(?is)</body\s*>(?!.*</body\s*>)", text)
        if m:
            return text[: m.start()] + note + "\n" + text[m.start():]
        return text + "\n" + note + "\n"

    def run(self, out):
        if out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True)
        zlog = []
        for rel in sorted(self.files):
            p = self.files[rel]
            d = out / self.dest[rel]
            if rel.endswith((".htm", ".html")):
                text = self.rewrite(rel, self.sanitize(rel, rd(p)))
                if FULLWIDTH_AT + "????" in text:  # footer only where an e-mail local part shows
                    text = self._append(text, REMOVAL_NOTE)
                if rel == "index.htm":
                    text = self._append(text, HOME_NOTE)
                wr(d, text)
            elif rel.endswith(".zip"):
                rebuild_zip(p, d, zlog)
            else:
                d.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(p, d)
        wr(out / "404.html", NOT_FOUND)
        return len(self.files) + 1, zlog


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--raw", default=os.environ.get("RIBBON98_RAW", "~/Code/Ribbon98-raw"))
    ap.add_argument("--out", default=str(REPO / "site"))
    a = ap.parse_args(argv)
    s = Site(a.raw)
    n, zlog = s.run(Path(a.out))
    print("build: %d files in %s" % (n, a.out))
    print("masked inside demo archives: %d members" % len(zlog))
    for z in zlog:
        print("   ", z)
    un = {k: sorted(v)[:2] for k, v in sorted(s.unresolved.items())}
    print("unresolved link targets (made plain text): %d" % len(un))
    for k, v in un.items():
        print("   ", k, "<-", v)


if __name__ == "__main__":
    sys.exit(main())
