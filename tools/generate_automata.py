#!/usr/bin/env python3
"""Draw every automaton in the PCCST302 Series Exam 1 solved paper as an SVG state diagram.

Each machine is declared once, as a transition function.  Both the diagram and the
transition table shown on the index page are derived from that single declaration,
so a diagram can never drift away from its table.

Usage:  python3 tools/generate_automata.py
Output: automata/*.svg  (standalone, theme aware) and automata/index.html
"""

import html
import math
import os

R = 26                 # state radius
ACCEPT_GAP = 5         # gap between the two rings of an accepting state
HEADER_H = 58          # space reserved for the caption in a standalone SVG
FONT = ("ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, "
        "'Helvetica Neue', Arial, sans-serif")
FONT_MONO = ("ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, "
             "'Liberation Mono', monospace")
FONT_SERIF = "ui-serif, Georgia, 'Iowan Old Style', 'Times New Roman', serif"

INK = "var(--auto-ink, #14161a)"
MUTED = "var(--auto-muted, #5d6472)"
ACCENT = "var(--auto-accent, #b4530a)"
BG = "var(--auto-bg, #ffffff)"

SVG_STYLE = """
  svg.automaton{--auto-ink:#14161a;--auto-muted:#5d6472;--auto-accent:#b4530a;--auto-bg:#ffffff}
  @media (prefers-color-scheme: dark){
    svg.automaton{--auto-ink:#e8eaf0;--auto-muted:#98a1b3;--auto-accent:#f0a65c;--auto-bg:#101319}
  }
"""


def esc(s):
    return html.escape(str(s), quote=True)


def unit(dx, dy):
    n = math.hypot(dx, dy) or 1.0
    return dx / n, dy / n


def arrowhead(x, y, dx, dy, color, size=11.0, half=4.7):
    ux, uy = unit(dx, dy)
    px, py = -uy, ux
    bx, by = x - size * ux, y - size * uy
    pts = f"{x:.1f},{y:.1f} {bx + half * px:.1f},{by + half * py:.1f} {bx - half * px:.1f},{by - half * py:.1f}"
    return f'<polygon points="{pts}" fill="{color}"/>'


def text(x, y, s, size, color, weight=400, anchor="middle", halo=True, opacity=None,
         family=FONT):
    knock = (f' stroke="{BG}" stroke-width="4.5" stroke-linejoin="round"'
             f' paint-order="stroke fill"' if halo else "")
    op = f' opacity="{opacity}"' if opacity else ""
    return (f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" font-family="{family}" '
            f'font-size="{size}" font-weight="{weight}" fill="{color}"{knock}{op} '
            f'dominant-baseline="central">{esc(s)}</text>')


class Machine:
    """One automaton: states, a transition function, and hand-placed coordinates."""

    def __init__(self, key, title, kind, blurb, alphabet, start, accept, delta, pos,
                 size, notes=None, curves=None, loops=None, labside=None,
                 start_dir=(-1, 0), nondet=False, footnote=None, note_above=(), labt=None, note_off=None):
        self.key = key
        self.title = title
        self.kind = kind
        self.blurb = blurb
        self.alphabet = list(alphabet)
        self.start = start
        self.accept = set(accept)
        self.delta = delta
        self.pos = pos
        self.w, self.h = size
        self.notes = notes or {}
        self.curves = curves or {}
        self.loops = loops or {}
        self.labside = labside or {}
        self.labt = labt or {}
        self.start_dir = start_dir
        self.nondet = nondet
        self.footnote = footnote
        self.note_above = set(note_above)
        self.note_off = note_off or {}
        self.has_eps = any("ε" in row for row in delta.values())
        self.columns = self.alphabet + (["ε"] if self.has_eps else [])

    # -- transition helpers -------------------------------------------------
    def targets(self, state, sym):
        d = self.delta.get(state, {}).get(sym)
        if d is None:
            return []
        return list(d) if isinstance(d, (list, tuple, set)) else [d]

    def grouped_edges(self):
        """{(src, dst): 'a, b'} with the symbols in alphabet order."""
        agg = {}
        for state in self.delta:
            for sym in self.columns:
                for dst in self.targets(state, sym):
                    agg.setdefault((state, dst), []).append(sym)
        return agg

    # -- drawing ------------------------------------------------------------
    def _edge(self, a, b, label):
        (x1, y1), (x2, y2) = self.pos[a], self.pos[b]
        curve = self.curves.get((a, b), 0.0)
        dx, dy = x2 - x1, y2 - y1
        ux, uy = unit(dx, dy)
        px, py = -uy, ux
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        cx, cy = mx + px * 2 * curve, my + py * 2 * curve

        sx_u, sy_u = unit(cx - x1, cy - y1)
        ex_u, ey_u = unit(cx - x2, cy - y2)
        sx, sy = x1 + R * sx_u, y1 + R * sy_u
        ex, ey = x2 + R * ex_u, y2 + R * ey_u

        out = [f'<path d="M{sx:.1f},{sy:.1f} Q{cx:.1f},{cy:.1f} {ex:.1f},{ey:.1f}" '
               f'fill="none" stroke="{INK}" stroke-width="1.7" opacity="0.85"/>',
               arrowhead(ex, ey, ex - cx, ey - cy, INK)]

        side = self.labside.get((a, b), 1 if curve >= 0 else -1)
        t = self.labt.get((a, b), 0.5)
        w0, w1, w2 = (1 - t) ** 2, 2 * t * (1 - t), t ** 2
        lx = w0 * x1 + w1 * cx + w2 * x2 + px * side * 14
        ly = w0 * y1 + w1 * cy + w2 * y2 + py * side * 14
        out.append(text(lx, ly, label, 13, INK, weight=500, family=FONT_MONO))
        return "".join(out)

    def _loop(self, state, label):
        x, y = self.pos[state]
        ang = math.radians(self.loops.get(state, -90))
        spread, reach = math.radians(20), R + 46

        def polar(a, r):
            return x + r * math.cos(a), y + r * math.sin(a)

        p1 = polar(ang - spread, R)
        p2 = polar(ang + spread, R)
        c1 = polar(ang - spread * 1.7, reach)
        c2 = polar(ang + spread * 1.7, reach)
        lab = polar(ang, R + 40)
        return "".join([
            f'<path d="M{p1[0]:.1f},{p1[1]:.1f} C{c1[0]:.1f},{c1[1]:.1f} '
            f'{c2[0]:.1f},{c2[1]:.1f} {p2[0]:.1f},{p2[1]:.1f}" fill="none" '
            f'stroke="{INK}" stroke-width="1.7" opacity="0.85"/>',
            arrowhead(p2[0], p2[1], p2[0] - c2[0], p2[1] - c2[1], INK),
            text(lab[0], lab[1], label, 13, INK, weight=500, family=FONT_MONO),
        ])

    def _node(self, state):
        x, y = self.pos[state]
        out = []
        if state == self.start:
            dx, dy = unit(*self.start_dir)
            tip = (x + dx * (R + 7), y + dy * (R + 7))
            tail = (x + dx * (R + 40), y + dy * (R + 40))
            out.append(f'<line x1="{tail[0]:.1f}" y1="{tail[1]:.1f}" x2="{tip[0]:.1f}" '
                       f'y2="{tip[1]:.1f}" stroke="{ACCENT}" stroke-width="2"/>')
            out.append(arrowhead(tip[0], tip[1], tip[0] - tail[0], tip[1] - tail[1], ACCENT))
        out.append(f'<circle cx="{x}" cy="{y}" r="{R}" fill="{BG}" stroke="{INK}" stroke-width="1.9"/>')
        if state in self.accept:
            out.append(f'<circle cx="{x}" cy="{y}" r="{R - ACCEPT_GAP}" fill="none" '
                       f'stroke="{ACCENT}" stroke-width="1.9"/>')
        size = 14.5 if len(state) <= 2 else (12.5 if len(state) == 3 else 11)
        out.append(text(x, y, state, size, INK, weight=600, halo=False,
                        family=FONT_MONO))
        note = self.notes.get(state)
        if note:
            lines = [ln.strip() for ln in note.split("|")]
            # keep the caption clear of a self-loop drawn on the same side
            above = state in self.note_above or 30 <= self.loops.get(state, -90) <= 150
            top = (y - R - 16 - (len(lines) - 1) * 13) if above else (y + R + 16)
            nx, ny = self.note_off.get(state, (0, 0))
            for i, line in enumerate(lines):
                out.append(text(x + nx, top + ny + i * 13, line, 10.5, MUTED, halo=True))
        return "".join(out)

    # -- automatic framing --------------------------------------------------
    def _extent(self, pts):
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)

    def bbox(self):
        """Bounding box of everything drawn, so the canvas can be framed to fit."""
        pts = []
        for state, (x, y) in self.pos.items():
            rr = R + 3
            pts += [(x - rr, y - rr), (x + rr, y + rr)]
            if state == self.start:
                dx, dy = unit(*self.start_dir)
                pts.append((x + dx * (R + 44) - 6, y + dy * (R + 44) - 6))
                pts.append((x + dx * (R + 44) + 6, y + dy * (R + 44) + 6))
            note = self.notes.get(state)
            if note:
                lines = [ln.strip() for ln in note.split("|")]
                above = state in self.note_above or 30 <= self.loops.get(state, -90) <= 150
                top = (y - R - 16 - (len(lines) - 1) * 13) if above else (y + R + 16)
                nx, ny = self.note_off.get(state, (0, 0))
                half = max(len(ln) for ln in lines) * 2.9 + 4
                pts += [(x + nx - half, top + ny - 8),
                        (x + nx + half, top + ny + (len(lines) - 1) * 13 + 8)]
        for (a, b), syms in self.grouped_edges().items():
            label = ", ".join(syms)
            half = len(label) * 3.9 + 4
            if a == b:
                x, y = self.pos[a]
                ang = math.radians(self.loops.get(a, -90))
                lx, ly = x + (R + 40) * math.cos(ang), y + (R + 40) * math.sin(ang)
                pts += [(x + (R + 52) * math.cos(ang) - 6, y + (R + 52) * math.sin(ang) - 6),
                        (x + (R + 52) * math.cos(ang) + 6, y + (R + 52) * math.sin(ang) + 6),
                        (lx - half, ly - 9), (lx + half, ly + 9)]
                continue
            (x1, y1), (x2, y2) = self.pos[a], self.pos[b]
            curve = self.curves.get((a, b), 0.0)
            px, py = (lambda u: (-u[1], u[0]))(unit(x2 - x1, y2 - y1))
            cx = (x1 + x2) / 2 + px * 2 * curve
            cy = (y1 + y2) / 2 + py * 2 * curve
            side = self.labside.get((a, b), 1 if curve >= 0 else -1)
            t = self.labt.get((a, b), 0.5)
            w0, w1, w2 = (1 - t) ** 2, 2 * t * (1 - t), t ** 2
            lx = w0 * x1 + w1 * cx + w2 * x2 + px * side * 14
            ly = w0 * y1 + w1 * cy + w2 * y2 + py * side * 14
            # a quadratic curve stays inside the triangle P0-C-P2, so C bounds it
            pts += [(cx, cy), (lx - half, ly - 9), (lx + half, ly + 9)]
        return self._extent(pts)

    def frame(self, standalone):
        """Canvas size and the offset that centres the drawing inside it."""
        margin = 26
        x0, y0, x1, y1 = self.bbox()
        w = x1 - x0 + 2 * margin
        h = y1 - y0 + 2 * margin
        if standalone:
            w = max(w, len(self.title) * 8.6 + 44,
                    (len(self.kind) + len(self.blurb) + 3) * 6.2 + 44)
        return round(w), round(h), margin - x0, margin - y0

    def body(self):
        parts = []
        for (a, b), syms in self.grouped_edges().items():
            label = ", ".join(syms)
            parts.append(self._loop(a, label) if a == b else self._edge(a, b, label))
        for state in self.delta:
            parts.append(self._node(state))
        return "".join(parts)

    def svg(self, standalone=True):
        w, h, dx, dy = self.frame(standalone)
        top = HEADER_H if standalone else 0
        head = (f'<svg xmlns="http://www.w3.org/2000/svg" class="automaton" '
                f'viewBox="0 0 {w} {h + top}" width="{w}" height="{h + top}" '
                f'role="img" aria-label="{esc(self.title)}">')
        if standalone:
            head += (f'<style>{SVG_STYLE}</style>'
                     f'<rect width="100%" height="100%" fill="{BG}"/>'
                     + text(22, 26, self.title, 16.5, INK, weight=600, anchor="start",
                            halo=False, family=FONT_SERIF)
                     + text(22, 47, f"{self.kind} · {self.blurb}", 12, MUTED,
                            anchor="start", halo=False))
        return (f'{head}<g transform="translate({dx:.1f},{dy + top:.1f})">'
                f'{self.body()}</g></svg>')

    # -- transition table ---------------------------------------------------
    def table_html(self):
        head = "".join(f'<th scope="col" class="sym">{esc(c)}</th>' for c in self.columns)
        rows = []
        for state in self.delta:
            mark = ("→ " if state == self.start else "") + ("∗ " if state in self.accept else "")
            cells = []
            for sym in self.columns:
                tgt = self.targets(state, sym)
                if self.nondet:
                    cell = "{" + ", ".join(tgt) + "}" if tgt else "∅"
                else:
                    cell = tgt[0] if tgt else "∅"
                cells.append(f"<td>{esc(cell)}</td>")
            note = self.notes.get(state, "").replace("|", " ")
            cls = ' class="acc"' if state in self.accept else ""
            rows.append(f'<tr{cls}><th scope="row"><span class="mk">{esc(mark)}</span>'
                        f'{esc(state)}</th>{"".join(cells)}'
                        f'<td class="mean">{esc(note)}</td></tr>')
        return ('<table class="delta"><thead><tr><th scope="col">state</th>' + head +
                '<th scope="col">meaning</th></tr></thead><tbody>' +
                "".join(rows) + "</tbody></table>")


# ---------------------------------------------------------------------------
# Q1  product of symbols modulo 7
# ---------------------------------------------------------------------------
def hexa(center, r_out, r_in):
    cx, cy = center
    p = {}
    for name, ang, r in [("q1", -90, r_out), ("q3", -30, r_in), ("q2", 30, r_out),
                         ("q6", 90, r_in), ("q4", 150, r_out), ("q5", 210, r_in)]:
        a = math.radians(ang)
        p[name] = (round(cx + r * math.cos(a), 1), round(cy + r * math.sin(a), 1))
    return p


_q1_pos = hexa((400, 320), 215, 108)
# symbol 3 walks the outer/inner ring, 2 is a +2 step, 4 is a -2 step
_q1_cw = [("q1", "q2"), ("q2", "q4"), ("q4", "q1")]       # outer triangle, symbol 2
_q1_ccw = [("q2", "q1"), ("q4", "q2"), ("q1", "q4")]      # outer triangle, symbol 4
_q1_curves = {e: -52 for e in _q1_cw}
_q1_curves.update({e: 88 for e in _q1_ccw})
_q1_curves.update({("q3", "q6"): 22, ("q6", "q5"): 22, ("q5", "q3"): 22,
                   ("q6", "q3"): 22, ("q5", "q6"): 22, ("q3", "q5"): 22})

Q1 = Machine(
    key="q1-product-mod-7",
    title="Q1 · Product of symbols ≡ 2 (mod 7)",
    kind="Minimal DFA · 6 states",
    blurb="state qr = product read so far is r mod 7; Σ = {1,2,3,4}",
    alphabet=["1", "2", "3", "4"],
    start="q1", accept={"q2"},
    delta={f"q{r}": {s: f"q{(r * int(s)) % 7}" for s in "1234"} for r in range(1, 7)},
    pos=_q1_pos, size=(800, 560), curves=_q1_curves,
    loops={"q1": -60, "q2": 30, "q4": 150, "q3": -30, "q6": 90, "q5": 210},
    start_dir=(-1, -0.55),
    footnote="Laid out so that symbol 3 (a generator of the group) walks one step around the "
             "ring, symbol 2 jumps two steps forward and symbol 4 two steps back. Every "
             "non-zero residue is invertible mod 7, so all six states are distinguishable.",
)

# ---------------------------------------------------------------------------
# Q2  #01 = #10
# ---------------------------------------------------------------------------
Q2 = Machine(
    key="q2-equal-01-10",
    title="Q2 · #01 = #10",
    kind="Minimal DFA · 5 states",
    blurb="accepts ε and every word whose first and last symbol agree",
    alphabet=["0", "1"],
    start="S", accept={"S", "A", "C"},
    delta={"S": {"0": "A", "1": "C"},
           "A": {"0": "A", "1": "B"},
           "B": {"0": "A", "1": "B"},
           "C": {"0": "D", "1": "C"},
           "D": {"0": "D", "1": "C"}},
    pos={"S": (120, 230), "A": (350, 120), "B": (600, 120),
         "C": (350, 350), "D": (600, 350)},
    size=(760, 500),
    notes={"S": "empty word", "A": "first 0, last 0", "B": "first 0, last 1",
           "C": "first 1, last 1", "D": "first 1, last 0"},
    curves={("A", "B"): 22, ("B", "A"): 22, ("C", "D"): 22, ("D", "C"): 22},
    loops={"A": -90, "B": -90, "C": 90, "D": 90},
    footnote="Σ(xi₊₁ − xi) = xₙ − x₁ = #01 − #10, so the two counts agree exactly when the "
             "first and last symbols are equal.",
)

# ---------------------------------------------------------------------------
# Q4  the photographed ε-NFA
# ---------------------------------------------------------------------------
Q4 = Machine(
    key="q4-epsilon-nfa",
    title="Q4 · ε-NFA used for δ̂(q2, aaaabbbaaab)",
    kind="ε-NFA · 4 states",
    blurb="the machine decoded from the photographed table",
    alphabet=["a", "b"],
    start="q0", accept=set(),
    delta={"q0": {"a": ["q1"]},
           "q1": {"a": ["q0"], "b": ["q2"]},
           "q2": {"b": ["q3"], "ε": ["q1"]},
           "q3": {"b": ["q3"]}},
    pos={"q0": (120, 160), "q1": (350, 160), "q2": (580, 160), "q3": (810, 160)},
    size=(920, 260), nondet=True,
    curves={("q0", "q1"): 24, ("q1", "q0"): 24, ("q1", "q2"): 24, ("q2", "q1"): 24},
    loops={"q3": -90},
    footnote="Starting from E({q2}) = {q1,q2}: a→{q0}, a→{q1}, a→{q0}, a→{q1}, b→{q1,q2}, "
             "b→{q1,q2,q3}, b→{q1,q2,q3}, a→{q0}, a→{q1}, a→{q0}, b→∅. "
             "The paper fixes no accepting set, so no state is ringed here.",
)

# ---------------------------------------------------------------------------
# Q5(a)  binary value divisible by 4
# ---------------------------------------------------------------------------
Q5A = Machine(
    key="q5a-divisible-by-4",
    title="Q5(a) · Binary value divisible by 4",
    kind="Minimal DFA · 3 states",
    blurb="non-empty binary strings whose value is ≡ 0 (mod 4)",
    alphabet=["0", "1"],
    start="A", accept={"B"},
    delta={"A": {"0": "B", "1": "C"},
           "B": {"0": "B", "1": "C"},
           "C": {"0": "A", "1": "C"}},
    pos={"A": (150, 320), "B": (420, 140), "C": (690, 320)},
    size=(840, 460),
    notes={"A": "start or remainder 2", "B": "non-empty remainder 0", "C": "remainder 1 or 3"},
    note_above=["B"], note_off={"B": (0, -76)},
    loops={"B": -90, "C": 0},
    labside={("A", "C"): 1},
    footnote="If your teacher counts ε itself as the integer 0, make the remainder-0 state the "
             "start state as well; the minimum is still 3 states.",
)

# ---------------------------------------------------------------------------
# Q5(b)  #1 ≡ 0 (mod 4) and #0 odd
# ---------------------------------------------------------------------------
_q5b_delta, _q5b_pos, _q5b_curves = {}, {}, {}
for i in range(4):
    for j in range(2):
        s = f"q{i}{j}"
        _q5b_delta[s] = {"0": f"q{i}{1 - j}", "1": f"q{(i + 1) % 4}{j}"}
        _q5b_pos[s] = (150 + i * 190, 150 + j * 250)
        _q5b_curves[(s, f"q{i}{1 - j}")] = 20
_q5b_curves[("q30", "q00")] = 95
_q5b_curves[("q31", "q01")] = -95

Q5B = Machine(
    key="q5b-ones-mod4-zeros-odd",
    title="Q5(b) · #1 ≡ 0 (mod 4) and #0 odd",
    kind="Minimal DFA · 8 states",
    blurb="product of a mod-4 counter for 1s and a parity counter for 0s",
    alphabet=["0", "1"],
    start="q00", accept={"q01"},
    delta=_q5b_delta, pos=_q5b_pos, size=(880, 580),
    curves=_q5b_curves,
    notes={f"q{i}{j}": f"#1≡{i}, #0 {'odd' if j else 'even'}" for i in range(4) for j in range(2)},
    note_above=[f"q{i}0" for i in range(4)],
    footnote="qij stores i = #1 mod 4 and j = #0 mod 2. Reading 1 steps the row counter, "
             "reading 0 flips the column. It is a group counter, so every state can be driven "
             "to (0,1) by a unique suffix pattern — all eight are distinguishable.",
)

# ---------------------------------------------------------------------------
# Q5(c)  no occurrence of aa
# ---------------------------------------------------------------------------
Q5C = Machine(
    key="q5c-avoid-aa",
    title="Q5(c) · Strings that do not contain aa",
    kind="Minimal DFA · 3 states",
    blurb="the trap state is unavoidable: once aa appears no suffix repairs it",
    alphabet=["a", "b"],
    start="N", accept={"N", "A"},
    delta={"N": {"a": "A", "b": "N"},
           "A": {"a": "D", "b": "N"},
           "D": {"a": "D", "b": "D"}},
    pos={"N": (150, 185), "A": (420, 185), "D": (690, 185)},
    size=(840, 325),
    notes={"N": "safe, last symbol ≠ a", "A": "safe, last symbol a", "D": "aa has occurred"},
    curves={("N", "A"): 24, ("A", "N"): 24},
    loops={"N": -90, "D": -90},
)

# ---------------------------------------------------------------------------
# Q5(d)  starts and ends with the same symbol
# ---------------------------------------------------------------------------
Q5D_NFA = Machine(
    key="q5d-same-first-last-nfa",
    title="Q5(d) · Starts and ends with the same symbol — NFA",
    kind="NFA · 4 states",
    blurb="remember the first symbol, scan freely, guess the last symbol",
    alphabet=["a", "b"],
    start="S", accept={"F"}, nondet=True,
    delta={"S": {"a": ["A", "F"], "b": ["B", "F"]},
           "A": {"a": ["A", "F"], "b": ["A"]},
           "B": {"a": ["B"], "b": ["B", "F"]},
           "F": {}},
    pos={"S": (130, 250), "A": (400, 120), "B": (400, 380), "F": (700, 250)},
    size=(840, 520),
    notes={"S": "nothing read", "A": "first symbol a", "B": "first symbol b",
           "F": "guessed the last symbol"},
    loops={"A": -90, "B": 90},
    labside={("S", "F"): -1},
    footnote="F has no outgoing transition, so the guess only survives if the guessed symbol "
             "really was the last one. Single-symbol words are accepted through S → F.",
)

Q5D_DFA = Machine(
    key="q5d-same-first-last-dfa",
    title="Q5(d) · Starts and ends with the same symbol — minimal DFA",
    kind="Minimal DFA · 5 states",
    blurb="after the first input, remember the pair (first, last)",
    alphabet=["a", "b"],
    start="S", accept={"AA", "BB"},
    delta={"S": {"a": "AA", "b": "BB"},
           "AA": {"a": "AA", "b": "AB"},
           "AB": {"a": "AA", "b": "AB"},
           "BB": {"a": "BA", "b": "BB"},
           "BA": {"a": "BA", "b": "BB"}},
    pos={"S": (130, 250), "AA": (410, 120), "AB": (690, 120),
         "BB": (410, 380), "BA": (690, 380)},
    size=(840, 520),
    notes={"S": "no symbol yet", "AA": "first a, last a", "AB": "first a, last b",
           "BB": "first b, last b", "BA": "first b, last a"},
    curves={("AA", "AB"): 22, ("AB", "AA"): 22, ("BB", "BA"): 22, ("BA", "BB"): 22},
    loops={"AA": -90, "AB": -90, "BB": 90, "BA": 90},
)

# ---------------------------------------------------------------------------
# Q6(a)  ends with 01
# ---------------------------------------------------------------------------
Q6A = Machine(
    key="q6a-ends-with-01",
    title="Q6(a) · Strings ending with 01",
    kind="Minimal DFA · 3 states",
    blurb="state = longest suffix of the input that is a prefix of 01",
    alphabet=["0", "1"],
    start="S", accept={"F"},
    delta={"S": {"0": "Z", "1": "S"},
           "Z": {"0": "Z", "1": "F"},
           "F": {"0": "Z", "1": "S"}},
    pos={"S": (150, 185), "Z": (420, 185), "F": (690, 185)},
    size=(840, 340),
    notes={"S": "no useful suffix", "Z": "suffix 0", "F": "suffix 01"},
    curves={("Z", "F"): 22, ("F", "Z"): 22, ("F", "S"): -74},
    loops={"S": -90, "Z": -90},
)

# ---------------------------------------------------------------------------
# Q6(b)  exactly two a symbols
# ---------------------------------------------------------------------------
Q6B = Machine(
    key="q6b-exactly-two-a",
    title="Q6(b) · Exactly two a symbols",
    kind="Minimal DFA · 4 states",
    blurb="count a symbols, then trap on the third",
    alphabet=["a", "b"],
    start="q0", accept={"q2"},
    delta={"q0": {"a": "q1", "b": "q0"},
           "q1": {"a": "q2", "b": "q1"},
           "q2": {"a": "D", "b": "q2"},
           "D": {"a": "D", "b": "D"}},
    pos={"q0": (140, 175), "q1": (370, 175), "q2": (600, 175), "D": (830, 175)},
    size=(960, 315),
    notes={"q0": "0 a symbols", "q1": "1 a symbol", "q2": "exactly 2 a symbols",
           "D": "at least 3 a symbols"},
    loops={"q0": -90, "q1": -90, "q2": -90, "D": -90},
)

# ---------------------------------------------------------------------------
# Q6(c)  aⁿbᵐcᵖd^q with n+m even and p+q odd
# ---------------------------------------------------------------------------
Q6C_NFA = Machine(
    key="q6c-blocks-enfa",
    title="Q6(c) · aⁿbᵐcᵖd^q, n+m even, p+q odd — ε-NFA",
    kind="ε-NFA · 8 states",
    blurb="one parity bit per phase; ε-edges change phase without reading input",
    alphabet=["a", "b", "c", "d"],
    start="A0", accept={"D1"}, nondet=True,
    delta={"A0": {"a": ["A1"], "ε": ["B0"]},
           "A1": {"a": ["A0"], "ε": ["B1"]},
           "B0": {"b": ["B1"], "ε": ["C0"]},
           "B1": {"b": ["B0"]},
           "C0": {"c": ["C1"], "ε": ["D0"]},
           "C1": {"c": ["C0"], "ε": ["D1"]},
           "D0": {"d": ["D1"]},
           "D1": {"d": ["D0"]}},
    pos={"A0": (150, 150), "B0": (400, 150), "C0": (650, 150), "D0": (900, 150),
         "A1": (150, 390), "B1": (400, 390), "C1": (650, 390), "D1": (900, 390)},
    size=(1040, 530),
    note_above=["A0", "B0", "C0", "D0"],
    notes={"A0": "in a, total even", "A1": "in a, total odd",
           "B0": "in b, n+m even", "B1": "in b, n+m odd",
           "C0": "in c, p+q even", "C1": "in c, p+q odd",
           "D0": "in d, p+q even", "D1": "in d, p+q odd"},
    curves={("A0", "A1"): 22, ("A1", "A0"): 22, ("B0", "B1"): 22, ("B1", "B0"): 22,
            ("C0", "C1"): 22, ("C1", "C0"): 22, ("D0", "D1"): 22, ("D1", "D0"): 22},
    footnote="C may only be entered from B0, because n+m must already be even. C1 −ε→ D1 lets "
             "a word with q = 0 and odd p be accepted, and the other ε-moves let any block be "
             "empty whenever the parity gates allow it.",
)

Q6C_DFA = Machine(
    key="q6c-blocks-dfa",
    title="Q6(c) · aⁿbᵐcᵖd^q, n+m even, p+q odd — equivalent DFA",
    kind="DFA · 9 states incl. trap",
    blurb="subset construction; each label is the ε-closed subset it stands for",
    alphabet=["a", "b", "c", "d"],
    start="A0", accept={"C1", "D1"},
    delta={"A0": {"a": "A1", "b": "B1", "c": "C1", "d": "D1"},
           "A1": {"a": "A0", "b": "B0", "c": "X", "d": "X"},
           "B0": {"a": "X", "b": "B1", "c": "C1", "d": "D1"},
           "B1": {"a": "X", "b": "B0", "c": "X", "d": "X"},
           "C0": {"a": "X", "b": "X", "c": "C1", "d": "D1"},
           "C1": {"a": "X", "b": "X", "c": "C0", "d": "D0"},
           "D0": {"a": "X", "b": "X", "c": "X", "d": "D1"},
           "D1": {"a": "X", "b": "X", "c": "X", "d": "D0"},
           "X": {"a": "X", "b": "X", "c": "X", "d": "X"}},
    pos={"A0": (150, 140), "B0": (400, 140), "C0": (650, 140), "D0": (900, 140),
         "A1": (150, 410), "B1": (400, 410), "C1": (650, 410), "D1": (900, 410),
         "X": (525, 680)},
    size=(1060, 790),
    notes={"A0": "{A0,B0,C0,D0}", "A1": "{A1,B1}", "B0": "{B0,C0,D0}", "B1": "{B1}",
           "C0": "{C0,D0}", "C1": "{C1,D1}", "D0": "{D0}", "D1": "{D1}", "X": "∅ — trap"},
    note_above=["A0", "B0", "C0", "D0"],
    curves={("A0", "A1"): 22, ("A1", "A0"): 22, ("B0", "B1"): 22, ("B1", "B0"): 22,
            ("C0", "C1"): 22, ("C1", "C0"): 22, ("D0", "D1"): 22, ("D1", "D0"): 22,
            ("B0", "X"): -60, ("C0", "X"): 70, ("D0", "X"): 96, ("A1", "X"): -34,
            ("B1", "X"): -14, ("C1", "X"): 30, ("D1", "X"): 40},
    labt={("A0", "C1"): 0.35, ("A0", "D1"): 0.35, ("B0", "C1"): 0.35, ("B0", "D1"): 0.35,
          ("C0", "D1"): 0.35, ("A1", "B0"): 0.35, ("C1", "D0"): 0.35, ("A0", "B1"): 0.4,
          ("C0", "X"): 0.62, ("D0", "X"): 0.68, ("B0", "X"): 0.6},
    loops={"X": 0},
    footnote="C1 and D1 are final because their subsets contain the ε-NFA final state D1. "
             "Sanity checks: c is accepted (0 even, 1 odd), abd is accepted, cd is rejected "
             "(p+q = 2), abbd is rejected (n+m = 3).",
)

# ---------------------------------------------------------------------------
# Q7(a)  minimise the photographed 8-state DFA
# ---------------------------------------------------------------------------
Q7A_ORIG = Machine(
    key="q7a-original-dfa",
    title="Q7(a) · The photographed DFA before minimisation",
    kind="DFA · 8 states",
    blurb="p is both start and final; u, w are final sinks; t, v are non-final sinks",
    alphabet=["a", "b"],
    start="p", accept={"p", "u", "w"},
    delta={"p": {"a": "t", "b": "q"},
           "q": {"a": "r", "b": "u"},
           "r": {"a": "s", "b": "v"},
           "s": {"a": "q", "b": "w"},
           "t": {"a": "t", "b": "t"},
           "u": {"a": "u", "b": "u"},
           "v": {"a": "v", "b": "v"},
           "w": {"a": "w", "b": "w"}},
    pos={"p": (150, 150), "q": (410, 150), "r": (670, 150), "s": (930, 150),
         "t": (150, 420), "u": (410, 420), "v": (670, 420), "w": (930, 420)},
    size=(1080, 540),
    notes={"t": "non-final sink", "u": "final sink", "v": "non-final sink", "w": "final sink"},
    curves={("s", "q"): 84},
    loops={"t": 180, "u": 0, "v": 180, "w": 0},
    start_dir=(0, -1),
)

Q7A_MIN = Machine(
    key="q7a-minimised-dfa",
    title="Q7(a) · Minimised DFA",
    kind="Minimal DFA · 6 states",
    blurb="only u with w, and t with v, can be merged",
    alphabet=["a", "b"],
    start="P", accept={"P", "U"},
    delta={"P": {"a": "D", "b": "Q"},
           "Q": {"a": "R", "b": "U"},
           "R": {"a": "S", "b": "D"},
           "S": {"a": "Q", "b": "U"},
           "U": {"a": "U", "b": "U"},
           "D": {"a": "D", "b": "D"}},
    pos={"P": (150, 150), "Q": (410, 150), "R": (670, 150), "S": (930, 150),
         "D": (280, 430), "U": (810, 430)},
    size=(1080, 560),
    notes={"P": "{p}", "Q": "{q}", "R": "{r}", "S": "{s}", "U": "{u, w}", "D": "{t, v}"},
    curves={("S", "Q"): 84, ("R", "D"): -26},
    loops={"U": 0, "D": 180},
    start_dir=(0, -1),
    footnote="Partition refinement: {p,u,w}|{q,r,s,t,v} → {p}|{u,w}|{q,s}|{r,t,v} → "
             "{p}|{u,w}|{q,s}|{r}|{t,v} → {p}|{u,w}|{q}|{s}|{r}|{t,v}. q and s split last, "
             "because on a they go to r and q respectively.",
)

# ---------------------------------------------------------------------------
# Q7(b)  boolean operations on M1 (ends 00) and M2 (ends 11)
# ---------------------------------------------------------------------------
Q7B_INT = Machine(
    key="q7b-intersection",
    title="Q7(b1) · L(M1) ∩ L(M2) = ∅",
    kind="Minimal DFA · 1 state",
    blurb="no word ends in 00 and in 11 at the same time",
    alphabet=["0", "1"],
    start="X", accept=set(),
    delta={"X": {"0": "X", "1": "X"}},
    pos={"X": (210, 140)}, size=(420, 250),
    notes={"X": "never accepts"},
    loops={"X": -90},
)

Q7B_UNION = Machine(
    key="q7b-union",
    title="Q7(b2) · L(M1) ∪ L(M2): ends in 00 or in 11",
    kind="Minimal DFA · 5 states",
    blurb="reachable product pairs of the two three-state machines",
    alphabet=["0", "1"],
    start="S", accept={"F0", "F1"},
    delta={"S": {"0": "Z", "1": "O"},
           "Z": {"0": "F0", "1": "O"},
           "F0": {"0": "F0", "1": "O"},
           "O": {"0": "Z", "1": "F1"},
           "F1": {"0": "Z", "1": "F1"}},
    pos={"S": (140, 260), "Z": (400, 130), "F0": (680, 130),
         "O": (400, 390), "F1": (680, 390)},
    size=(830, 540),
    notes={"S": "(p,q0) no symbol", "Z": "(q,q0) last 0", "F0": "(r,q0) suffix 00",
           "O": "(p,q1) last 1", "F1": "(p,q2) suffix 11"},
    curves={("Z", "O"): 24, ("O", "Z"): 24, ("F0", "O"): 34, ("F1", "Z"): 34},
    loops={"F0": -90, "F1": 90},
)

Q7B_DIFF = Machine(
    key="q7b-difference",
    title="Q7(b3) · L(M1) − L(M2) = L(M1): ends in 00",
    kind="Minimal DFA · 3 states",
    blurb="a word ending in 00 can never end in 11, so nothing is removed",
    alphabet=["0", "1"],
    start="P", accept={"R"},
    delta={"P": {"0": "Q", "1": "P"},
           "Q": {"0": "R", "1": "P"},
           "R": {"0": "R", "1": "P"}},
    pos={"P": (150, 185), "Q": (420, 185), "R": (690, 185)},
    size=(840, 340),
    notes={"P": "no useful suffix", "Q": "suffix 0", "R": "suffix 00"},
    curves={("Q", "P"): 22, ("P", "Q"): 22, ("R", "P"): -74},
    loops={"P": -90, "R": -90},
)

# ---------------------------------------------------------------------------
# Q8(a)  third symbol from the right is 1
# ---------------------------------------------------------------------------
Q8A_NFA = Machine(
    key="q8a-third-from-right-enfa",
    title="Q8(a) · Third symbol from the right is 1 — ε-NFA",
    kind="ε-NFA · 5 states",
    blurb="regular expression (0+1)* 1 (0+1)(0+1)",
    alphabet=["0", "1"],
    start="q0", accept={"q4"}, nondet=True,
    delta={"q0": {"0": ["q0"], "1": ["q0"], "ε": ["q1"]},
           "q1": {"1": ["q2"]},
           "q2": {"0": ["q3"], "1": ["q3"]},
           "q3": {"0": ["q4"], "1": ["q4"]},
           "q4": {}},
    pos={"q0": (140, 190), "q1": (370, 190), "q2": (600, 190),
         "q3": (830, 175), "q4": (1060, 175)},
    size=(1200, 300),
    notes={"q0": "scan any prefix", "q1": "guess made", "q2": "distinguished 1 read",
           "q3": "one more symbol", "q4": "two more symbols"},
    loops={"q0": -90},
    footnote="The ε-edge guesses that the next symbol is the distinguished 1; the two "
             "following factors then force exactly two symbols after it.",
)

_q8a_ring = ["000", "001", "011", "111", "110", "101", "010", "100"]
_q8a_pos = {}
for _i, _s in enumerate(_q8a_ring):
    _a = math.radians(-90 + 45 * _i)
    _q8a_pos[_s] = (round(400 + 235 * math.cos(_a), 1), round(345 + 235 * math.sin(_a), 1))

Q8A_DFA = Machine(
    key="q8a-third-from-right-dfa",
    title="Q8(a) · Third symbol from the right is 1 — minimal DFA",
    kind="Minimal DFA · 8 states",
    blurb="a 3-bit shift register: on input b, xyz → yzb; accept when x = 1",
    alphabet=["0", "1"],
    start="000", accept={"100", "101", "110", "111"},
    delta={s: {"0": s[1:] + "0", "1": s[1:] + "1"} for s in _q8a_ring},
    pos=_q8a_pos, size=(800, 640),
    curves={("001", "010"): 34, ("100", "001"): 34, ("101", "011"): 34,
            ("110", "100"): 34, ("011", "110"): -20,
            ("101", "010"): 22, ("010", "101"): 22},
    loops={"000": 180, "111": 45},
    start_dir=(0, -1),
    footnote="The eight states sit on the de Bruijn cycle 000 001 011 111 110 101 010 100, so "
             "the ring edges are exactly one shift apart. Two histories that differ in the "
             "first, second or third bit are separated by appending 0, 1 or 2 arbitrary bits.",
)

# ---------------------------------------------------------------------------
# Q8(b)  every length-3 window holds at least two a symbols
# ---------------------------------------------------------------------------
Q8B = Machine(
    key="q8b-window-two-a",
    title="Q8(b) · Every length-3 window has at least two a symbols",
    kind="Minimal DFA · 7 states",
    blurb="forbidden blocks: bbb, bba, bab, abb",
    alphabet=["a", "b"],
    start="E", accept={"E", "A", "B", "AB", "BA", "BB"},
    delta={"E": {"a": "A", "b": "B"},
           "A": {"a": "A", "b": "AB"},
           "B": {"a": "BA", "b": "BB"},
           "AB": {"a": "BA", "b": "D"},
           "BA": {"a": "A", "b": "D"},
           "BB": {"a": "D", "b": "D"},
           "D": {"a": "D", "b": "D"}},
    pos={"E": (150, 130), "A": (420, 130), "AB": (700, 130),
         "B": (420, 380), "BA": (700, 380), "BB": (420, 620), "D": (950, 380)},
    size=(1090, 730),
    notes={"E": "no useful suffix", "A": "suffix a", "B": "suffix b", "AB": "suffix ab",
           "BA": "suffix ba", "BB": "suffix bb", "D": "a forbidden triple occurred"},
    curves={("AB", "BA"): 20, ("BA", "A"): -20, ("B", "BB"): -18},
    loops={"A": -90, "D": -90},
    footnote="Every safe state accepts, because words shorter than 3 satisfy the condition "
             "vacuously. From AB reading b completes abb, so the machine traps; reading a "
             "leaves the suffix ba.",
)

MACHINES = [Q1, Q2, Q4, Q5A, Q5B, Q5C, Q5D_NFA, Q5D_DFA, Q6A, Q6B,
            Q6C_NFA, Q6C_DFA, Q7A_ORIG, Q7A_MIN, Q7B_INT, Q7B_UNION, Q7B_DIFF,
            Q8A_NFA, Q8A_DFA, Q8B]

GROUPS = [
    ("Part A · compulsory", [Q1, Q2, Q4]),
    ("Q5 · counting and pattern DFAs", [Q5A, Q5B, Q5C, Q5D_NFA, Q5D_DFA]),
    ("Q6 · suffix, counting and block machines", [Q6A, Q6B, Q6C_NFA, Q6C_DFA]),
    ("Q7 · minimisation and boolean operations", [Q7A_ORIG, Q7A_MIN, Q7B_INT, Q7B_UNION, Q7B_DIFF]),
    ("Q8 · long-answer constructions", [Q8A_NFA, Q8A_DFA, Q8B]),
]

ANSWER_MAP = [
    ("Q1", "Minimum DFA for product of symbols mod 7", "6 states", "q1-product-mod-7"),
    ("Q2", "#01 = #10", "5 states; ε or first symbol = last symbol", "q2-equal-01-10"),
    ("Q3", "Shortest word outside a*b*(ba)*a*", "length 3; witness bab", None),
    ("Q4", "δ̂(q2, aaaabbbaaab)", "∅", "q4-epsilon-nfa"),
    ("Q5(a)", "Binary value divisible by 4", "3-state minimal DFA", "q5a-divisible-by-4"),
    ("Q5(b)", "#1 ≡ 0 (mod 4) and #0 odd", "8-state minimal product DFA",
     "q5b-ones-mod4-zeros-odd"),
    ("Q5(c)", "Avoid aa", "3-state minimal DFA", "q5c-avoid-aa"),
    ("Q5(d)", "Start and end with the same symbol", "4-state NFA; 5-state minimal DFA",
     "q5d-same-first-last-nfa"),
    ("Q6(a)", "End with 01", "3-state minimal DFA", "q6a-ends-with-01"),
    ("Q6(b)", "Exactly two a symbols", "4-state minimal DFA", "q6b-exactly-two-a"),
    ("Q6(c)", "aⁿbᵐcᵖd^q with two parity tests", "8-state ε-NFA; 9 DFA states with the trap",
     "q6c-blocks-enfa"),
    ("Q7(a)", "Minimise the photographed 8-state DFA", "6 equivalence classes",
     "q7a-original-dfa"),
    ("Q7(b)", "M1 ∩ M2, M1 ∪ M2, M1 − M2", "1, 5 and 3 states", "q7b-intersection"),
    ("Q8(a)", "Third symbol from the right is 1", "RE + 5-state ε-NFA + 8-state minimal DFA",
     "q8a-third-from-right-enfa"),
    ("Q8(b)", "Every length-3 window has at least two a symbols", "7-state minimal DFA",
     "q8b-window-two-a"),
]

PAGE_CSS = """
:root{
  --ground:#eceff4; --plate:#ffffff; --ink:#12151c; --muted:#59617a;
  --rule:#dbe0e9; --rule-soft:#eaedf3; --mark:#ad1f45; --mark-tint:#fbe9ee;
  --tag:#eef1f6;
  --serif:ui-serif, Georgia, 'Iowan Old Style', 'Times New Roman', serif;
  --sans:ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  --mono:ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, 'Liberation Mono', monospace;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --ground:#0a0c11; --plate:#12151c; --ink:#e6e9f2; --muted:#949db3;
    --rule:#232936; --rule-soft:#1a1f29; --mark:#ff7f99; --mark-tint:#26131a; --tag:#1b202a;
  }
}
:root[data-theme="dark"]{
  --ground:#0a0c11; --plate:#12151c; --ink:#e6e9f2; --muted:#949db3;
  --rule:#232936; --rule-soft:#1a1f29; --mark:#ff7f99; --mark-tint:#26131a; --tag:#1b202a;
}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);font-family:var(--sans);
  line-height:1.55;-webkit-font-smoothing:antialiased}
.wrap{max-width:1120px;margin:0 auto;padding:64px 22px 100px;display:flex;
  flex-direction:column;gap:34px}
a{color:inherit}
a:focus-visible,summary:focus-visible{outline:2px solid var(--mark);outline-offset:3px;
  border-radius:3px}
.eyebrow{font-family:var(--mono);font-size:12px;letter-spacing:.16em;text-transform:uppercase;
  color:var(--mark);margin:0 0 14px}
h1{font-family:var(--serif);font-size:clamp(30px,5vw,46px);line-height:1.08;margin:0 0 16px;
  letter-spacing:-.015em;font-weight:600;text-wrap:balance;max-width:18ch}
.lede{color:var(--muted);max-width:64ch;margin:0;font-size:16px}
.legend{display:flex;flex-wrap:wrap;gap:8px 26px;margin:26px 0 0;padding:0;list-style:none;
  font-size:13px;color:var(--muted)}
.legend b{color:var(--ink);font-weight:600;font-family:var(--mono);font-size:12.5px}
.map{border-top:1px solid var(--ink);border-bottom:1px solid var(--rule)}
.map caption{caption-side:top;text-align:left;font-family:var(--mono);font-size:11.5px;
  letter-spacing:.14em;text-transform:uppercase;color:var(--muted);padding-bottom:10px}
.map table{width:100%;border-collapse:collapse}
.map td{border-bottom:1px solid var(--rule-soft);padding:9px 16px 9px 0;vertical-align:baseline;
  font-size:14px}
.map tr:last-child td{border-bottom:none}
.map .q{font-family:var(--mono);font-size:12.5px;color:var(--mark);white-space:nowrap;width:1%}
.map .res{color:var(--muted);text-align:right;white-space:nowrap}
.map a{text-decoration:none;border-bottom:1px solid var(--rule)}
.map a:hover{border-bottom-color:var(--mark)}
.map .none{color:var(--muted)}
h2.group{font-family:var(--mono);font-size:11.5px;letter-spacing:.16em;text-transform:uppercase;
  color:var(--muted);font-weight:500;margin:26px 0 -14px;padding-bottom:10px;
  border-bottom:1px solid var(--ink)}
.card{background:var(--plate);border:1px solid var(--rule);padding:26px 26px 18px;
  display:flex;flex-direction:column;gap:14px;scroll-margin-top:20px}
.head{display:flex;flex-wrap:wrap;align-items:baseline;gap:10px 12px}
.tag{font-family:var(--mono);font-size:12.5px;color:var(--mark);letter-spacing:.04em}
.card h3{font-family:var(--serif);margin:0;font-size:21px;font-weight:600;letter-spacing:-.01em;
  flex:1 1 22ch}
.chip{font-family:var(--mono);background:var(--tag);color:var(--muted);padding:4px 10px;
  font-size:11.5px;white-space:nowrap}
.blurb{color:var(--muted);font-size:14.5px;margin:-4px 0 0;max-width:80ch}
.figure{overflow-x:auto;margin:0;padding:4px 0;
  --auto-ink:var(--ink);--auto-muted:var(--muted);--auto-accent:var(--mark);--auto-bg:var(--plate)}
.figure svg{display:block;margin:0 auto;max-width:100%;height:auto}
.note{margin:0;font-size:14px;color:var(--muted);border-left:2px solid var(--mark);
  padding-left:14px;max-width:88ch}
details{border-top:1px solid var(--rule-soft);padding-top:12px;margin-top:2px}
summary{cursor:pointer;font-family:var(--mono);font-size:12px;letter-spacing:.1em;
  text-transform:uppercase;color:var(--muted);list-style:none}
summary::-webkit-details-marker{display:none}
summary::before{content:"+ ";color:var(--mark)}
details[open] summary::before{content:"− "}
.tablewrap{overflow-x:auto;margin-top:14px}
table.delta{border-collapse:collapse;font-family:var(--mono);font-size:13px;min-width:100%;
  font-variant-numeric:tabular-nums}
table.delta th,table.delta td{border-bottom:1px solid var(--rule-soft);padding:7px 16px 7px 8px;
  text-align:left;white-space:nowrap}
table.delta thead th{font-size:11px;letter-spacing:.12em;text-transform:uppercase;
  color:var(--muted);font-weight:500;border-bottom:1px solid var(--rule)}
table.delta thead th.sym{text-transform:none;letter-spacing:0;font-size:13px;color:var(--ink)}
table.delta tbody th{font-weight:600}
table.delta tbody tr.acc th,table.delta tbody tr.acc td{background:var(--mark-tint)}
.mk{color:var(--mark)}
td.mean{font-family:var(--sans);color:var(--muted);white-space:normal;min-width:16ch}
footer{color:var(--muted);font-size:13px;border-top:1px solid var(--rule);padding-top:20px}
footer code{font-family:var(--mono);font-size:12.5px;color:var(--ink)}
@media (max-width:640px){
  .wrap{padding:40px 16px 72px}
  .card{padding:20px 16px 14px}
  .map .res{display:none}
}
"""


def answer_map_html():
    rows = []
    for tag, task, result, key in ANSWER_MAP:
        task_cell = f'<a href="#{key}">{esc(task)}</a>' if key else (
            f'<span class="none">{esc(task)} — no automaton in this question</span>')
        rows.append(f'<tr><td class="q">{esc(tag)}</td><td>{task_cell}</td>'
                    f'<td class="res">{esc(result)}</td></tr>')
    return ('<section class="map"><table><caption>Answer map · jump to a machine</caption>'
            '<tbody>' + "".join(rows) + "</tbody></table></section>")


def page_html():
    out = [f"<title>Series Exam 1 Automata</title><style>{PAGE_CSS}</style>",
           '<div class="wrap">', "<header>",
           '<p class="eyebrow">PCCST302 · Theory of Computation</p>',
           "<h1>Series Exam 1, every automaton drawn</h1>",
           '<p class="lede">A state diagram for each machine in the fully solved paper — '
           '20 of them across Q1–Q8, both OR branches included. Each diagram is generated '
           'from the same transition function as the table printed beneath it, so the arrows '
           'and the table cannot disagree.</p>',
           '<ul class="legend">'
           '<li><b>→</b> initial state</li>'
           '<li><b>double ring</b> accepting state</li>'
           '<li><b>tinted row</b> accepting state in the table</li>'
           '<li><b>D / X</b> dead or trap state</li>'
           '<li><b>ε</b> consumes no input</li>'
           "</ul></header>",
           answer_map_html()]
    for group, machines in GROUPS:
        out.append(f'<h2 class="group">{esc(group)}</h2>')
        for m in machines:
            tag, _, name = m.title.partition(" · ")
            out.append(f'<section class="card" id="{esc(m.key)}">')
            out.append(f'<div class="head"><span class="tag">{esc(tag)}</span>'
                       f'<h3>{esc(name)}</h3><span class="chip">{esc(m.kind)}</span></div>')
            out.append(f'<p class="blurb">{esc(m.blurb)}</p>')
            out.append(f'<figure class="figure">{m.svg(standalone=False)}</figure>')
            if m.footnote:
                out.append(f'<p class="note">{esc(m.footnote)}</p>')
            out.append('<details><summary>Transition table</summary>'
                       f'<div class="tablewrap">{m.table_html()}</div></details>')
            out.append("</section>")
    out.append('<footer>Drawn from the solved paper by <code>tools/generate_automata.py</code>. '
               'Standalone SVGs live in <code>automata/</code> and follow the system light or '
               'dark theme.</footer></div>')
    return "\n".join(out)


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    outdir = os.path.join(root, "automata")
    os.makedirs(outdir, exist_ok=True)
    for m in MACHINES:
        with open(os.path.join(outdir, m.key + ".svg"), "w", encoding="utf-8") as fh:
            fh.write(m.svg(standalone=True))
        states = len(m.delta)
        edges = len(m.grouped_edges())
        print(f"{m.key:38s} {states:2d} states {edges:3d} arrows")
    with open(os.path.join(outdir, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(page_html())
    print(f"\n{len(MACHINES)} diagrams + index.html written to {outdir}")


if __name__ == "__main__":
    main()
