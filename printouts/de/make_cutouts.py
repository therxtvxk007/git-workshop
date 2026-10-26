"""Build scissor-friendly A4 cutout sheets for the DE lab printouts.

    python3 make_cutouts.py verilog_source.txt <figures_dir> <out_dir>

Layout rules (same idea as the DSA cutouts, but faster to cut):
  * every cutout is exactly 17 cm wide, centred, so ONE cut down each side
    of the stack trims all of them at once;
  * cutouts on a page are stacked edge to edge and share a single dashed
    line, so ONE horizontal cut separates two neighbours (no slivers);
  * every cutout carries a big paste-order number and "Part k/n";
  * a long program breaks at a file or `endmodule` boundary where possible.
"""
import re
import sys
from pathlib import Path

from reportlab.lib.colors import Color, black, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

FONT_DIR = "/usr/share/fonts/truetype/dejavu/"
pdfmetrics.registerFont(TTFont("Sans", FONT_DIR + "DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("Sans-Bold", FONT_DIR + "DejaVuSans-Bold.ttf"))
pdfmetrics.registerFont(TTFont("Mono", FONT_DIR + "DejaVuSansMono.ttf"))
pdfmetrics.registerFont(TTFont("Mono-Bold", FONT_DIR + "DejaVuSansMono-Bold.ttf"))

PAGE_W, PAGE_H = A4
BOX_W = 17 * cm
BOX_X = (PAGE_W - BOX_W) / 2
TOP = PAGE_H - 1.5 * cm          # first cut line
BOTTOM = 1.5 * cm                # lowest allowed cut line
PAD = 0.35 * cm
HEAD_H = 1.25 * cm               # title + subtitle band inside a cutout
CODE_PT = 7.7
LEAD = CODE_PT * 1.22
FILE_GAP = 0.18 * cm             # space above a file-name label
CHAR_W = pdfmetrics.stringWidth("M", "Mono", CODE_PT)
MAX_CHARS = int((BOX_W - 2 * PAD) / CHAR_W)
MIN_LINES = 8                    # never start a part with fewer lines than this
GREY = Color(0.45, 0.45, 0.45)
LIGHT = Color(0.93, 0.93, 0.93)


# ---------------------------------------------------------------- source ---

def parse_verilog(path):
    """-> list of items: {exp, exp_title, title, rows}; rows are (kind, text)."""
    items, exp = [], None
    for line in Path(path).read_text().splitlines():
        if line.startswith("@@ EXPERIMENT"):
            num, title = line[len("@@ EXPERIMENT "):].split(" | ", 1)
            exp = (int(num), title)
        elif line.startswith("@@ ITEM"):
            items.append({"exp": exp[0], "exp_title": exp[1],
                          "title": line[len("@@ ITEM "):], "rows": []})
        elif line.startswith("@@ FILE"):
            items[-1]["rows"].append(("file", line[len("@@ FILE "):]))
        else:
            for part in wrap(line):
                items[-1]["rows"].append(("code", part))
    return items


def wrap(line):
    """Wrap a long code line, preferring ', ' outside string literals."""
    if len(line) <= MAX_CHARS:
        return [line]
    indent = len(line) - len(line.lstrip()) + 4
    out, first = [], True
    while len(line) > (MAX_CHARS if first else MAX_CHARS - indent):
        limit = MAX_CHARS if first else MAX_CHARS - indent
        cut, in_str = None, False
        for i, ch in enumerate(line[:limit]):
            if ch == '"':
                in_str = not in_str
            elif ch == "," and not in_str and line[i + 1:i + 2] == " ":
                cut = i + 1
        if cut is None:
            cut = line.rfind(" ", 0, limit)
            cut = cut if cut > indent else limit
        out.append(line[:cut].rstrip() if first else " " * indent + line[:cut].strip())
        line, first = line[cut:].lstrip(), False
    out.append(line if first else " " * indent + line)
    return out


def row_h(kind):
    return LEAD + (FILE_GAP if kind == "file" else 0)


# ---------------------------------------------------------------- layout ---

def box_height(rows):
    return HEAD_H + sum(row_h(k) for k, _ in rows) + PAD


def take_rows(rows, avail):
    """How many leading rows fit in `avail` points, and whether the break is
    tidy (before a file label / after `endmodule`). Never leaves a tail
    shorter than MIN_LINES."""
    space, n = avail - HEAD_H - PAD, 0
    while n < len(rows) and space >= row_h(rows[n][0]):
        space -= row_h(rows[n][0])
        n += 1
    if n == len(rows):
        return n, True
    n = min(n, len(rows) - MIN_LINES)
    for k in range(n, MIN_LINES - 1, -1):
        if rows[k][0] == "file" or rows[k - 1][1].strip() == "endmodule":
            return k, True
    return n, False


def paginate(units):
    """units: list of {label, rows|image}. Returns pages of placed boxes."""
    pages, page, y = [], [], TOP
    for u in units:
        if "image" in u:
            pieces = [dict(u, h=u["h"])]
        else:
            pieces, rows = [], u["rows"]
            while rows:
                avail = y - BOTTOM
                n, tidy = take_rows(rows, avail)
                if n < min(MIN_LINES, len(rows)) or (not tidy and page):
                    pages.append(page)
                    page, y = [], TOP
                    continue
                piece = dict(u, rows=rows[:n], h=box_height(rows[:n]))
                pieces.append(piece)
                page.append(piece)
                y -= piece["h"]
                rows = rows[n:]
            for i, p in enumerate(pieces):
                p["part"] = (i + 1, len(pieces))
            continue
        piece = pieces[0]
        if y - piece["h"] < BOTTOM:
            pages.append(page)
            page, y = [], TOP
        piece["part"] = (1, 1)
        page.append(piece)
        y -= piece["h"]
    if page:
        pages.append(page)
    return [p for p in pages if p]


# ---------------------------------------------------------------- render ---

def scissors_line(c, y):
    c.setDash(4, 3)
    c.setLineWidth(0.6)
    c.setStrokeColor(black)
    c.line(BOX_X - 0.9 * cm, y, BOX_X + BOX_W + 0.9 * cm, y)
    c.setDash()
    c.setFont("Sans", 11)
    c.drawRightString(BOX_X - 0.95 * cm, y - 4, "✂")


def side_lines(c, top, bottom):
    c.setDash(4, 3)
    c.setLineWidth(0.6)
    for x in (BOX_X, BOX_X + BOX_W):
        c.line(x, top + 0.6 * cm, x, bottom - 0.6 * cm)
    c.setDash()


def draw_box(c, b, top, seq, kind_label):
    h = b["h"]
    # paste-order tab
    tab = f"{seq:02d}"
    c.setFillColor(black)
    c.rect(BOX_X, top - 0.85 * cm, 1.15 * cm, 0.85 * cm, stroke=0, fill=1)
    c.setFillColor(white)
    c.setFont("Sans-Bold", 13)
    c.drawCentredString(BOX_X + 0.575 * cm, top - 0.62 * cm, tab)
    c.setFillColor(black)
    tx = BOX_X + 1.45 * cm
    c.setFont("Sans-Bold", 10)
    c.drawString(tx, top - 0.5 * cm, f"{b['head']}  |  {kind_label}")
    c.setFont("Sans", 9)
    c.drawString(tx, top - 0.95 * cm, b["sub"])
    k, n = b["part"]
    c.setFont("Sans-Bold" if n > 1 else "Sans", 9)
    c.drawRightString(BOX_X + BOX_W - PAD, top - 0.5 * cm,
                      f"Part {k}/{n}" + ("  (continues →)" if k < n else ""))
    y = top - HEAD_H
    if "image" in b:
        iw, ih = b["iw"], b["ih"]
        c.drawImage(b["image"], BOX_X + (BOX_W - iw) / 2, y - ih, iw, ih)
        return
    for kind, text in b["rows"]:
        if kind == "file":
            y -= FILE_GAP + LEAD
            c.setFillColor(LIGHT)
            c.rect(BOX_X + PAD - 2, y - 2.2, BOX_W - 2 * PAD + 4, LEAD, stroke=0, fill=1)
            c.setFillColor(black)
            c.setFont("Mono-Bold", CODE_PT)
            c.drawString(BOX_X + PAD, y, text)
        else:
            y -= LEAD
            c.setFont("Mono", CODE_PT)
            c.drawString(BOX_X + PAD, y, text)


def render(pages, out, kind_label, sheet_label):
    c = canvas.Canvas(str(out), pagesize=A4)
    c.setTitle(f"DE Lab {sheet_label} Cutouts")
    seq, total = 0, len(pages)
    for pno, page in enumerate(pages, 1):
        c.setFont("Sans", 7.5)
        c.setFillColor(GREY)
        c.drawString(BOX_X, PAGE_H - 0.8 * cm,
                     "A4 | Print at Actual size 100% (no 'fit to page') | Single-sided")
        c.setFillColor(black)
        c.setFont("Sans-Bold", 8)
        c.drawRightString(BOX_X + BOX_W, PAGE_H - 0.8 * cm,
                          f"{sheet_label} / Sheet {pno} of {total}")
        y = TOP
        scissors_line(c, y)
        for b in page:
            seq += 1
            draw_box(c, b, y, seq, kind_label)
            y -= b["h"]
            scissors_line(c, y)
        side_lines(c, TOP, y)
        c.setFont("Sans", 7.5)
        c.setFillColor(GREY)
        c.drawString(BOX_X, 0.8 * cm,
                     "✂ 1) cut down both long sides once  2) cut across each dashed line"
                     "  3) paste by the black number")
        c.drawRightString(BOX_X + BOX_W, 0.8 * cm, "Cutout width: 17 cm")
        c.setFillColor(black)
        c.showPage()
    c.save()
    return seq


def verilog_units(items):
    return [{"head": f"EXPERIMENT {it['exp']}",
             "sub": f"{it['exp_title']}  —  {it['title']}",
             "rows": it["rows"]} for it in items]


FIGURES = [
    ("fig-000.png", "2 to 4 decoder"),
    ("fig-001.png", "4:1 multiplexer"),
    ("fig-002.png", "Boolean function  F = A'BC + AB'C' + ABC"),
    ("fig-003.png", "Priority encoder with 7-segment display"),
    ("fig-004.png", "Logisim-evolution main window"),
]


def figure_units(fig_dir):
    from PIL import Image
    units, max_w, max_h = [], BOX_W - 2 * PAD, 10.5 * cm
    for i, (name, title) in enumerate(FIGURES, 1):
        path = str(Path(fig_dir) / name)
        w, h = Image.open(path).size
        s = min(max_w / w, max_h / h)
        units.append({"head": f"FIGURE {i}", "sub": title, "image": path,
                      "iw": w * s, "ih": h * s, "h": HEAD_H + h * s + PAD})
    return units


def main(src, fig_dir, out_dir):
    out_dir = Path(out_dir)
    n = render(paginate(verilog_units(parse_verilog(src))),
               out_dir / "DE_Verilog_Cutouts_A4.pdf", "VERILOG", "Verilog")
    m = render(paginate(figure_units(fig_dir)),
               out_dir / "DE_Logisim_Cutouts_A4.pdf", "LOGISIM", "Logisim")
    print(f"verilog cutouts: {n}, logisim cutouts: {m}, max chars/line: {MAX_CHARS}")


if __name__ == "__main__":
    main(*sys.argv[1:4])
