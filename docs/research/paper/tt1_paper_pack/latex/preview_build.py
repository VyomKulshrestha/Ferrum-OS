"""Render a layout preview of main.tex without a TeX engine.

No LaTeX toolchain was available in the environment this was built in (no pdflatex, xelatex,
lualatex, latexmk or tectonic; conda-forge has no texlive-core or tectonic build for win-64),
so this script reproduces the page geometry of the target template and flows the actual text,
tables and figures of main.tex through it to give a page count and a visual check.

What it reproduces faithfully:
  * page size, margins, text width/height, column width and gutter of the template;
  * the real text, table rows and figure sizes of main.tex, in document order;
  * float areas: full-width floats (figure*/table*) get a band at the top of a page, as in LaTeX.
What it only approximates:
  * the font (Times instead of acmart's Libertine / the USENIX template's Times variant);
  * hyphenation and the paragraph-breaking algorithm (greedy instead of Knuth-Plass);
  * exact float placement within a page, and acmart's `review` line numbers.
Treat the page count as an estimate good to roughly half a page, not as a pdflatex result.

Usage:  python preview_build.py acm      -> preview_asiaccs.pdf  (acmart sigconf metrics)
        python preview_build.py usenix   -> ../latex_usenix/preview_usenix.pdf
"""
import os
import re
import sys

from reportlab.lib.colors import Color, black
from reportlab.lib.enums import TA_JUSTIFY, TA_CENTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import Paragraph, Table, TableStyle, Spacer
from pypdf import PdfReader, PdfWriter, Transformation

HERE = os.path.dirname(os.path.abspath(__file__))

# --------------------------------------------------------------------------- templates

TEMPLATES = {
    # acmart sigconf: US letter, 7in x 9.25in text block, two 20pc columns, 9pt body.
    "acm": dict(
        tex=os.path.join(HERE, "main.tex"),
        out=os.path.join(HERE, "preview_asiaccs.pdf"),
        page=(612.0, 792.0), textwidth=504.0, textheight=666.0,
        left=54.0, top=54.0, colsep=21.72, body=9.0, leading=10.5,
        refsize=8.0, refleading=9.0, title=17.0,
        name="ACM acmart [sigconf,review,anonymous] (ASIA CCS)",
    ),
    # USENIX Security: US letter, 7in x 9in text block, two columns, 10pt body.
    "usenix": dict(
        tex=os.path.join(HERE, os.pardir, "latex_usenix", "main.tex"),
        out=os.path.join(HERE, os.pardir, "latex_usenix", "preview_usenix.pdf"),
        page=(612.0, 792.0), textwidth=504.0, textheight=648.0,
        left=54.0, top=72.0, colsep=23.76, body=10.0, leading=12.0,
        refsize=9.0, refleading=10.5, title=17.0,
        name="USENIX Security (letterpaper, twocolumn, 10pt)",
    ),
}

# --------------------------------------------------------------------------- tex -> text

ACCENTS = [
    ("{\\`e}", "\u00e8"), ("\\`e", "\u00e8"), ("{\\'e}", "\u00e9"), ("\\'e", "\u00e9"),
    ("{\\ss}", "\u00df"), ("\\ss", "\u00df"), ("{\\\"o}", "\u00f6"), ("\\\"o", "\u00f6"),
    ("{\\\"u}", "\u00fc"), ("{\\\"a}", "\u00e4"),
]

MATH = [
    (r"\\tau", "\u03c4"), (r"\\eta", "\u03b7"), (r"\\times", "\u00d7"),
    (r"\\le\b", "\u2264"), (r"\\ge\b", "\u2265"), (r"\\approx", "\u2248"),
    (r"\\mathbf\{1\}", "1"), (r"\\min", "min"), (r"\\max", "max"),
    (r"\\text\{([^}]*)\}", r"\1"), (r"\\,", "\u2009"), (r"\\;", "\u2009"),
]


def drop_macros(src):
    """Remove front-matter macros that are not body text."""
    for mac in ("\\keywords", "\\ccsdesc", "\\acmConference", "\\acmISBN", "\\acmDOI"):
        while mac in src:
            i = src.index(mac)
            j = src.index("{", i)
            _, k = brace_arg(src, j)
            src = src[:i] + src[k:]
    return src


def strip_comments(src):
    out = []
    for line in src.split("\n"):
        line = re.sub(r"(?<!\\)%.*$", "", line)
        out.append(line)
    return "\n".join(out)


def brace_arg(src, i):
    """Return (argument, index after closing brace) for src[i] == '{'."""
    assert src[i] == "{", src[i:i + 20]
    depth, j = 0, i
    while j < len(src):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[i + 1:j], j + 1
        j += 1
    raise ValueError("unbalanced braces")


def inline(s, refs=None, cites=None):
    """Convert inline LaTeX to reportlab markup."""
    s = s.replace("\n", " ")

    def math(m):
        t = m.group(1)
        for pat, rep in MATH:
            t = re.sub(pat, rep, t)
        t = re.sub(r"\^\{([^}]*)\}", r"<super>\1</super>", t)
        t = re.sub(r"\^(\w)", r"<super>\1</super>", t)
        t = re.sub(r"_\{([^}]*)\}", r"<sub>\1</sub>", t)
        t = re.sub(r"_(\w)", r"<sub>\1</sub>", t)
        t = t.replace("\\", "")
        return t

    s = re.sub(r"\$([^$]*)\$", math, s)
    s = re.sub(r"\\textbf\{([^{}]*)\}", r"<b>\1</b>", s)
    s = re.sub(r"\\emph\{([^{}]*)\}", r"<i>\1</i>", s)
    s = re.sub(r"\\textit\{([^{}]*)\}", r"<i>\1</i>", s)
    s = re.sub(r"\\url\{([^{}]*)\}", lambda m: m.group(1).replace("&", "&amp;"), s)

    def cite(m):
        keys = [k.strip() for k in m.group(1).split(",")]
        nums = []
        for k in keys:
            if cites is not None:
                if k not in cites:
                    cites[k] = len(cites) + 1
                nums.append(str(cites[k]))
            else:
                nums.append("?")
        return "[" + ", ".join(nums) + "]"

    s = re.sub(r"~?\\cite\{([^{}]*)\}", cite, s)
    s = re.sub(r"~?\\ref\{([^{}]*)\}", lambda m: (refs or {}).get(m.group(1), "??"), s)
    s = re.sub(r"\\label\{[^{}]*\}", "", s)
    s = s.replace("\\,", "\u2009").replace("\\ ", " ")
    for a, b in ACCENTS:
        s = s.replace(a, b)
    s = s.replace("``", "\u201c").replace("''", "\u201d")
    s = s.replace("--", "\u2013")
    s = re.sub(r"\\[%&_#]", lambda m: m.group(0)[1], s)
    s = s.replace("\\\\", " ").replace("~", "\u00a0")
    s = re.sub(r"\\(?:small|footnotesize|centering|toprule|midrule|bottomrule)\b", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def prescan(src):
    """Number sections, figures and tables up front so forward \\ref resolves."""
    labels = {}
    sec = sub = nfig = ntab = 0
    pat = re.compile(r"\\(section|subsection)(\*?)\{|\\begin\{(figure\*?|table\*?)\}")
    for m in pat.finditer(src):
        if m.group(1):
            arg, after = brace_arg(src, m.end() - 1)
            if m.group(1) == "section":
                if m.group(2) != "*":
                    sec += 1
                    sub = 0
                num = "" if m.group(2) == "*" else str(sec)
            else:
                sub += 1
                num = "%d.%d" % (sec, sub)
            lm = re.match(r"\s*\\label\{([^}]*)\}", src[after:])
            if lm:
                labels[lm.group(1)] = num
        else:
            env = m.group(3)
            base = "figure" if env.startswith("figure") else "table"
            if base == "figure":
                nfig += 1
                num = nfig
            else:
                ntab += 1
                num = ntab
            end = src.index("\\end{%s}" % env, m.end())
            lab = re.search(r"\\label\{([^}]*)\}", src[m.end():end])
            if lab:
                labels[lab.group(1)] = ("Figure %d" if base == "figure" else "Table %d") % num
    return labels


def parse(texpath):
    """Return (title, blocks, labels, cites). Blocks are dicts in document order."""
    src = strip_comments(open(texpath, encoding="utf-8").read())
    title = brace_arg(src, src.index("\\title") + len("\\title"))[0]
    src = drop_macros(src[src.index("\\begin{document}"):])

    blocks, cites = [], {}
    labels = prescan(src)
    sec = 0
    sub = 0
    nfig = 0
    ntab = 0

    # first pass: number sections, figures and tables so \ref resolves
    for m in re.finditer(r"\\(section|subsection)\*?\{|\\begin\{(figure|table)\*?\}", src):
        pass

    i = 0
    n = len(src)
    body_started = False
    while i < n:
        m = re.compile(
            r"\\(section|subsection|paragraph)(\*?)\{|"
            r"\\begin\{(abstract|itemize|enumerate|figure\*?|table\*?)\}|"
            r"\\(maketitle|appendix|bibliographystyle|end\{document\})"
        ).search(src, i)
        if not m:
            break
        # plain text between markers
        if body_started:
            chunk = src[i:m.start()]
            for para in re.split(r"\n\s*\n", chunk):
                txt = inline(para, labels, cites)
                if txt:
                    blocks.append(dict(kind="para", text=txt))
        i = m.end()

        if m.group(4) == "maketitle":
            body_started = True
            continue
        if m.group(4) == "appendix":
            continue
        if m.group(4) == "bibliographystyle":
            arg, i = brace_arg(src, src.index("{", i))
            j = src.index("\\bibliography{", i)
            arg2, i = brace_arg(src, src.index("{", j))
            blocks.append(dict(kind="refs", bib=arg2))
            continue
        if m.group(4) and m.group(4).startswith("end{document"):
            break

        if m.group(1):  # sectioning
            arg, i = brace_arg(src, m.end() - 1)
            starred = m.group(2) == "*"
            if m.group(1) == "section":
                if not starred:
                    sec += 1
                    sub = 0
                num = "" if starred else "%d" % sec
            elif m.group(1) == "subsection":
                sub += 1
                num = "%d.%d" % (sec, sub)
            else:
                num = None
            lm = re.match(r"\s*\\label\{([^}]*)\}", src[i:])
            if lm:
                i += lm.end()
            blocks.append(dict(kind="head", level=m.group(1), num=num,
                               text=inline(arg, labels, cites)))
            continue

        env = m.group(3)
        if env == "abstract":
            end = src.index("\\end{abstract}", i)
            blocks.append(dict(kind="head", level="section", num="",
                               text="Abstract"))
            for para in re.split(r"\n\s*\n", src[i:end]):
                txt = inline(para, labels, cites)
                if txt:
                    blocks.append(dict(kind="para", text=txt))
            i = end + len("\\end{abstract}")
            body_started = True
            continue

        if env in ("itemize", "enumerate"):
            end = src.index("\\end{%s}" % env, i)
            inner = src[i:end]
            items = [x for x in re.split(r"\\item\b", inner)[1:]]
            blocks.append(dict(kind="list", ordered=env == "enumerate",
                               items=[inline(x, labels, cites) for x in items]))
            i = end + len("\\end{%s}" % env)
            continue

        if env.startswith("figure") or env.startswith("table"):
            span2 = env.endswith("*")
            base = "figure" if env.startswith("figure") else "table"
            end = src.index("\\end{%s}" % env, i)
            inner = src[i:end]
            i = end + len("\\end{%s}" % env)
            if base == "figure":
                nfig += 1
                num = nfig
            else:
                ntab += 1
                num = ntab

            cap = ""
            cm = inner.find("\\caption")
            if cm >= 0:
                cap = brace_arg(inner, inner.index("{", cm))[0]
            blk = dict(kind=base, span2=span2, num=num,
                       caption=inline(cap, labels, cites))
            if base == "figure":
                g = re.search(r"\\includegraphics\[width=([^\]]*)\]\{([^}]*)\}", inner)
                blk["width"] = g.group(1)
                blk["path"] = g.group(2)
            else:
                tm = re.search(r"\\begin\{(tabularx|tabular)\}", inner)
                env2 = tm.group(1)
                pos = inner.index("{", tm.end() - 1)
                if env2 == "tabularx":
                    wspec, pos2 = brace_arg(inner, pos)
                    spec, after = brace_arg(inner, inner.index("{", pos2))
                    blk["xwidth"] = "column" if "columnwidth" in wspec else "text"
                else:
                    spec, after = brace_arg(inner, pos)
                    blk["xwidth"] = None
                tend = inner.index("\\end{%s}" % env2)
                body = inner[after:tend]
                blk["spec"] = spec
                blk["rows"] = parse_tabular(body, labels, cites)
                blk["small"] = "\\small" in inner
            blocks.append(blk)
            continue

    return title, blocks, labels, cites


def parse_tabular(body, labels, cites):
    rows = []
    for raw in body.split("\\\\"):
        raw = raw.replace("\\toprule", "").replace("\\midrule", "").replace("\\bottomrule", "")
        if not raw.strip():
            continue
        cells = [inline(c, labels, cites) for c in re.split(r"(?<!\\)&", raw)]
        rows.append(cells)
    return rows


# --------------------------------------------------------------------------- flowables

def build_flowables(blocks, T, cites, bibpath):
    colw = (T["textwidth"] - T["colsep"]) / 2.0
    body = ParagraphStyle("body", fontName="Times-Roman", fontSize=T["body"],
                          leading=T["leading"], alignment=TA_JUSTIFY,
                          firstLineIndent=T["body"], spaceAfter=0)
    body0 = ParagraphStyle("body0", parent=body, firstLineIndent=0)
    h1 = ParagraphStyle("h1", fontName="Times-Bold", fontSize=T["body"] + 1.5,
                        leading=T["leading"] + 3, spaceBefore=9, spaceAfter=3)
    h2 = ParagraphStyle("h2", fontName="Times-Bold", fontSize=T["body"] + 0.5,
                        leading=T["leading"] + 2, spaceBefore=7, spaceAfter=2)
    cap = ParagraphStyle("cap", fontName="Times-Roman", fontSize=T["body"] - 1,
                         leading=T["leading"] - 1, alignment=TA_JUSTIFY, spaceBefore=3)
    ref = ParagraphStyle("ref", fontName="Times-Roman", fontSize=T["refsize"],
                         leading=T["refleading"], leftIndent=10, firstLineIndent=-10,
                         spaceAfter=1.5)
    cell = ParagraphStyle("cell", fontName="Times-Roman", fontSize=T["body"] - 1.5,
                          leading=T["leading"] - 2.5)
    cellb = ParagraphStyle("cellb", parent=cell, fontName="Times-Bold")

    items = []          # (flowable, span2, is_float, meta)
    prev_head = True
    for b in blocks:
        if b["kind"] == "head":
            style = h1 if b["level"] in ("section",) else h2
            if b["level"] == "paragraph":
                items.append((Paragraph("<b>%s.</b>" % b["text"], body0), False, False, None))
                prev_head = True
                continue
            label = ("%s %s" % (b["num"], b["text"])).strip()
            items.append((Paragraph(label.upper() if b["level"] == "section" else label, style),
                          False, False, None))
            prev_head = True
        elif b["kind"] == "para":
            items.append((Paragraph(b["text"], body0 if prev_head else body), False, False, None))
            prev_head = False
        elif b["kind"] == "list":
            for k, it in enumerate(b["items"], 1):
                bullet = "%d." % k if b["ordered"] else "\u2022"
                st = ParagraphStyle("li%d" % k, parent=body0, leftIndent=10,
                                    firstLineIndent=-10, spaceAfter=1)
                items.append((Paragraph("%s\u2002%s" % (bullet, it), st), False, False, None))
            prev_head = False
        elif b["kind"] == "figure":
            w = T["textwidth"] if b["span2"] else colw
            if "0.92" in b["width"]:
                w *= 0.92
            path = os.path.join(os.path.dirname(T["tex"]), b["path"].replace("/", os.sep))
            pw, ph = pdf_size(path)
            h = w * ph / pw
            capflow = Paragraph("<b>Figure %d:</b> %s" % (b["num"], b["caption"]), cap)
            items.append((("IMG", path, w, h, capflow), b["span2"], True, b["num"]))
            prev_head = False
        elif b["kind"] == "table":
            w = T["textwidth"] if b["span2"] else colw
            t = make_table(b, w, cell, cellb, T)
            capflow = Paragraph("<b>Table %d:</b> %s" % (b["num"], b["caption"]), cap)
            items.append((("TAB", t, capflow, w), b["span2"], True, b["num"]))
            prev_head = False
        elif b["kind"] == "refs":
            items.append((Paragraph("REFERENCES", h1), False, False, "REFSTART"))
            for k, entry in enumerate(bib_entries(bibpath, cites), 1):
                items.append((Paragraph("[%d]\u2002%s" % (k, entry), ref), False, False, None))
    return items, colw


def parse_spec(spec):
    """Return a list of column descriptors from a tabular/tabularx column spec."""
    spec = spec.replace("@{}", "")
    cols, i, hs = [], 0, 1.0
    while i < len(spec):
        ch = spec[i]
        if ch == ">":
            arg, i = brace_arg(spec, spec.index("{", i))
            m = re.search(r"\\hsize\s*=\s*([0-9.]+)", arg)
            hs = float(m.group(1)) if m else 1.0
            continue
        if ch == "p":
            arg, i = brace_arg(spec, spec.index("{", i))
            frac = float(re.match(r"([0-9.]+)", arg).group(1))
            cols.append(("p", frac, "columnwidth" in arg))
            hs = 1.0
            continue
        if ch in "XLC":
            cols.append(("x", hs, None))
            hs = 1.0
        elif ch in "lcr":
            cols.append(("n", ch, None))
            hs = 1.0
        i += 1
    return cols


def make_table(b, width, cell, cellb, T):
    from reportlab.pdfbase.pdfmetrics import stringWidth
    rows = b["rows"]
    ncol = max(len(r) for r in rows)
    cols = parse_spec(b["spec"])[:ncol]
    while len(cols) < ncol:
        cols.append(("n", "l", None))
    colw = (T["textwidth"] - T["colsep"]) / 2.0
    ref = T["textwidth"] if b["span2"] else colw
    fs = T["body"] - 1.5
    pad = 8.0

    widths = [None] * ncol
    for k, (kind, a, iscol) in enumerate(cols):
        if kind == "p":
            widths[k] = a * (colw if iscol else ref)
        elif kind == "n":
            nat = 0.0
            for r in rows:
                if k < len(r):
                    txt = re.sub(r"<[^>]*>", "", r[k])
                    nat = max(nat, stringWidth(txt, "Times-Roman", fs))
            widths[k] = min(nat + pad, width * 0.5)
    used = sum(w for w in widths if w is not None)
    xs = [k for k, c in enumerate(cols) if c[0] == "x"]
    if xs:
        tot = sum(cols[k][1] for k in xs)
        rest = max(width - used, width * 0.15)
        for k in xs:
            widths[k] = rest * cols[k][1] / tot
    total = sum(widths)
    if total > width:
        widths = [w * width / total for w in widths]

    data = []
    for ri, r in enumerate(rows):
        r = list(r) + [""] * (ncol - len(r))
        data.append([Paragraph(c, cellb if ri == 0 else cell) for c in r])
    t = Table(data, colWidths=widths, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, 0), 0.8, black),
        ("LINEBELOW", (0, 0), (-1, 0), 0.4, black),
        ("LINEBELOW", (0, -1), (-1, -1), 0.8, black),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
    ]))
    return t


def pdf_size(path):
    r = PdfReader(path)
    box = r.pages[0].mediabox
    return float(box.width), float(box.height)


def bib_entries(bibpath, cites):
    """Format refs.bib in citation-key order, numbered as cited."""
    src = open(bibpath, encoding="utf-8").read()
    src = re.sub(r"^\s*%.*$", "", src, flags=re.M)
    entries = {}
    for m in re.finditer(r"@(\w+)\s*\{\s*([^,]+),", src):
        start = m.end()
        depth, j = 1, src.index("{", m.start())
        k = j + 1
        while k < len(src) and depth:
            if src[k] == "{":
                depth += 1
            elif src[k] == "}":
                depth -= 1
            k += 1
        entries[m.group(2).strip()] = src[start:k - 1]
    out = []
    for key in sorted(cites, key=cites.get):
        raw = entries.get(key, "")
        f = {}
        for fm in re.finditer(r"(\w+)\s*=\s*", raw):
            p = fm.end()
            if raw[p] == "{":
                val, _ = brace_arg(raw, p)
            else:
                val = re.match(r"[^,]*", raw[p:]).group(0)
            f[fm.group(1).lower()] = re.sub(r"\s+", " ", val).strip()
        for a, b in ACCENTS:
            raw = raw.replace(a, b)
            f = {k: v.replace(a, b) for k, v in f.items()}
        au = f.get("author", "").replace("{", "").replace("}", "")
        au = " and ".join(a.strip() for a in au.split(" and "))
        bits = [b for b in [au, f.get("title", "").replace("{", "").replace("}", ""),
                            f.get("booktitle", f.get("journal", f.get("howpublished", ""))),
                            f.get("year", "")] if b]
        s = ". ".join(bits)
        if f.get("doi"):
            s += ". doi:" + f["doi"]
        if f.get("note"):
            s += ". " + f["note"]
        out.append(s.replace("&", "&amp;"))
    return out


# --------------------------------------------------------------------------- layout

def layout(items, T, colw, titleband=0.0):
    """Pack items into pages of two columns, full-width floats queued FIFO to page tops.

    LaTeX keeps floats in declaration order and puts a deferred [t] float at the top of a
    later page; the queue below does the same, which is what makes the page count comparable.
    """
    return _pack(items, T, colw, titleband)


def _flow_height(f, w):
    return f.wrap(w, 10000)[1]


def _float_size(flow, T):
    if flow[0] == "IMG":
        _, path, w, h, capf = flow
        return h + _flow_height(capf, w) + 10.0, w
    _, tab, capf, w = flow
    return _flow_height(tab, w) + _flow_height(capf, w) + 12.0, w


class _Page:
    def __init__(self):
        self.items = []
        self.cursor = [0.0, 0.0]
        self.band = 0.0
        self.col = 0


def _pack(items, T, colw, titleband=0.0):
    x0, H = T["left"], T["textheight"]
    ytop = T["page"][1] - T["top"]
    ybot = ytop - H
    pages, placements = [], []
    pending = []                      # queued full-width floats, in declaration order

    def colx(c):
        return x0 if c == 0 else x0 + colw + T["colsep"]

    def draw_float(pg, pi, flow, x, y, span_centre=False):
        """Place one float with its caption, top edge at y; return consumed height."""
        if flow[0] == "IMG":
            _, path, fw, fh, capf = flow
            ch = _flow_height(capf, fw)
            xx = x + (T["textwidth"] - fw) / 2.0 if span_centre else x
            placements.append((pi, path, xx, y - fh, fw, fh))
            pg.items.append((capf, xx, y - fh - ch - 3, fw))
            return fh + ch + 10.0
        _, tab, capf, fw = flow
        ch = _flow_height(capf, fw)
        th = _flow_height(tab, fw)
        pg.items.append((capf, x, y - ch, fw))
        pg.items.append((tab, x, y - ch - 6 - th, fw))
        return th + ch + 12.0

    def new_page(pi):
        pg = _Page()
        pages.append(pg)
        y = ytop - (titleband if pi == 0 else 0.0)
        limit = 0.90 * (y - ybot)
        used = 0.0
        while pending:
            h, w = _float_size(pending[0], T)
            if used + h > limit:
                break
            used += draw_float(pg, pi, pending.pop(0), x0, y - used, span_centre=True)
        pg.band = (ytop - y) + used
        pg.cursor = [y - used, y - used]
        return pg

    pi = 0
    pg = new_page(0)

    def advance():
        nonlocal pg, pi
        if pg.col == 0:
            pg.col = 1
        else:
            pi += 1
            pg = new_page(pi)
            pg.col = 0

    refstart = None
    for flow, span2, isfloat, meta in items:
        if span2:
            pending.append(flow)
            continue
        if isinstance(flow, tuple) and flow[0] in ("IMG", "TAB"):
            h, w = _float_size(flow, T)
            if pg.cursor[pg.col] - h < ybot:
                advance()
            pg.cursor[pg.col] -= draw_float(pg, pi, flow, colx(pg.col), pg.cursor[pg.col])
            continue
        h = _flow_height(flow, colw)
        sb = getattr(flow.style, "spaceBefore", 0) if hasattr(flow, "style") else 0
        sa = getattr(flow.style, "spaceAfter", 0) if hasattr(flow, "style") else 0
        if pg.cursor[pg.col] - (h + sb + sa) < ybot:
            advance()
            sb = 0
        y = pg.cursor[pg.col] - sb
        pg.items.append((flow, colx(pg.col), y - h, colw))
        if meta == "REFSTART":
            pg.items.append(("REFSTART", pi + 1, 0, 0))
        pg.cursor[pg.col] = y - h - sa

    while pending:                     # leftovers go on float pages, as LaTeX does
        pi += 1
        pg = _Page()
        pages.append(pg)
        used = 0.0
        while pending:
            h, w = _float_size(pending[0], T)
            if used + h > H:
                break
            used += draw_float(pg, pi, pending.pop(0), x0, ytop - used, span_centre=True)
        pg.cursor = [ytop - used, ytop - used]
        pg.band = used
    return pages, placements


def render(name, T):
    title, blocks, labels, cites = parse(T["tex"])
    bibpath = os.path.join(os.path.dirname(T["tex"]), "refs.bib")
    items, colw = build_flowables(blocks, T, cites, bibpath)
    ts = ParagraphStyle("t", fontName="Times-Bold", fontSize=T["title"],
                        leading=T["title"] + 3, alignment=TA_CENTER)
    tp = Paragraph(inline(title), ts)
    th = _flow_height(tp, T["textwidth"])
    ap = Paragraph("Anonymous Author(s)", ParagraphStyle(
        "a", fontName="Times-Roman", fontSize=T["body"] + 1,
        leading=T["body"] + 4, alignment=TA_CENTER))
    ah = _flow_height(ap, T["textwidth"])
    titleband = th + ah + 22.0
    pages, placements = layout(items, T, colw, titleband)

    raw = T["out"] + ".raw"
    c = pdfcanvas.Canvas(raw, pagesize=T["page"])
    refstart = None
    for pi, pg in enumerate(pages):
        if pi == 0:
            tp.wrap(T["textwidth"], 10000)
            tp.drawOn(c, T["left"], T["page"][1] - T["top"] - th)
            ap.wrap(T["textwidth"], 10000)
            ap.drawOn(c, T["left"], T["page"][1] - T["top"] - th - ah - 8)
        for it in pg.items:
            if it[0] == "REFSTART":
                refstart = it[1]
                continue
            flow, x, y, w = it
            flow.wrap(w, 10000)
            flow.drawOn(c, x, y)
        c.setFont("Times-Roman", 8)
        c.drawCentredString(T["page"][0] / 2.0, 36, str(pi + 1))
        c.showPage()
    c.save()

    # stamp the real figure PDFs into the reserved space
    reader = PdfReader(raw)
    writer = PdfWriter()
    for p in reader.pages:
        writer.add_page(p)
    for pi, path, x, y, w, h in placements:
        fr = PdfReader(path)
        fp = fr.pages[0]
        sx = w / float(fp.mediabox.width)
        sy = h / float(fp.mediabox.height)
        s = min(sx, sy)
        writer.pages[pi].merge_transformed_page(
            fp, Transformation().scale(s, s).translate(x, y))
    with open(T["out"], "wb") as fh:
        writer.write(fh)
    os.remove(raw)

    body_pages = refstart if refstart else len(pages)
    print("%s" % T["name"])
    print("  file                 : %s" % os.path.relpath(T["out"], HERE))
    print("  total pages          : %d" % len(pages))
    print("  main text ends on    : page %d" % body_pages)
    print("  references           : pages %d-%d (%.1f pages)"
          % (body_pages, len(pages), len(pages) - body_pages + 1))
    print("  figures stamped      : %d   tables typeset: %d"
          % (len(placements), sum(1 for b in blocks if b["kind"] == "table")))
    return len(pages), body_pages


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "acm"
    render(which, TEMPLATES[which])
