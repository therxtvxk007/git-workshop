"""Render PAPER.md into the published report page.

The report and the page are one document with two renderings, so the page is
generated rather than maintained. Editing the HTML by hand would let the two
drift, and a divergence between the report of record and the copy people
actually read is the sort of defect this project spends most of its effort
preventing elsewhere.

Usage:  python research/paper/build_report.py <source.md> <target.html>
"""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

import markdown

CSS = """
:root{
  --ground:#EDF0F3; --stock:#F7F9FA; --sunk:#E3E8ED; --panel:#E7ECF0;
  --ink:#0F141A; --ink-soft:#454F5A; --ink-faint:#6B7681;
  --rule:#C6CFD8; --rule-soft:#DBE2E8; --rule-strong:#8D9AA6;
  --limit:#8F5711; --verified:#1B6560;
  --serif:"Newsreader",Charter,Georgia,serif;
  --sans:"IBM Plex Sans","Helvetica Neue",Arial,sans-serif;
  --mono:"IBM Plex Mono",ui-monospace,Menlo,monospace;
  --measure:40rem;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --ground:#0B1015; --stock:#121920; --sunk:#161E26; --panel:#151D25;
  --ink:#DFE6EC; --ink-soft:#A3AEB9; --ink-faint:#7C8894;
  --rule:#2A343E; --rule-soft:#1E2831; --rule-strong:#485663;
  --limit:#D99B4E; --verified:#5FB5AC;
}}
:root[data-theme="dark"]{
  --ground:#0B1015; --stock:#121920; --sunk:#161E26; --panel:#151D25;
  --ink:#DFE6EC; --ink-soft:#A3AEB9; --ink-faint:#7C8894;
  --rule:#2A343E; --rule-soft:#1E2831; --rule-strong:#485663;
  --limit:#D99B4E; --verified:#5FB5AC;
}
*{box-sizing:border-box}
body{
  background:var(--ground); color:var(--ink);
  font-family:var(--serif); font-size:1.0313rem; line-height:1.66;
  margin:0; padding:0 1.5rem 6rem; -webkit-font-smoothing:antialiased;
}
.doc{max-width:var(--measure);margin:0 auto}

/* title block */
.titleblock{border-bottom:3px double var(--rule-strong);padding:3.5rem 0 1.5rem;margin-bottom:2rem}
.titleblock .kicker{
  font-family:var(--mono);font-size:.625rem;letter-spacing:.2em;text-transform:uppercase;
  color:var(--ink-faint);margin-bottom:1.5rem;padding-bottom:.75rem;
  border-bottom:1px solid var(--rule);
}
h1{
  font-family:var(--sans);font-weight:600;font-size:clamp(1.5rem,3.6vw,2.1rem);
  line-height:1.2;letter-spacing:-.016em;margin:0 0 1rem;text-wrap:balance;
}
.titleblock .sub{
  font-family:var(--mono);font-size:.6875rem;letter-spacing:.16em;text-transform:uppercase;
  color:var(--limit);
}

/* headings */
h2{
  font-family:var(--sans);font-weight:600;font-size:1.3125rem;line-height:1.25;
  letter-spacing:-.01em;margin:3.25rem 0 1.1rem;padding-top:.9rem;
  border-top:1px solid var(--rule-strong);text-wrap:balance;
}
h2 .n{font-family:var(--mono);font-weight:500;color:var(--ink-faint);margin-right:.6rem;font-size:.9em}
h3{
  font-family:var(--sans);font-weight:600;font-size:1rem;line-height:1.35;
  margin:2.1rem 0 .7rem;text-wrap:balance;
}
h3 .n{font-family:var(--mono);font-weight:500;color:var(--ink-faint);margin-right:.5rem;font-size:.92em}
h4{
  font-family:var(--mono);font-weight:500;font-size:.6875rem;letter-spacing:.12em;
  text-transform:uppercase;color:var(--ink-faint);margin:1.9rem 0 .6rem;
}
p{margin:0 0 .95rem;text-wrap:pretty}
strong{font-weight:600}
a{color:var(--limit)}
hr{border:none;border-top:1px solid var(--rule-soft);margin:2.25rem 0}
ul,ol{margin:0 0 1.05rem;padding-left:1.4rem}
li{margin-bottom:.4rem}
li::marker{color:var(--ink-faint)}

/* blockquote = formal extract */
blockquote{
  margin:1.5rem 0;padding:1rem 1.3rem;background:var(--stock);
  border-left:3px solid var(--limit);font-size:1rem;line-height:1.55;
}
blockquote p{margin:0}
blockquote p+p{margin-top:.75rem}

/* tables */
.tw{overflow-x:auto;margin:1.5rem 0;border:1px solid var(--rule)}
table{border-collapse:collapse;width:100%;font-family:var(--sans);font-size:.8125rem;
  line-height:1.45;background:var(--stock)}
th{font-family:var(--mono);font-size:.5938rem;letter-spacing:.1em;text-transform:uppercase;
  font-weight:500;color:var(--ink-faint);text-align:left;padding:.65rem .8rem;
  border-bottom:1px solid var(--rule-strong);vertical-align:bottom}
td{padding:.65rem .8rem;border-bottom:1px solid var(--rule-soft);vertical-align:top;
  font-variant-numeric:tabular-nums}
tr:last-child td{border-bottom:none}
td strong{color:var(--limit)}

/* code */
code{font-family:var(--mono);font-size:.84em;background:var(--sunk);padding:.1em .32em;border-radius:2px}
pre{font-family:var(--mono);font-size:.7813rem;line-height:1.6;background:var(--stock);
  border:1px solid var(--rule);padding:.95rem 1.1rem;overflow-x:auto;margin:1.4rem 0}
pre code{background:none;padding:0;font-size:inherit}

/* executive summary + toc panels */
.panel{background:var(--panel);border:1px solid var(--rule);padding:1.4rem 1.6rem;margin:1.75rem 0}
.panel h2{margin-top:0;border-top:none;padding-top:0}
.toc ol{list-style:none;padding-left:0;counter-reset:toc}
.toc li{counter-increment:toc;font-family:var(--sans);font-size:.875rem;margin-bottom:.3rem}
.toc li::before{content:counter(toc) ".";font-family:var(--mono);font-size:.75rem;
  color:var(--ink-faint);display:inline-block;min-width:1.7rem}
.toc a{color:var(--ink);text-decoration:none;border-bottom:1px solid transparent}
.toc a:hover,.toc a:focus-visible{border-bottom-color:var(--limit);color:var(--limit)}

:focus-visible{outline:2px solid var(--limit);outline-offset:2px}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
@media (max-width:640px){body{padding:0 1.1rem 4rem;font-size:1rem}}
"""

TITLE = "The Open-Source Ceiling"
SUBTITLE = "Technical Report &middot; Version 1.0 &middot; Draft for review"


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def build(source: Path, target: Path) -> None:
    raw = source.read_text(encoding="utf-8")

    # The H1 and the immediately following "## Technical Report" marker become
    # the title block, so drop them from the flowed body.
    lines = raw.splitlines()
    heading = next(i for i, line in enumerate(lines) if line.startswith("# "))
    doc_title = lines[heading][2:].strip()
    body_lines = lines[heading + 1 :]
    body_lines = [line for line in body_lines if line.strip() != "## Technical Report"]
    body_md = "\n".join(body_lines).lstrip("\n-").lstrip()

    body = markdown.markdown(
        body_md,
        extensions=["tables", "fenced_code", "sane_lists"],
        output_format="html5",
    )

    # Anchor every H2 and split its leading clause number for typographic
    # treatment; the numbering is content, so it is marked up rather than faked
    # with a counter that could drift from the source.
    def h2(match: re.Match[str]) -> str:
        inner = match.group(1)
        anchor = slugify(re.sub(r"<[^>]+>", "", inner))
        num = re.match(r"^((?:\d+\.|Appendix [A-Z]\s*&mdash;|Appendix [A-Z]))\s*(.*)$", inner)
        if num:
            inner = f'<span class="n">{num.group(1)}</span>{num.group(2)}'
        return f'<h2 id="{anchor}">{inner}</h2>'

    body = re.sub(r"<h2>(.*?)</h2>", h2, body, flags=re.S)

    def h3(match: re.Match[str]) -> str:
        inner = match.group(1)
        num = re.match(r"^(\d+\.\d+(?:\.\d+)?)\s+(.*)$", inner)
        if num:
            inner = f'<span class="n">{num.group(1)}</span>{num.group(2)}'
        return f"<h3>{inner}</h3>"

    body = re.sub(r"<h3>(.*?)</h3>", h3, body, flags=re.S)

    # Wide content scrolls in its own container, never the page body.
    body = re.sub(r"<table>", '<div class="tw"><table>', body)
    body = re.sub(r"</table>", "</table></div>", body)

    # Executive summary and contents read as front matter, so each is panelled.
    # Each panel is opened and closed in a single substitution: wrapping both
    # first and closing them afterwards places the first close inside the
    # second panel, which leaves it open and unbalances the document.
    def panel(body_html: str, anchor: str, extra: str = "") -> str:
        pattern = re.compile(
            rf'(<h2 id="{anchor}">.*?)(?=<h2 id=)',
            flags=re.S,
        )
        cls = f"panel {extra}".strip()
        return pattern.sub(rf'<div class="{cls}">\1</div>', body_html, count=1)

    body = panel(body, "executive-summary")
    body = panel(body, "table-of-contents", "toc")

    page = (
        f"<title>{html.escape(TITLE)}</title>\n"
        '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
        "family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&"
        'family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;1,6..72,400&display=swap">\n'
        f"<style>{CSS}</style>\n"
        '<div class="doc">\n'
        '<header class="titleblock">\n'
        '<div class="kicker">Centre-scale event forecasting &middot; Unclassified</div>\n'
        f"<h1>{html.escape(doc_title)}</h1>\n"
        f'<div class="sub">{SUBTITLE}</div>\n'
        "</header>\n"
        f"{body}\n</div>\n"
    )
    target.write_text(page, encoding="utf-8")
    print(f"wrote {target} ({len(page):,} bytes)")


if __name__ == "__main__":
    build(Path(sys.argv[1]), Path(sys.argv[2]))
