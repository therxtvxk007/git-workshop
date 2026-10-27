"""Manim video: Digital Electronics Lab — Viva Cheat Sheet.

Render all scenes and stitch them with ./render.sh  (needs manim + ffmpeg, no LaTeX).
"""

import hashlib
import os
import wave
from pathlib import Path

from manim import *

FONT = "DejaVu Sans"
MONO = "DejaVu Sans Mono"

config.background_color = "#0d0d12"


# ---------------------------------------------------------------- helpers
def T(s, size=30, color=WHITE, **kw):
    return Text(s, font=FONT, font_size=size, color=color, **kw)


def M(s, size=26, color=WHITE, **kw):
    return Text(s, font=MONO, font_size=size, color=color, **kw)


def heading(s, color=YELLOW):
    t = T(s, 40, color, weight=BOLD)
    if t.width > 12.5:
        t.set_width(12.5)
    t.to_edge(UP, buff=0.35)
    line = Line(t.get_corner(DL), t.get_corner(DR), color=color).shift(DOWN * 0.12)
    return VGroup(t, line)


def fit(m, w=13.0):
    if m.width > w:
        m.set_width(w)
    return m


class Caption:
    """Bottom-of-screen narration line."""

    def __init__(self, scene):
        self.scene, self.cur = scene, None

    def say(self, s, wait=2.0, color=GREY_A):
        new = fit(T(s, 24, color), 13).to_edge(DOWN, buff=0.3)
        if self.cur is None:
            self.scene.play(FadeIn(new, shift=UP * 0.2), run_time=0.6)
        else:
            self.scene.play(FadeOut(self.cur, shift=UP * 0.2), FadeIn(new, shift=UP * 0.2), run_time=0.6)
        self.cur = new
        self.scene.wait(wait)


def clear_all(scene):
    sync(scene)
    if scene.mobjects:
        scene.play(*[FadeOut(m) for m in scene.mobjects], run_time=0.7)


def new_page(scene, title, color=YELLOW):
    clear_all(scene)
    h = heading(title, color)
    scene.play(FadeIn(h))
    return Caption(scene)


def table(rows, xs, y0, dy=0.5, size=24, header_color=YELLOW, colors=None):
    """rows[0] is the header. Returns VGroup of row VGroups."""
    g = VGroup()
    for r, row in enumerate(rows):
        col = header_color if r == 0 else (colors[r - 1] if colors else WHITE)
        g.add(VGroup(*[T(str(c), size, col).move_to([x, y0 - r * dy, 0]) for c, x in zip(row, xs)]))
    rule = Line([xs[0] - 0.5, y0 - dy / 2, 0], [xs[-1] + 0.5, y0 - dy / 2, 0], stroke_width=2, color=GREY_B)
    g.rule = rule
    return g


def show_table(scene, tbl, lag=0.12):
    scene.play(FadeIn(tbl[0]), Create(tbl.rule), run_time=0.6)
    scene.play(LaggedStart(*[FadeIn(r, shift=RIGHT * 0.15) for r in tbl[1:]], lag_ratio=lag))


def expr_table(rows, y0=1.6, dy=0.55, size=24, left=-5.6, mid=-0.6):
    g = VGroup()
    hdr = VGroup(T("Circuit / concept", size, YELLOW).move_to([left, y0, 0], aligned_edge=LEFT),
                 T("Expression", size, YELLOW).move_to([mid, y0, 0], aligned_edge=LEFT))
    g.add(hdr)
    for i, (a, b) in enumerate(rows):
        y = y0 - (i + 1) * dy
        g.add(VGroup(T(a, size, GREY_A).move_to([left, y, 0], aligned_edge=LEFT),
                     fit(M(b, size - 2, GREEN_B), 6.6 - mid).move_to([mid, y, 0], aligned_edge=LEFT)))
    return g


def gate(kind, center, w=1.0, h=0.8, color=BLUE_B, in_bubbles=False):
    """AND / OR / NAND / NOR / NOT symbol with .in1 .in2 .out anchor points."""
    c = np.array(center, dtype=float)
    l, r = c[0] - w / 2, c[0] + w / 2
    top, bot = c[1] + h / 2, c[1] - h / 2
    sw = 3
    g = VGroup()
    base = kind.replace("N", "", 1) if kind in ("NAND", "NOR") else kind
    if base == "AND":
        r0 = r - h / 2
        g.add(VMobject(color=color, stroke_width=sw).set_points_as_corners(
            [[r0, top, 0], [l, top, 0], [l, bot, 0], [r0, bot, 0]]))
        g.add(ArcBetweenPoints([r0, bot, 0], [r0, top, 0], angle=PI, color=color, stroke_width=sw))
        out = np.array([r, c[1], 0])
        inx = l
    elif base == "OR":
        g.add(ArcBetweenPoints([l, bot, 0], [l, top, 0], angle=-0.9, color=color, stroke_width=sw))
        g.add(ArcBetweenPoints([l, top, 0], [r, c[1], 0], angle=-0.6, color=color, stroke_width=sw))
        g.add(ArcBetweenPoints([l, bot, 0], [r, c[1], 0], angle=0.6, color=color, stroke_width=sw))
        out = np.array([r, c[1], 0])
        inx = l + 0.12
    else:  # NOT
        g.add(Polygon([l, top, 0], [l, bot, 0], [r - 0.16, c[1], 0], color=color, stroke_width=sw))
        out = np.array([r - 0.16, c[1], 0])
        inx = l
    if kind in ("NAND", "NOR", "NOT"):
        g.add(Circle(radius=0.08, color=color, stroke_width=sw).move_to(out + RIGHT * 0.08))
        out = out + RIGHT * 0.16
    g.in1 = np.array([inx, c[1] + h / 4, 0]) if kind != "NOT" else np.array([l, c[1], 0])
    g.in2 = np.array([inx, c[1] - h / 4, 0]) if kind != "NOT" else np.array([l, c[1], 0])
    if in_bubbles:
        for p in (g.in1, g.in2):
            g.add(Circle(radius=0.08, color=color, stroke_width=sw).move_to(p + LEFT * 0.08))
        g.in1, g.in2 = g.in1 + LEFT * 0.16, g.in2 + LEFT * 0.16
    g.out = out
    return g


def wire(points, color=WHITE, sw=3):
    return VMobject(color=color, stroke_width=sw).set_points_as_corners(
        [np.array(p, dtype=float) for p in points])


def waveform(levels, x0, y0, dx, h, color, sw=4):
    pts = []
    for i, lv in enumerate(levels):
        x = x0 + i * dx
        if i > 0 and levels[i - 1] != lv:
            pts.append([x, y0 + levels[i - 1] * h, 0])
        pts.append([x, y0 + lv * h, 0])
    pts.append([x0 + len(levels) * dx, y0 + levels[-1] * h, 0])
    return VMobject(color=color, stroke_width=sw).set_points_as_corners(pts)


def block(label, w=1.4, h=1.0, color=WHITE, size=24):
    r = Rectangle(width=w, height=h, color=color, stroke_width=3)
    return VGroup(r, T(label, size, color).move_to(r))


def code(src, width=None, size=20):
    c = Code(code_string=src, language="verilog", formatter_style="monokai", add_line_numbers=False,
             background="rectangle", paragraph_config={"font": MONO, "font_size": size},
             background_config={"stroke_color": GREY_D, "fill_color": "#1b1b24", "fill_opacity": 1})
    if width and c.width > width:
        c.set_width(width)
    return c


def lamp(on, r=0.16, color=YELLOW):
    return Circle(radius=r, color=color if on else GREY_D, fill_opacity=0.9 if on else 0.15, stroke_width=2)


def bits(v, n):
    return format(v, f"0{n}b")


# ---------------------------------------------------------------- voiceover
# Narration is synthesised offline with Kokoro TTS (pip install kokoro-onnx soundfile) and
# cached as WAV files in ./voiceover, so a re-render only synthesises lines that changed.
# Model files (kokoro-v1.0.int8.onnx, voices-v1.0.bin) are read from $KOKORO_DIR.
VO_VOICE = os.environ.get("VO_VOICE", "af_heart")
VO_SPEED = float(os.environ.get("VO_SPEED", "1.0"))
VO_MODEL_DIR = Path(os.environ.get("KOKORO_DIR", Path.home() / ".cache" / "kokoro"))
VO_CACHE = Path(__file__).resolve().parent / "voiceover"
_kokoro = None


def tts(text):
    """Return (wav path, duration in seconds) for a narration line."""
    global _kokoro
    VO_CACHE.mkdir(exist_ok=True)
    key = hashlib.sha1(f"{VO_VOICE}|{VO_SPEED}|{text}".encode()).hexdigest()[:16]
    path = VO_CACHE / f"{key}.wav"
    if not path.exists():
        import soundfile as sf
        from kokoro_onnx import Kokoro
        if _kokoro is None:
            _kokoro = Kokoro(str(VO_MODEL_DIR / "kokoro-v1.0.int8.onnx"), str(VO_MODEL_DIR / "voices-v1.0.bin"))
        samples, sr = _kokoro.create(text, voice=VO_VOICE, speed=VO_SPEED, lang="en-us")
        sf.write(str(path), samples, sr)
    with wave.open(str(path)) as w:
        return path, w.getnframes() / w.getframerate()


def sync(scene, pad=0.4):
    """Wait until the current narration line has finished."""
    rem = getattr(scene, "_vo_end", 0.0) - scene.renderer.time + pad
    if rem > 0.05:
        scene.wait(rem)
    scene._vo_end = 0.0


def say(scene, text):
    """Start a narration line; animations that follow play while it is spoken."""
    sync(scene, pad=0.15)
    path, dur = tts(text)
    scene.add_sound(str(path))
    scene._vo_end = scene.renderer.time + dur


# ---------------------------------------------------------------- scenes
class V01_Boolean(Scene):
    def construct(self):
        t1 = T("Digital Electronics Lab", 56, YELLOW, weight=BOLD)
        t2 = T("Viva Cheat Sheet — animated", 32, GREY_B).next_to(t1, DOWN, buff=0.35)
        topics = T("Boolean algebra • Adders • Subtractors • Overflow • MUX/DEMUX • Decoders\n"
                   "Priority encoder • 7-segment • Flip-flops • Verilog • Testbenches",
                   22, GREY_A, line_spacing=1.2).next_to(t2, DOWN, buff=0.6)
        say(self, "Welcome to this quick revision of the digital electronics lab viva cheat sheet. We'll cover Boolean algebra, adders and subtractors, overflow, multiplexers, decoders and encoders, seven segment displays, flip-flops, Verilog, and testbenches.")
        self.play(Write(t1), run_time=1.5)
        self.play(FadeIn(t2, shift=UP * 0.2))
        self.play(FadeIn(topics))
        self.wait(2.5)

        cap = new_page(self, "1. Boolean Algebra — the main laws")
        say(self, 'Boolean algebra is the math of zeros and ones. We use it to simplify circuits so that fewer gates are needed. The main laws are identity: A plus zero is A, and A times one is A. Null: A plus one is one, and A times zero is zero. Complement: A plus A prime is one, and A times A prime is zero. Idempotent: A plus A is A. Absorption: A plus A B is A. And the commutative, associative and distributive laws.')
        laws = [("Identity", "A + 0 = A\nA · 1 = A"), ("Null", "A + 1 = 1\nA · 0 = 0"),
                ("Complement", "A + A' = 1\nA · A' = 0"), ("Idempotent", "A + A = A\nA · A = A"),
                ("Absorption", "A + AB = A"), ("Comm. / Assoc. / Distrib.", "A + B = B + A\nA(B + C) = AB + AC")]
        cards = VGroup()
        for name, f in laws:
            box = RoundedRectangle(width=4.0, height=1.9, corner_radius=0.15, color=BLUE_D, stroke_width=2)
            nm = T(name, 24, BLUE_B).move_to(box.get_top() + DOWN * 0.35)
            fm = M(f, 24, WHITE, line_spacing=1.1).move_to(box.get_center() + DOWN * 0.25)
            cards.add(VGroup(box, nm, fm))
        cards.arrange_in_grid(2, 3, buff=0.35).shift(DOWN * 0.35)
        self.play(LaggedStart(*[FadeIn(c, shift=UP * 0.2) for c in cards], lag_ratio=0.25), run_time=3)
        cap.say("Boolean algebra is the math of 0 and 1 — used to simplify circuits so fewer gates are needed.", 3)

        cap = new_page(self, "De Morgan's Theorems")
        say(self, "De Morgan's theorems convert between AND and OR forms. The complement of A AND B equals A prime OR B prime, and the complement of A OR B equals A prime AND B prime. Flip the operator, and complement each variable. So a NAND gate is the same as an OR gate with inverted inputs, and a NOR is an AND with inverted inputs. This is how an AND-OR circuit is rebuilt using only NAND gates.")
        d1 = M("(A · B)' = A' + B'", 36, YELLOW).shift(UP * 1.9 + LEFT * 3.3)
        d2 = M("(A + B)' = A' · B'", 36, YELLOW).shift(UP * 1.9 + RIGHT * 3.3)
        self.play(Write(d1), Write(d2))
        g1 = gate("NAND", [-5.0, 0.0, 0])
        g2 = gate("OR", [-1.9, 0.0, 0], in_bubbles=True)
        g3 = gate("NOR", [1.9, 0.0, 0])
        g4 = gate("AND", [5.0, 0.0, 0], in_bubbles=True)
        eq1 = T("≡", 44).move_to([-3.45, 0, 0])
        eq2 = T("≡", 44).move_to([3.45, 0, 0])
        self.play(Create(g1), Create(g3))
        self.play(FadeIn(eq1), FadeIn(eq2), Create(g2), Create(g4))
        lb = VGroup(T("NAND", 20, GREY_B).next_to(g1, DOWN), T("OR with inverted inputs", 20, GREY_B).next_to(g2, DOWN),
                    T("NOR", 20, GREY_B).next_to(g3, DOWN), T("AND with inverted inputs", 20, GREY_B).next_to(g4, DOWN))
        self.play(FadeIn(lb))
        rule = T("Rule: flip the operator (AND ↔ OR) and complement every variable", 28, ORANGE).shift(DOWN * 1.7)
        self.play(Write(rule))
        cap.say("This is how an AND-OR circuit is rebuilt using only NAND gates.", 2.5)

        cap = new_page(self, "Universal Gates: NAND and NOR")
        say(self, 'NAND and NOR are universal gates: each one alone can build every other gate. Tie both inputs of a NAND together and you get NOT A. An AND needs two NAND gates: a NAND, followed by a NAND used as an inverter.')
        # NOT from NAND
        n1 = gate("NAND", [-3.2, 0.6, 0])
        a_in = T("A", 28).move_to([-5.2, 0.6, 0])
        jx = -4.4
        w_a = VGroup(wire([a_in.get_right() + RIGHT * 0.1, [jx, 0.6, 0]]),
                     wire([[jx, 0.6, 0], [jx, n1.in1[1], 0], n1.in1]), wire([[jx, 0.6, 0], [jx, n1.in2[1], 0], n1.in2]),
                     Dot([jx, 0.6, 0], radius=0.05))
        o1 = T("A'", 28, GREEN).next_to(n1.out, RIGHT, buff=0.3)
        lbl1 = T("NOT A = (A · A)'", 26, GREEN).move_to([-3.4, -0.7, 0])
        self.play(FadeIn(a_in), Create(w_a), Create(n1))
        self.play(Create(Line(n1.out, o1.get_left() + LEFT * 0.05)), FadeIn(o1), Write(lbl1))
        # AND from two NANDs
        n2 = gate("NAND", [2.2, 0.6, 0])
        n3 = gate("NAND", [4.4, 0.6, 0])
        ia, ib = T("A", 26).move_to([0.8, 0.8, 0]), T("B", 26).move_to([0.8, 0.4, 0])
        w2 = VGroup(Line([1.0, n2.in1[1], 0], n2.in1), Line([1.0, n2.in2[1], 0], n2.in2))
        jx2 = n2.out[0] + 0.35
        w3 = VGroup(Line(n2.out, [jx2, 0.6, 0]), wire([[jx2, 0.6, 0], [jx2, n3.in1[1], 0], n3.in1]),
                    wire([[jx2, 0.6, 0], [jx2, n3.in2[1], 0], n3.in2]), Dot([jx2, 0.6, 0], radius=0.05))
        o2 = T("AB", 26, GREEN).next_to(n3.out, RIGHT, buff=0.3)
        lbl2 = T("AND needs two NAND gates", 26, GREEN).move_to([3.2, -0.7, 0])
        self.play(FadeIn(ia), FadeIn(ib), Create(w2), Create(n2))
        self.play(Create(w3), Create(n3))
        self.play(Create(Line(n3.out, o2.get_left() + LEFT * 0.05)), FadeIn(o2), Write(lbl2))
        cap.say("NAND and NOR are universal: each one alone can build every other gate.", 3)

        cap = new_page(self, "Propagation Delay & Simplification")
        say(self, 'Propagation delay is the time from an input change to the output change. Deep chains of gates are slower, so fewer levels of logic means a faster circuit. To simplify logic, use Boolean algebra, or a Karnaugh map, where you group adjacent ones in groups of one, two, four or eight.')
        x0, dx = -3.5, 0.5
        inp = [0] * 4 + [1] * 10
        out = [0] * 7 + [1] * 7
        w_in = waveform(inp, x0, 1.5, dx, 0.7, BLUE)
        w_out = waveform(out, x0, 0.2, dx, 0.7, PINK)
        self.play(FadeIn(T("input", 22, BLUE).next_to(w_in, LEFT)), Create(w_in))
        self.play(FadeIn(T("output", 22, PINK).next_to(w_out, LEFT)), Create(w_out))
        xa, xb = x0 + 4 * dx, x0 + 7 * dx
        dl = VGroup(DashedLine([xa, 1.5, 0], [xa, 0.0, 0], color=GREY), DashedLine([xb, 1.5, 0], [xb, 0.0, 0], color=GREY))
        br = DoubleArrow([xa, -0.15, 0], [xb, -0.15, 0], buff=0, color=YELLOW, stroke_width=3, tip_length=0.15)
        tp = T("t_pd", 24, YELLOW).next_to(br, DOWN, buff=0.1)
        self.play(Create(dl), GrowFromCenter(br), FadeIn(tp))
        note = VGroup(
            T("Delay = time from input change to output change", 24),
            T("Deep gate chains are slower → fewer logic levels = faster", 24),
            T("Simplify: algebra, or a K-map —", 24),
            T("group adjacent 1s in groups of 1, 2, 4 or 8", 24, GREEN),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.22).move_to([0, -2.3, 0])
        self.play(LaggedStart(*[FadeIn(n) for n in note], lag_ratio=0.4), run_time=2)
        self.wait(2.5)

        cap = new_page(self, "Gate Expressions")
        say(self, 'Here are the basic gate expressions. AND is A times B. OR is A plus B. NOT is A prime. NAND and NOR are the complements of AND and OR. Ex-or is A B prime plus A prime B, which is one when the inputs differ. And ex-nor is A B plus A prime B prime, which is one when they are equal.')
        et = expr_table([("AND gate", "Y = A·B"), ("OR gate", "Y = A + B"), ("NOT gate", "Y = A'"),
                         ("NAND gate", "Y = (A·B)'"), ("NOR gate", "Y = (A + B)'"),
                         ("XOR gate", "Y = AB' + A'B"), ("XNOR gate", "Y = AB + A'B'")], y0=2.0)
        self.play(FadeIn(et[0]))
        self.play(LaggedStart(*[FadeIn(r, shift=RIGHT * 0.2) for r in et[1:]], lag_ratio=0.3), run_time=2.5)
        cap.say("XOR = 1 when the inputs differ;  XNOR = 1 when they are equal.", 3)
        clear_all(self)


class V02_Adders(Scene):
    def construct(self):
        cap = new_page(self, "2. Half Adder")
        say(self, 'A half adder adds two single bits. The sum is A ex-or B, and the carry is A and B. It has no carry-in, so on its own it cannot be chained for multi-bit addition.')
        tb = table([["A", "B", "S", "C"]] + [[a, b, a ^ b, a & b] for a in (0, 1) for b in (0, 1)],
                   xs=[-5.4, -4.6, -3.4, -2.6], y0=1.6, dy=0.6, size=28)
        show_table(self, tb)
        ha = block("Half\nAdder", 1.8, 1.6, BLUE_B).move_to([1.6, 0.6, 0])
        ins = VGroup(Arrow([-0.3, 1.0, 0], ha.get_left() + UP * 0.4, buff=0, stroke_width=3),
                     Arrow([-0.3, 0.2, 0], ha.get_left() + DOWN * 0.4, buff=0, stroke_width=3),
                     T("A", 24).move_to([-0.5, 1.0, 0]), T("B", 24).move_to([-0.5, 0.2, 0]))
        outs = VGroup(Arrow(ha.get_right() + UP * 0.4, ha.get_right() + UP * 0.4 + RIGHT * 1.2, buff=0, stroke_width=3),
                      Arrow(ha.get_right() + DOWN * 0.4, ha.get_right() + DOWN * 0.4 + RIGHT * 1.2, buff=0, stroke_width=3),
                      T("S", 24).move_to(ha.get_right() + UP * 0.4 + RIGHT * 1.5),
                      T("C", 24).move_to(ha.get_right() + DOWN * 0.4 + RIGHT * 1.5))
        self.play(FadeIn(ha), FadeIn(ins), FadeIn(outs))
        e = VGroup(M("S = A ⊕ B = AB' + A'B", 26, GREEN), M("C = A · B", 26, GREEN)).arrange(DOWN, aligned_edge=LEFT)
        e.move_to([2.3, -1.5, 0])
        self.play(Write(e))
        cap.say("No carry-in, so a half adder alone cannot be chained for multi-bit addition.", 3)

        cap = new_page(self, "Full Adder")
        say(self, 'A full adder adds two bits plus a carry-in from the previous stage. The sum is A ex-or B ex-or carry-in. The carry-out is A B, plus B carry-in, plus A carry-in, which can also be written as A B plus carry-in times A ex-or B.')
        rows = [[a, b, c, a ^ b ^ c, int(a + b + c >= 2)] for a in (0, 1) for b in (0, 1) for c in (0, 1)]
        tb = table([["A", "B", "Cin", "S", "Cout"]] + rows, xs=[-5.6, -4.9, -4.1, -3.0, -2.1], y0=2.2, dy=0.5, size=26)
        show_table(self, tb, lag=0.08)
        e = VGroup(M("S    = A ⊕ B ⊕ Cin", 26, GREEN),
                   M("Cout = AB + B·Cin + A·Cin", 26, GREEN),
                   M("     = AB + Cin(A ⊕ B)", 26, GREEN)).arrange(DOWN, aligned_edge=LEFT, buff=0.2).move_to([2.6, 1.3, 0])
        self.play(Write(e), run_time=2)
        sum_rows = [i for i, r in enumerate(rows) if r[3]]
        car_rows = [i for i, r in enumerate(rows) if r[4]]
        say(self, 'Notice that the sum is one when an odd number of inputs are one, which is why ex-or is used for the sum. The carry-out is one when at least two of the three inputs are one.')
        hs = VGroup(*[SurroundingRectangle(tb[i + 1][3], color=BLUE, buff=0.08) for i in sum_rows])
        self.play(Create(hs))
        t1 = T("S = 1 when an ODD number of inputs are 1  → XOR", 24, BLUE).move_to([2.6, -0.3, 0])
        self.play(FadeIn(t1))
        self.wait(1)
        hc = VGroup(*[SurroundingRectangle(tb[i + 1][4], color=ORANGE, buff=0.08) for i in car_rows])
        self.play(ReplacementTransform(hs, hc))
        t2 = T("Cout = 1 when AT LEAST TWO inputs are 1  (majority)", 24, ORANGE).move_to([2.6, -0.9, 0])
        self.play(FadeIn(t2))
        cap.say("The carry-in is what lets full adders be chained.", 2)

        cap = new_page(self, "Ripple-Carry Adder (4 full adders)")
        say(self, 'The carry-in is what lets full adders be chained into a ripple-carry adder. Here we add seven and five. Each stage passes its carry to the next, so the last stage has to wait for all the earlier ones. The result is twelve.')
        A, B = 0b0111, 0b0101
        fas = VGroup(*[block(f"FA{i}", 1.4, 1.2, BLUE_B) for i in range(4)]).arrange(LEFT, buff=1.0).shift(UP * 0.2)
        self.play(FadeIn(fas))
        lbls, sums, carries = VGroup(), VGroup(), []
        for i, fa in enumerate(fas):
            lbls.add(T(f"A{i}={A >> i & 1}  B{i}={B >> i & 1}", 18, GREY_A).next_to(fa, UP, buff=0.25))
        self.play(FadeIn(lbls))
        c = 0
        cin = T("Cin=0", 18, ORANGE).next_to(fas[0], RIGHT, buff=0.2)
        self.play(FadeIn(cin))
        for i, fa in enumerate(fas):
            a, b = A >> i & 1, B >> i & 1
            s, c_new = a ^ b ^ c, int(a + b + c >= 2)
            sd = T(f"S{i}={s}", 22, GREEN).next_to(fa, DOWN, buff=0.3)
            arr = Arrow(fa.get_left(), fa.get_left() + LEFT * 1.0, buff=0, color=ORANGE, stroke_width=4)
            cl = T(str(c_new), 20, ORANGE).next_to(arr, UP, buff=0.05)
            self.play(Indicate(fa, color=YELLOW, scale_factor=1.08), run_time=0.5)
            self.play(FadeIn(sd), GrowArrow(arr), FadeIn(cl), run_time=0.6)
            sums.add(sd)
            c = c_new
        res = T(f"{bits(A, 4)} (7) + {bits(B, 4)} (5) = {c}{bits((A + B) % 16, 4)} (12)", 30, YELLOW).shift(DOWN * 2.0)
        self.play(Write(res))
        cap.say("Each carry ripples to the next stage — the last stage must wait for all earlier ones.", 3)
        clear_all(self)


class V03_Subtractors(Scene):
    def construct(self):
        cap = new_page(self, "3. Half Subtractor")
        say(self, 'A half subtractor computes A minus B with no borrow-in. The difference is A ex-or B, which is one when the inputs differ. The borrow is A prime B. It is one only when A is zero and B is one, because zero minus one needs a borrow.')
        tb = table([["A", "B", "D", "Bout"]] + [[a, b, a ^ b, int(a == 0 and b == 1)] for a in (0, 1) for b in (0, 1)],
                   xs=[-5.4, -4.6, -3.4, -2.4], y0=1.6, dy=0.6, size=28)
        show_table(self, tb)
        self.play(Create(SurroundingRectangle(tb[2], color=RED)))
        e = VGroup(M("D    = A ⊕ B", 28, GREEN), M("Bout = A'B", 28, GREEN)).arrange(DOWN, aligned_edge=LEFT).move_to([2.3, 1.0, 0])
        self.play(Write(e))
        n = VGroup(T("Difference = 1 when inputs differ", 24), T("Borrow only for 0 − 1", 24, RED)).arrange(
            DOWN, aligned_edge=LEFT).move_to([2.3, -0.6, 0])
        self.play(FadeIn(n))
        cap.say("Half subtractor computes A − B with no borrow-in.", 2.5)

        cap = new_page(self, "Full Subtractor:  A − B − Bin")
        say(self, 'A full subtractor computes A minus B minus borrow-in. The difference is A ex-or B ex-or borrow-in. The borrow-out is one whenever the result is negative. That happens in three cases: A is zero and B is one; A is zero and borrow-in is one; or B and borrow-in are both one. So borrow-out equals A prime B, plus A prime borrow-in, plus B borrow-in.')
        rows = [[a, b, bi, a ^ b ^ bi, int(a - b - bi < 0)] for a in (0, 1) for b in (0, 1) for bi in (0, 1)]
        tb = table([["A", "B", "Bin", "D", "Bout"]] + rows, xs=[-5.6, -4.9, -4.1, -3.0, -2.0], y0=2.2, dy=0.5, size=26)
        show_table(self, tb, lag=0.08)
        e = VGroup(M("D    = A ⊕ B ⊕ Bin", 26, GREEN), M("Bout = A'B + A'·Bin + B·Bin", 26, GREEN)).arrange(
            DOWN, aligned_edge=LEFT, buff=0.2).move_to([2.6, 1.6, 0])
        self.play(Write(e))
        cases = VGroup(T("Borrow-out = 1 whenever the result is negative:", 24, ORANGE),
                       T("•  A = 0 and B = 1             → A'B", 24),
                       T("•  A = 0 and Bin = 1  (0−0−1)  → A'·Bin", 24),
                       T("•  B = 1 and Bin = 1  (1−1−1)  → B·Bin", 24)).arrange(DOWN, aligned_edge=LEFT, buff=0.2)
        cases.move_to([2.6, -0.4, 0])
        fit(cases, 7.0)
        hb = VGroup(*[SurroundingRectangle(tb[i + 1][4], color=ORANGE, buff=0.08) for i, r in enumerate(rows) if r[4]])
        self.play(Create(hb))
        for cs in cases:
            self.play(FadeIn(cs, shift=RIGHT * 0.2), run_time=0.6)
        self.wait(2.5)

        cap = new_page(self, "Adder-Subtractor (2's complement)")
        say(self, "An adder-subtractor uses ex-or gates controlled by a mode line, M. When M is zero, B passes through unchanged and the circuit adds. When M is one, the ex-or gates invert B, and M also acts as the carry-in. So the circuit computes A plus the two's complement of B, which is A minus B.")
        xors = VGroup(*[block("XOR", 1.0, 0.7, PINK, 20) for _ in range(4)]).arrange(LEFT, buff=1.1).shift(UP * 1.2)
        adder = Rectangle(width=9.0, height=1.0, color=BLUE_B).shift(DOWN * 0.6)
        adder_t = T("4-bit parallel adder", 24, BLUE_B).move_to(adder)
        self.play(FadeIn(xors), Create(adder), FadeIn(adder_t))
        bl = VGroup()
        for i, x in enumerate(xors):
            bl.add(Line(x.get_top() + UP * 1.0, x.get_top(), stroke_width=3), T(f"B{i}", 20).next_to(x, UP, buff=1.05))
            bl.add(Arrow(x.get_bottom(), [x.get_center()[0], adder.get_top()[1], 0], buff=0, stroke_width=3,
                         max_tip_length_to_length_ratio=0.2))
        mline = wire([[6.0, 2.0, 0], [-5.6, 2.0, 0]], ORANGE)
        mdrops = VGroup(*[wire([[x.get_right()[0] + 0.2, 2.0, 0], [x.get_right()[0] + 0.2, x.get_center()[1], 0],
                                x.get_right()], ORANGE) for x in xors])
        mcin = wire([[6.0, 2.0, 0], [6.0, -0.6, 0], adder.get_right()], ORANGE)
        mlbl = T("M", 28, ORANGE).move_to([6.35, 2.0, 0])
        cin_l = T("Cin", 18, ORANGE).next_to(adder.get_right(), UP, buff=0.05).shift(RIGHT * 0.3)
        self.play(Create(bl))
        self.play(Create(mline), Create(mdrops), Create(mcin), FadeIn(mlbl), FadeIn(cin_l))
        modes = VGroup(T("M = 0 →  B passes unchanged, Cin = 0  →  A + B", 26, GREEN),
                       T("M = 1 →  XOR inverts B, Cin = 1  →  A + B' + 1 = A − B", 26, ORANGE)).arrange(
            DOWN, aligned_edge=LEFT, buff=0.2).shift(DOWN * 2.1)
        self.play(FadeIn(modes[0]))
        self.play(FadeIn(modes[1]))
        cap.say("M acts both as the XOR control and as the carry-in.", 2.5)

        cap = new_page(self, "Example:  5 − 3  using 2's complement")
        say(self, 'For example, five minus three. Three is zero zero one one. Invert it to get one one zero zero, and add one to get one one zero one, which is minus three. Add that to five, zero one zero one, and we get one zero zero one zero. Drop the final carry, and the answer is zero zero one zero, which is two.')
        steps = VGroup(M("B = 0011  (3)", 32),
                       M("invert  → 1100", 32),
                       M("add 1   → 1101   (= −3)", 32, ORANGE),
                       M("  0101   (5)", 32),
                       M("+ 1101  (−3)", 32),
                       M("────────", 32),
                       M("1 0010  → drop carry → 0010 = 2", 32, GREEN)).arrange(DOWN, aligned_edge=LEFT, buff=0.18)
        steps.move_to([0, -0.2, 0])
        for s in steps:
            self.play(FadeIn(s, shift=RIGHT * 0.2), run_time=0.6)
        cap.say("2's complement: invert all bits and add 1 — subtraction reuses the adder.", 3)
        clear_all(self)


class V04_Overflow(Scene):
    def add_cols(self, a, b, n, center):
        dx = 0.6
        x0 = center[0] + 1.5 * dx
        y = center[1]
        carry = [0] * (n + 1)
        for i in range(n):
            s = (a >> i & 1) + (b >> i & 1) + carry[i]
            carry[i + 1] = s >> 1
        ra = VGroup(*[M(str(a >> i & 1), 34).move_to([x0 - i * dx, y, 0]) for i in range(n)])
        rb = VGroup(*[M(str(b >> i & 1), 34).move_to([x0 - i * dx, y - 0.6, 0]) for i in range(n)])
        plus = M("+", 34).move_to([x0 - n * dx, y - 0.6, 0])
        rule = Line([x0 - n * dx - 0.3, y - 0.95, 0], [x0 + 0.3, y - 0.95, 0])
        self.play(FadeIn(ra), FadeIn(rb), FadeIn(plus), Create(rule))
        sums, cars = VGroup(), {}
        for i in range(n):
            s = ((a >> i & 1) + (b >> i & 1) + carry[i]) & 1
            d = M(str(s), 34, GREEN).move_to([x0 - i * dx, y - 1.35, 0])
            anims = [FadeIn(d)]
            if carry[i + 1]:
                cdig = M("1", 22, ORANGE).move_to([x0 - (i + 1) * dx, y + 0.5, 0])
                cars[i + 1] = cdig
                anims.append(FadeIn(cdig, shift=LEFT * 0.2))
            self.play(*anims, run_time=0.45)
            sums.add(d)
        cout = M(str(carry[n]), 34, RED if carry[n] else GREY).move_to([x0 - n * dx, y - 1.35, 0])
        self.play(FadeIn(cout))
        return carry, sums, cout, cars

    def construct(self):
        cap = new_page(self, "4. Overflow — Unsigned")
        say(self, 'Overflow. For unsigned numbers, overflow means the result needs more bits than are available. Twelve plus six is eighteen, which does not fit in four bits. It is signalled by a carry out of the most significant bit.')
        carry, sums, cout, _ = self.add_cols(0b1100, 0b0110, 4, [-4.6, 1.2, 0])
        self.play(Indicate(cout, color=RED, scale_factor=1.5))
        info = VGroup(T("12 + 6 = 18  >  15  (4-bit max)", 28),
                      T("Carry out of the MSB  ⇒  unsigned overflow", 28, RED)).arrange(DOWN, aligned_edge=LEFT)
        info.move_to([2.0, 0.6, 0])
        self.play(FadeIn(info))
        cap.say("Unsigned overflow: the result needs more bits than are available.", 3)

        cap = new_page(self, "Overflow — Signed (2's complement)")
        say(self, "For signed, two's complement numbers, overflow occurs when the carry into the most significant bit differs from the carry out of it. Plus six plus plus three should be plus nine, but the result, one zero zero one, reads as minus seven. The carry into the M S B is one and the carry out is zero. Overflow is their ex-or, which is one.")
        carry, sums, cout, cars = self.add_cols(0b0110, 0b0011, 4, [-4.6, 1.2, 0])
        cin_msb = cars.get(3)
        if cin_msb is not None:
            self.play(Circumscribe(cin_msb, color=YELLOW, shape=Circle))
        self.play(Circumscribe(cout, color=YELLOW, shape=Circle))
        info = VGroup(T("+6 + (+3) = +9 … but 1001 reads as −7!", 26),
                      T(f"Carry INTO MSB  C(n−1) = {carry[3]}", 26, ORANGE),
                      T(f"Carry OUT of MSB  C(n) = {carry[4]}", 26, ORANGE),
                      M("Overflow = C(n−1) ⊕ C(n) = 1", 28, RED)).arrange(DOWN, aligned_edge=LEFT, buff=0.25)
        info.move_to([2.0, 0.6, 0])
        for i in info:
            self.play(FadeIn(i, shift=RIGHT * 0.2), run_time=0.6)
        cap.say("Signed overflow occurs when the carry into the MSB differs from the carry out.", 3.5)
        clear_all(self)


class V05_Mux(Scene):
    def construct(self):
        cap = new_page(self, "5. Multiplexer (4:1 MUX)")
        say(self, 'A multiplexer selects one of many data inputs using select lines, and sends it to a single output. A mux with n select lines has two to the n data inputs, so a four to one mux has four inputs, two select lines and one output. As the select lines step through zero zero, zero one, one zero and one one, the output follows I zero, I one, I two and I three.')
        body = Polygon([-1, 1.8, 0], [-1, -1.8, 0], [1, -1.0, 0], [1, 1.0, 0], color=BLUE_B, stroke_width=3).shift(LEFT * 1.5)
        mux_t = T("MUX", 26, BLUE_B).move_to(body)
        vals = [1, 0, 1, 1]
        ins, in_pts = VGroup(), []
        for i in range(4):
            y = 1.2 - i * 0.8
            p = np.array([-2.5, y, 0])
            in_pts.append(p)
            ins.add(Line(p + LEFT * 1.4, p, stroke_width=3), T(f"I{i} = {vals[i]}", 22).next_to(p + LEFT * 1.4, LEFT, buff=0.1))
        outp = np.array([-0.5, 0, 0])
        out_line = Line(outp, outp + RIGHT * 1.5, stroke_width=3)
        sels = VGroup(Line([-1.8, -2.6, 0], [-1.8, -1.55, 0], stroke_width=3), Line([-1.2, -2.6, 0], [-1.2, -1.3, 0], stroke_width=3))
        self.play(Create(body), FadeIn(mux_t), Create(ins), Create(out_line), Create(sels))
        sel_lbl = T("S1 S0 = 00", 24, ORANGE).move_to([-1.5, -2.95, 0])
        y_lbl = T("Y = 1", 28, GREEN).next_to(out_line, RIGHT)
        self.play(FadeIn(sel_lbl), FadeIn(y_lbl))
        eq = VGroup(M("Y = S1'S0'I0 + S1'S0I1", 24, GREEN), M("  + S1S0'I2 + S1S0I3", 24, GREEN)).arrange(
            DOWN, aligned_edge=LEFT).move_to([3.9, 1.2, 0])
        self.play(Write(eq))
        path = None
        for s in range(4):
            new_path = wire([in_pts[s], [-1.6, in_pts[s][1], 0], [-1.0, 0, 0], outp], YELLOW, 5)
            anims = [Transform(sel_lbl, T(f"S1 S0 = {bits(s, 2)}", 24, ORANGE).move_to(sel_lbl)),
                     Transform(y_lbl, T(f"Y = I{s} = {vals[s]}", 28, GREEN).next_to(out_line, RIGHT))]
            if path is None:
                path = new_path
                anims.append(Create(path))
            else:
                anims.append(Transform(path, new_path))
            self.play(*anims, run_time=0.8)
            self.wait(0.6)
        say(self, 'A two to one mux is simply: Y equals S prime A, plus S B.')
        facts = VGroup(T("n select lines → 2ⁿ data inputs", 24),
                       T("4:1 MUX: 4 inputs, 2 selects, 1 output", 24),
                       M("2:1 MUX:  Y = S'·A + S·B", 24, GREEN)).arrange(DOWN, aligned_edge=LEFT, buff=0.2).move_to([3.9, -1.3, 0])
        self.play(FadeIn(facts))
        cap.say("A MUX selects ONE of many inputs and sends it to a single output.", 3)

        cap = new_page(self, "Demultiplexer (1:4 DEMUX)")
        say(self, 'A demultiplexer does the reverse. It routes one input to one of many outputs, chosen by the select lines. A mux can also implement a Boolean function: connect the variables to the select lines, and constants or variables to the data inputs.')
        body = Polygon([-1, 1.0, 0], [-1, -1.0, 0], [1, -1.8, 0], [1, 1.8, 0], color=PINK, stroke_width=3).shift(LEFT * 1.0)
        self.play(Create(body), FadeIn(T("DEMUX", 22, PINK).move_to(body)))
        inl = Line([-3.5, 0, 0], [-2.0, 0, 0], stroke_width=3)
        din = T("D", 26).next_to(inl, LEFT)
        outs = VGroup()
        lamps = VGroup()
        for i in range(4):
            y = 1.2 - i * 0.8
            outs.add(Line([0, y, 0], [1.5, y, 0], stroke_width=3), T(f"Y{i}", 22).move_to([2.3, y, 0]))
            lamps.add(lamp(False).move_to([1.8, y, 0]))
        self.play(Create(inl), FadeIn(din), Create(outs), FadeIn(lamps))
        sel = T("S1 S0 = 00", 24, ORANGE).move_to([-1.0, -2.4, 0])
        self.play(FadeIn(sel))
        for s in range(4):
            new = VGroup(*[lamp(i == s).move_to(lamps[i]) for i in range(4)])
            self.play(Transform(lamps, new), Transform(sel, T(f"S1 S0 = {bits(s, 2)}", 24, ORANGE).move_to(sel)), run_time=0.6)
            self.wait(0.4)
        n = VGroup(T("DEMUX = reverse of MUX:", 24), T("one input → one of many", 24),
                   T("outputs (chosen by selects)", 24), T(" ", 12),
                   T("MUX as logic implementer:", 24, YELLOW),
                   T("variables → select lines", 24), T("constants / vars → data inputs", 24)).arrange(
            DOWN, aligned_edge=LEFT, buff=0.15)
        fit(n, 4.3).move_to([5.0, 0.2, 0])
        self.play(FadeIn(n))
        self.wait(3)
        clear_all(self)


class V06_Decoder(Scene):
    def construct(self):
        cap = new_page(self, "6. 2-to-4 Decoder")
        say(self, 'A decoder converts an n-bit input into up to two to the n outputs, with exactly one output active for each input code. In a two to four decoder, Y zero is A prime B prime, Y one is A prime B, Y two is A B prime, and Y three is A B. Each output is a minterm of the inputs.')
        box = Rectangle(width=2.0, height=3.4, color=BLUE_B).shift(LEFT * 1.5)
        self.play(Create(box), FadeIn(T("2:4\nDEC", 26, BLUE_B).move_to(box)))
        a_l = VGroup(Line([-4.0, 0.6, 0], box.get_left() + UP * 0.6), Line([-4.0, -0.6, 0], box.get_left() + DOWN * 0.6))
        a_t = T("A = 0", 24).move_to([-4.8, 0.6, 0])
        b_t = T("B = 0", 24).move_to([-4.8, -0.6, 0])
        self.play(Create(a_l), FadeIn(a_t), FadeIn(b_t))
        exprs = ["A'B'", "A'B", "AB'", "AB"]
        lamps, outs = VGroup(), VGroup()
        for i in range(4):
            y = 1.2 - i * 0.8
            outs.add(Line([box.get_right()[0], y, 0], [0.9, y, 0]), T(f"Y{i}", 22).move_to([1.5, y, 0]),
                     M(f"= {exprs[i]}", 22, GREEN).move_to([2.6, y, 0], aligned_edge=LEFT))
            lamps.add(lamp(i == 0).move_to([1.1, y, 0]))
        self.play(Create(outs), FadeIn(lamps))
        for v in range(1, 4):
            a, b = v >> 1, v & 1
            new = VGroup(*[lamp(i == v).move_to(lamps[i]) for i in range(4)])
            self.play(Transform(lamps, new), Transform(a_t, T(f"A = {a}", 24).move_to(a_t)),
                      Transform(b_t, T(f"B = {b}", 24).move_to(b_t)), run_time=0.6)
            self.wait(0.5)
        cap.say("Exactly one output is active for each input code — each output is a minterm.", 2.5)
        say(self, 'With an enable input, when the decoder is disabled, all of its outputs are off.')
        en = T("EN = 0", 24, RED).next_to(box, DOWN, buff=0.3)
        self.play(FadeIn(en), Transform(lamps, VGroup(*[lamp(False).move_to(lamps[i]) for i in range(4)])))
        cap.say("Enable input: when disabled, ALL outputs are off.", 2.5)

        cap = new_page(self, "Decoder Facts")
        say(self, 'Two two-to-four decoders with enables can be combined into a three-to-eight decoder. A decoder turns an input code into one active line, while a mux picks one data input and passes it to a single output. To build a Boolean function with a decoder, OR together the minterm outputs you need. For example, Y one plus Y two gives A ex-or B.')
        pts = VGroup(
            T("•  n inputs → up to 2ⁿ outputs (one active per code)", 26),
            T("•  Two 2-to-4 decoders + enables → one 3-to-8 decoder", 26),
            T("   (MSB enables the upper decoder, its complement the lower)", 22, GREY_B),
            T("•  Decoder vs MUX: decoder turns a code into ONE active line;", 26),
            T("   a MUX passes ONE data input to a single output", 26),
            T("•  Boolean function = OR of the needed minterm outputs", 26, YELLOW),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.22).shift(UP * 0.7)
        fit(pts, 13)
        for p in pts:
            self.play(FadeIn(p, shift=RIGHT * 0.2), run_time=0.55)
        ex = VGroup(M("F = Σm(1, 2)  →  Y1 + Y2 = A'B + AB' = A ⊕ B", 26, GREEN)).shift(DOWN * 2.3)
        self.play(Write(ex))
        self.wait(2.5)
        clear_all(self)


class V07_PriorityEncoder(Scene):
    def construct(self):
        cap = new_page(self, "Encoders — why priority is needed")
        say(self, 'An encoder does the opposite of a decoder: it converts one active input line into a binary code. But a plain encoder gives a wrong, mixed code when two inputs are active together. Here inputs one and two are both active, and the output, one one, claims input three. A priority encoder fixes this by outputting the code of only the highest active input.')
        c = code("module encoder4to2(input [3:0] in, output [1:0] out);\n"
                 "  assign out[1] = in[2] | in[3];\n"
                 "  assign out[0] = in[1] | in[3];\nendmodule", width=9).shift(UP * 1.2)
        self.play(FadeIn(c))
        ex = VGroup(T("in = 0110  (In1 and In2 both active)", 26),
                    T("out = 11  → claims In3!  Wrong / mixed code", 26, RED),
                    T("Priority encoder: output the code of the HIGHEST active input only", 26, GREEN)
                    ).arrange(DOWN, buff=0.3).shift(DOWN * 1.3)
        for e in ex:
            self.play(FadeIn(e, shift=UP * 0.2), run_time=0.7)
            self.wait(0.6)
        self.wait(1)

        cap = new_page(self, "6A. 9-line Priority Encoder (In9 … In0 → Y4 Y3 Y2 Y1)")
        say(self, "In the nine-line priority encoder from experiment six, the output bits are the binary index of the highest active input. Inputs below it have no effect, so they are don't cares. For example, input six active gives zero one one zero. Notice the output is zero zero zero zero both when only input zero is active and when no input is active, so real designs add a valid output to tell them apart.")
        n_in = 10
        cells, labels = VGroup(), VGroup()
        for k in range(n_in):
            idx = 9 - k
            sq = Square(0.7, color=GREY_B, stroke_width=2).move_to([-5.4 + k * 0.85, 1.3, 0])
            cells.add(sq)
            labels.add(T(f"In{idx}", 18, GREY_B).next_to(sq, UP, buff=0.1))
        vals = VGroup(*[T("0", 26).move_to(cells[k]) for k in range(n_in)])
        outs = VGroup(*[Square(0.8, color=GREEN, stroke_width=2).move_to([-1.3 + j * 1.0, -1.0, 0]) for j in range(4)])
        olbl = VGroup(*[T(f"Y{4 - j}", 20, GREEN).next_to(outs[j], UP, buff=0.1) for j in range(4)])
        ovals = VGroup(*[T("0", 30, GREEN).move_to(outs[j]) for j in range(4)])
        self.play(FadeIn(cells), FadeIn(labels), FadeIn(vals))
        self.play(FadeIn(outs), FadeIn(olbl), FadeIn(ovals))
        ring = None
        desc = None
        examples = [{2, 5}, {0, 1, 6}, {3, 9}, {4, 7, 2}, {0}, set()]
        for act in examples:
            hi = max(act) if act else None
            new_vals = VGroup()
            for k in range(n_in):
                idx = 9 - k
                if idx in act:
                    s = "1"
                    col = YELLOW if idx == hi else ORANGE
                elif hi is not None and idx < hi:
                    s, col = "X", GREY
                else:
                    s, col = "0", WHITE
                new_vals.add(T(s, 26, col).move_to(cells[k]))
            code_v = hi if hi is not None else 0
            nov = VGroup(*[T(bits(code_v, 4)[j], 30, GREEN).move_to(outs[j]) for j in range(4)])
            txt = (f"highest active = In{hi}  →  {bits(code_v, 4)} = {code_v}" if hi is not None
                   else "no input active  →  0000  (same as In0!)")
            nd = T(txt, 26, YELLOW).shift(DOWN * 2.3)
            anims = [Transform(vals, new_vals), Transform(ovals, nov)]
            anims.append(Transform(desc, nd) if desc else FadeIn(nd))
            desc = desc or nd
            new_ring = SurroundingRectangle(cells[9 - hi], color=YELLOW, buff=0.06) if hi is not None else \
                SurroundingRectangle(cells, color=RED, buff=0.06)
            if ring is None:
                ring = new_ring
                anims.append(Create(ring))
            else:
                anims.append(Transform(ring, new_ring))
            self.play(*anims, run_time=0.8)
            self.wait(1.2)
        cap.say("Inputs below the highest active one are don't-cares (X). A 'valid' output separates In0 from 'none'.", 3)

        cap = new_page(self, "6B. Priority Encoder Expressions")
        say(self, "Each output is one when the highest active input has that bit set. Y four covers inputs eight and nine. Y three covers four to seven. Y two covers two, three, six and seven. And Y one covers the odd inputs. Nine inputs need four output bits, because two cubed, which is eight, is too small. The lab sheet's table uses inputs zero to nine but the circuit uses one to nine, so check which version your teacher expects.")
        ex = VGroup(
            M("Y4 = I8 + I9", 24, GREEN),
            M("Y3 = (I4+I5+I6+I7)·(I8+I9)'", 24, GREEN),
            M("Y2 = (I6+I7)·(I8+I9)' + (I2+I3)·(I4+…+I9)'", 24, GREEN),
            M("Y1 = I9 + I7·(I8+I9)' + I5·(I6+…+I9)'", 24, GREEN),
            M("        + I3·(I4+…+I9)' + I1·(I2+…+I9)'", 24, GREEN),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.25).shift(UP * 0.8)
        fit(ex, 12.5)
        for e in ex:
            self.play(FadeIn(e, shift=RIGHT * 0.2), run_time=0.6)
        notes = VGroup(T("Y4 → 8, 9    Y3 → 4–7    Y2 → 2, 3, 6, 7    Y1 → odd: 1, 3, 5, 7, 9", 24, YELLOW),
                       T("9 inputs need 4 output bits:  2³ = 8 too small, 2⁴ = 16 enough", 24),
                       T("Lab sheet: table uses In0–In9, circuit uses In1–In9 — check which your teacher expects", 20, GREY_B)
                       ).arrange(DOWN, buff=0.2).shift(DOWN * 1.9)
        fit(notes, 13)
        self.play(FadeIn(notes))
        self.wait(4)
        clear_all(self)


SEG = {0: "abcdef", 1: "bc", 2: "abdeg", 3: "abcdg", 4: "bcfg", 5: "acdfg", 6: "acdefg", 7: "abc", 8: "abcdefg", 9: "abcdfg"}


def seven_seg(center, on="", color=RED, scale=1.0):
    L, Th = 1.0, 0.2
    pos = {"a": (0, 1.2, 0), "g": (0, 0, 0), "d": (0, -1.2, 0),
           "f": (-0.6, 0.6, 1), "b": (0.6, 0.6, 1), "e": (-0.6, -0.6, 1), "c": (0.6, -0.6, 1)}
    g = VGroup()
    for k in "abcdefg":
        x, y, vert = pos[k]
        r = RoundedRectangle(width=Th if vert else L, height=L if vert else Th, corner_radius=Th / 2,
                             stroke_width=1, stroke_color=GREY_D)
        r.set_fill(color if k in on else "#2a2a33", opacity=1).move_to([x, y, 0])
        r.name = k
        g.add(r)
    return g.scale(scale).move_to(center)


class V08_SevenSeg(Scene):
    def construct(self):
        cap = new_page(self, "7. BCD to 7-Segment Converter")
        say(self, "A B C D to seven segment converter takes a four-bit B C D input, with A as the most significant bit and D as the least, and drives the seven segments, a to g. Here are the digits zero to nine. Codes ten to fifteen are invalid B C D, so they are treated as don't cares.")
        disp = seven_seg([-3.5, 0.2, 0], SEG[0], scale=1.3)
        names = VGroup(*[T(k, 20, GREY_B).next_to(disp[i], LEFT if k in "fe" else (RIGHT if k in "bc" else UP), buff=0.12)
                         for i, k in enumerate("abcdefg")])
        self.play(FadeIn(disp), FadeIn(names))
        bcd = M("ABCD = 0000", 30, YELLOW).move_to([1.5, 1.6, 0])
        dig = T("digit 0", 30).move_to([1.5, 0.9, 0])
        segs = M("on: abcdef", 26, RED).move_to([1.5, 0.2, 0])
        self.play(FadeIn(bcd), FadeIn(dig), FadeIn(segs))
        for d in range(1, 10):
            new = seven_seg(disp.get_center(), SEG[d], scale=1.3)
            self.play(Transform(disp, new), Transform(bcd, M(f"ABCD = {bits(d, 4)}", 30, YELLOW).move_to(bcd)),
                      Transform(dig, T(f"digit {d}", 30).move_to(dig)),
                      Transform(segs, M(f"on: {SEG[d]}", 26, RED).move_to(segs)), run_time=0.45)
            self.wait(0.35)
        inv = T("1010 – 1111 are invalid BCD → don't cares", 24, GREY_B).move_to([1.5, -0.8, 0])
        self.play(FadeIn(inv))
        cap.say("A is the MSB, D the LSB. One truth table per segment, simplified with a K-map.", 3)

        cap = new_page(self, "Segment a — K-map")
        say(self, "Write a truth table for each segment, then simplify it with a K-map. For segment a, the ones and don't cares group into A, C, B D, and the four corners, B prime D prime. So a equals A plus C plus B D plus B prime D prime. That is for a common cathode display, where segments light when driven high. A common anode display lights when driven low, so the outputs are inverted.")
        gray = [0, 1, 3, 2]
        cw = 0.85
        cells = {}
        grid = VGroup()
        for r in range(4):
            for c in range(4):
                m = gray[r] * 4 + gray[c]
                sq = Square(cw, color=WHITE, stroke_width=2).move_to([c * cw, -r * cw, 0])
                v = "X" if m > 9 else ("1" if "a" in SEG[m] else "0")
                tv = T(v, 26, RED if v == "1" else GREY_B).move_to(sq)
                ti = T(str(m), 12, GREY).move_to(sq.get_corner(DR) + UL * 0.12)
                cells[m] = sq
                grid.add(sq, tv, ti)
        cl = VGroup(*[T(s, 20, YELLOW).move_to([c * cw, 0.62, 0]) for c, s in enumerate(["00", "01", "11", "10"])])
        rl = VGroup(*[T(s, 20, YELLOW).move_to([-0.7, -r * cw, 0]) for r, s in enumerate(["00", "01", "11", "10"])])
        corner = T("AB \\ CD", 16, YELLOW).move_to([-0.85, 0.95, 0])
        km = VGroup(grid, cl, rl, corner).move_to([-3.2, -0.2, 0])
        self.play(FadeIn(km))
        groups = [
            (VGroup(*[cells[m] for m in (12, 13, 15, 14, 8, 9, 11, 10)]), BLUE, "A  (rows 11, 10)"),
            (VGroup(*[cells[m] for m in (3, 2, 7, 6, 15, 14, 11, 10)]), GREEN, "C  (cols 11, 10)"),
            (VGroup(*[cells[m] for m in (5, 7, 13, 15)]), ORANGE, "BD  (centre quad)"),
        ]
        expl = VGroup()
        y = 1.6
        for grp, col, txt in groups:
            rect = SurroundingRectangle(grp, color=col, buff=0.04 + 0.04 * len(expl))
            t = T(txt, 24, col).move_to([3.4, y, 0], aligned_edge=LEFT).shift(LEFT * 1.5)
            self.play(Create(rect), FadeIn(t), run_time=0.8)
            expl.add(t)
            y -= 0.6
        corners = VGroup(*[SurroundingRectangle(cells[m], color=PINK, buff=0.1) for m in (0, 2, 8, 10)])
        t = T("B'D'  (four corners)", 24, PINK).move_to([3.4, y, 0], aligned_edge=LEFT).shift(LEFT * 1.5)
        self.play(Create(corners), FadeIn(t))
        res = M("a = A + C + BD + B'D'", 32, YELLOW).move_to([2.6, -1.3, 0])
        self.play(Write(res))
        cc = VGroup(T("Common cathode: segment ON when driven HIGH", 22),
                    T("Common anode: ON when LOW → outputs inverted", 22)).arrange(DOWN, aligned_edge=LEFT).move_to([2.6, -2.4, 0])
        self.play(FadeIn(cc))
        self.wait(3)
        clear_all(self)


class V09_Sequential(Scene):
    def construct(self):
        cap = new_page(self, "8. Latch vs Flip-Flop")
        say(self, 'A latch changes whenever its enable is active, so its output follows D the whole time the enable is high. A flip-flop changes only on the active clock edge, which makes it suitable for synchronous design.')
        n = 24
        clk = ([0] * 3 + [1] * 3) * 4
        d = [0, 0, 1, 1, 0, 1, 1, 0, 0, 1, 0, 1, 0, 0, 1, 1, 1, 0, 1, 0, 0, 0, 1, 1]
        latch, ff = [], []
        ql = qf = 0
        for t in range(n):
            if clk[t]:
                ql = d[t]
            if t > 0 and clk[t] and not clk[t - 1]:
                qf = d[t]
            latch.append(ql)
            ff.append(qf)
        x0, dx, h = -4.6, 0.4, 0.6
        rows = [("clk / EN", clk, WHITE), ("D", d, BLUE), ("Q latch", latch, ORANGE), ("Q flip-flop", ff, GREEN)]
        for i, (nm, lv, col) in enumerate(rows):
            y = 1.7 - i * 1.15
            self.play(FadeIn(T(nm, 22, col).move_to([x0 - 1.3, y + h / 2, 0])),
                      Create(waveform(lv, x0, y, dx, h, col)), run_time=1.2)
        edges = VGroup(*[DashedLine([x0 + t * dx, 2.4, 0], [x0 + t * dx, -1.8, 0], color=YELLOW, stroke_width=2)
                         for t in range(1, n) if clk[t] and not clk[t - 1]])
        self.play(Create(edges))
        cap.say("Latch: follows D whenever enable is active.  Flip-flop: changes ONLY on the clock edge.", 3.5)

        cap = new_page(self, "Flip-Flop Characteristic Equations")
        say(self, 'The characteristic equations. For a D flip-flop, Q next equals D. For a T flip-flop, Q next equals T ex-or Q. For a J K flip-flop, Q next equals J Q prime plus K prime Q. And for an S R flip-flop, with S and R never both one, Q next equals S plus R prime Q. A synchronous reset acts only on the active clock edge, while an asynchronous reset acts immediately. In a synchronous counter all flip-flops share one clock; in a ripple counter each is clocked by the previous stage, so it is slower.')
        et = expr_table([("D flip-flop", "Q+ = D"), ("T flip-flop", "Q+ = T ⊕ Q"),
                         ("JK flip-flop", "Q+ = JQ' + K'Q"), ("SR flip-flop (S·R = 0)", "Q+ = S + R'Q")], y0=1.8, dy=0.7, size=28)
        self.play(FadeIn(et[0]))
        self.play(LaggedStart(*[FadeIn(r, shift=RIGHT * 0.2) for r in et[1:]], lag_ratio=0.3), run_time=2)
        more = VGroup(T("Synchronous reset: acts only on the active clock edge", 24),
                      T("Asynchronous reset: acts immediately, whatever the clock", 24),
                      T("Sync counter: one shared clock · Async (ripple): each FF clocked by the previous → slower", 22, GREY_B)
                      ).arrange(DOWN, aligned_edge=LEFT, buff=0.2).shift(DOWN * 1.9)
        fit(more, 13)
        self.play(FadeIn(more))
        self.wait(3.5)

        cap = new_page(self, "SISO Shift Register")
        say(self, 'In a serial-in, serial-out shift register, data enters one bit at a time at one end, and leaves one bit at a time at the other, one bit per clock pulse.')
        boxes = VGroup(*[block(f"FF{i}", 1.3, 1.1, BLUE_B, 20) for i in range(4)]).arrange(RIGHT, buff=0.6).shift(UP * 0.4)
        self.play(FadeIn(boxes))
        links = VGroup(*[Arrow(boxes[i].get_right(), boxes[i + 1].get_left(), buff=0, stroke_width=3) for i in range(3)])
        sin = Arrow(boxes[0].get_left() + LEFT * 1.0, boxes[0].get_left(), buff=0, stroke_width=3)
        sout = Arrow(boxes[3].get_right(), boxes[3].get_right() + RIGHT * 1.0, buff=0, stroke_width=3)
        self.play(Create(links), GrowArrow(sin), GrowArrow(sout),
                  FadeIn(T("serial\nin", 20).next_to(sin, LEFT)), FadeIn(T("serial\nout", 20).next_to(sout, RIGHT)))
        stream = [1, 0, 1, 1, 0, 0, 0, 0]
        regs = [0, 0, 0, 0]
        vals = VGroup(*[T("0", 30, YELLOW).move_to(boxes[i][0].get_center() + DOWN * 0.25) for i in range(4)])
        for b in boxes:
            b[1].shift(UP * 0.25)
        self.play(FadeIn(vals))
        queue = M("in: " + " ".join(map(str, stream[:4])), 26, ORANGE).move_to([-4.6, -1.5, 0])
        outq = M("out:", 26, GREEN).move_to([3.5, -1.5, 0], aligned_edge=LEFT)
        clkc = T("clock 0", 24).move_to([0, -2.2, 0])
        self.play(FadeIn(queue), FadeIn(outq), FadeIn(clkc))
        outs = []
        for k, bit in enumerate(stream):
            outs.append(regs[3])
            regs = [bit] + regs[:3]
            nv = VGroup(*[T(str(regs[i]), 30, YELLOW).move_to(vals[i]) for i in range(4)])
            rem = stream[k + 1:4]
            self.play(Transform(vals, nv),
                      Transform(queue, M("in: " + " ".join(map(str, rem)), 26, ORANGE).move_to([-4.6, -1.5, 0])),
                      Transform(outq, M("out: " + " ".join(map(str, outs[4:] if k >= 4 else [])), 26, GREEN)
                                .move_to([3.5, -1.5, 0], aligned_edge=LEFT)),
                      Transform(clkc, T(f"clock {k + 1}", 24).move_to(clkc)), run_time=0.6)
            self.wait(0.3)
        cap.say("Data enters serially at one end and leaves serially at the other — one bit per clock.", 3)
        clear_all(self)


class V10_Verilog(Scene):
    def construct(self):
        cap = new_page(self, "9. Verilog — three modeling levels")
        say(self, 'Verilog has three modeling levels. Gate level builds circuits from primitive gates; it is close to the hardware but tedious for large designs. Dataflow uses assign statements and expressions, and is shorter for combinational logic. Behavioral uses always blocks and procedural statements.')
        lv = [("Gate-level", "and g1(y, a, b);", "primitive gates — close to hardware,\ntedious for big circuits"),
              ("Dataflow", "assign y = a & b;", "assign + expressions — short,\ngood for combinational logic"),
              ("Behavioral", "always @(*)\n  y = a & b;", "always blocks + procedural\nstatements")]
        cols = VGroup()
        for name, src, note in lv:
            cols.add(VGroup(T(name, 28, YELLOW), code(src, width=3.9, size=26), T(note, 24, GREY_A)).arrange(DOWN, buff=0.35))
        cols.arrange(RIGHT, buff=0.6, aligned_edge=UP).shift(UP * 0.2)
        fit(cols, 13)
        for c in cols:
            self.play(FadeIn(c, shift=UP * 0.2), run_time=0.8)
            self.wait(0.8)
        self.wait(1.5)

        cap = new_page(self, "wire vs reg  •  assign vs always")
        say(self, 'A wire is a net that is driven continuously, for example by assign. A reg holds a value and is assigned inside always or initial blocks; a reg cannot be driven by assign. Assign is continuous and used for combinational expressions, while always is procedural, for behavioral and sequential logic. The sensitivity list, at star, includes every signal read in the block. A case statement selects a branch by value, and the conditional operator is: condition, question mark, value one, colon, value two.')
        rows = VGroup(
            VGroup(T("wire", 30, BLUE_B), T("net, driven continuously (e.g. by assign)", 24)),
            VGroup(T("reg", 30, BLUE_B), T("holds a value; assigned inside always / initial", 24)),
            VGroup(T("", 10), T("a reg can NOT be driven by assign", 24, RED)),
            VGroup(T("assign", 30, GREEN), T("continuous → combinational expressions", 24)),
            VGroup(T("always", 30, GREEN), T("procedural → behavioral & sequential logic", 24)),
            VGroup(T("@(*)", 30, ORANGE), T("sensitivity list = every signal read → no missed inputs", 24)),
            VGroup(T("case / ?:", 30, ORANGE), T("select by value (MUX, decoder);  cond ? v1 : v2", 24)),
        )
        for i, r in enumerate(rows):
            r[0].move_to([-4.6, 2.0 - i * 0.62, 0], aligned_edge=LEFT)
            r[1].move_to([-2.2, 2.0 - i * 0.62, 0], aligned_edge=LEFT)
            fit(r[1], 8.5)
            r[1].move_to([-2.2, 2.0 - i * 0.62, 0], aligned_edge=LEFT)
            self.play(FadeIn(r, shift=RIGHT * 0.2), run_time=0.55)
        self.wait(2.5)

        cap = new_page(self, "Blocking ( = ) vs Non-blocking ( <= )")
        say(self, "Blocking assignments, written with equals, run in order. Non-blocking assignments, written less-than equals, read all the right-hand sides first and then update together. So the non-blocking version swaps a and b, but the blocking version makes both equal to b's old value. Use non-blocking for clocked logic, and blocking for combinational logic.")
        nb = code("always @(posedge clk) begin\n  a <= b;\n  b <= a;\nend", width=5.6, size=22).move_to([-3.4, 1.6, 0])
        bl = code("always @(*) begin\n  a = b;\n  b = a;\nend", width=5.6, size=22).move_to([3.4, 1.6, 0])
        self.play(FadeIn(nb), FadeIn(bl))

        def regbox(nm, v, x, y, col):
            r = Square(0.8, color=col)
            return VGroup(r, T(str(v), 30, col).move_to(r), T(nm, 24).next_to(r, LEFT)).move_to([x, y, 0])

        na, nbx = regbox("a", 1, -4.2, -0.6, GREEN), regbox("b", 0, -2.4, -0.6, GREEN)
        ba, bb = regbox("a", 1, 2.6, -0.6, ORANGE), regbox("b", 0, 4.4, -0.6, ORANGE)
        self.play(FadeIn(na), FadeIn(nbx), FadeIn(ba), FadeIn(bb))
        s1 = T("read all RHS first: b=0, a=1", 20, GREY_A).move_to([-3.4, -1.5, 0])
        self.play(FadeIn(s1))
        self.play(Transform(na[1], T("0", 30, GREEN).move_to(na[1])), Transform(nbx[1], T("1", 30, GREEN).move_to(nbx[1])))
        r1 = T("→ updated together: SWAPPED ✓", 22, GREEN).move_to([-3.4, -2.0, 0])
        self.play(FadeIn(r1))
        s2 = T("a = b  →  a = 0", 20, GREY_A).move_to([3.4, -1.5, 0])
        self.play(FadeIn(s2), Transform(ba[1], T("0", 30, ORANGE).move_to(ba[1])))
        s3 = T("b = a (new a)  →  b = 0", 20, GREY_A).move_to([3.4, -1.9, 0])
        self.play(FadeIn(s3), Transform(bb[1], T("0", 30, ORANGE).move_to(bb[1])))
        r2 = T("→ both become b's old value ✗", 22, RED).move_to([3.4, -2.35, 0])
        self.play(FadeIn(r2))
        cap.say("Use non-blocking (<=) for clocked logic and blocking (=) for combinational logic.", 3.5)

        cap = new_page(self, "Dataflow one-liners")
        say(self, 'Here are the dataflow one-liners for ex-or, the half adder, the full adder, the full subtractor, and a two to one mux using the conditional operator.')
        et = expr_table([("XOR", "assign y = a ^ b;"), ("Half adder", "sum = a ^ b; carry = a & b;"),
                         ("Full adder", "sum = a ^ b ^ cin;"), ("", "cout = (a & b) | (b & cin) | (a & cin);"),
                         ("Full subtractor", "diff = a ^ b ^ bin;"), ("", "bout = (~a & b) | (~a & bin) | (b & bin);"),
                         ("2:1 MUX", "assign y = s ? b : a;")], y0=2.0, size=24, left=-6.2, mid=-2.6)
        self.play(FadeIn(et[0]))
        self.play(LaggedStart(*[FadeIn(r, shift=RIGHT * 0.2) for r in et[1:]], lag_ratio=0.3), run_time=2.5)
        self.wait(3)

        snippets = [
            ("4:1 MUX — behavioral (case)",
             "module mux4to1(input [3:0] in, input [1:0] sel,\n                output reg y);\n  always @(*) begin\n"
             "    case (sel)\n      2'b00: y = in[0];\n      2'b01: y = in[1];\n      2'b10: y = in[2];\n"
             "      2'b11: y = in[3];\n      default: y = 1'b0;\n    endcase\n  end\nendmodule"),
            ("4:1 MUX — dataflow (conditional operator)",
             "module mux4to1_df(input i0, i1, i2, i3, input s1, s0,\n                  output y);\n"
             "  assign y = s1 ? (s0 ? i3 : i2) : (s0 ? i1 : i0);\nendmodule"),
            ("2-to-4 decoder",
             "module decoder2to4(input a, b, output y0, y1, y2, y3);\n  assign y0 = ~a & ~b;\n  assign y1 = ~a &  b;\n"
             "  assign y2 =  a & ~b;\n  assign y3 =  a &  b;\nendmodule"),
            ("4-to-2 priority encoder (highest wins)",
             "module priority_enc4to2(input [3:0] in, output reg [1:0] out);\n  always @(*) begin\n"
             "    if      (in[3]) out = 2'b11;\n    else if (in[2]) out = 2'b10;\n    else if (in[1]) out = 2'b01;\n"
             "    else            out = 2'b00;\n  end\nendmodule"),
            ("XOR gate — behavioral",
             "module xor_gate(input a, input b, output reg y);\n  always @(*) begin\n    if (a == b) y = 1'b0;\n"
             "    else        y = 1'b1;\n  end\nendmodule"),
            ("D flip-flop with synchronous reset",
             "module d_ff(input clk, rst, d, output reg q);\n  always @(posedge clk) begin\n    if (rst) q <= 1'b0;\n"
             "    else     q <= d;\n  end\nendmodule"),
        ]
        cur = None
        for title, src in snippets:
            h = heading(title, GREEN)
            c = code(src, width=11.5, size=22)
            if c.height > 5.6:
                c.set_height(5.6)
            c.next_to(h, DOWN, buff=0.35)
            say(self, VO_SNIPPETS[title])
            if cur is None:
                clear_all(self)
                self.play(FadeIn(h), FadeIn(c, shift=UP * 0.2))
            else:
                self.play(FadeOut(cur[0]), FadeOut(cur[1]), FadeIn(h), FadeIn(c, shift=UP * 0.2))
            cur = (h, c)
            self.wait(3.2)
        clear_all(self)


class V11_Testbench(Scene):
    def construct(self):
        cap = new_page(self, "10. Testbench for the Full Adder")
        say(self, 'A testbench is a Verilog module with no ports. It instantiates the design under test, generates the input stimulus, and displays or checks the outputs. Dump file names the waveform file, and dump vars chooses which signals to record, producing a V C D file that G T K Wave can open. Monitor prints automatically whenever a listed signal changes, while display prints once each time it runs. The for loop walks through all eight input combinations.')
        src = ("module tb_full_adder;\n  reg a, b, cin;\n  wire sum, cout;\n  integer i;\n\n"
               "  full_adder uut(.a(a), .b(b), .cin(cin),\n                 .sum(sum), .cout(cout));\n\n"
               "  initial begin\n    $dumpfile(\"fa.vcd\");\n    $dumpvars(0, tb_full_adder);\n"
               "    $monitor(\"t=%0t a=%b b=%b cin=%b sum=%b cout=%b\",\n             $time, a, b, cin, sum, cout);\n"
               "    for (i = 0; i < 8; i = i + 1) begin\n      {a, b, cin} = i;\n      #10;\n    end\n    $finish;\n  end\nendmodule")
        c = code(src, size=20)
        c.set_height(5.9)
        if c.width > 7.6:
            c.set_width(7.6)
        c.to_edge(LEFT, buff=0.3).shift(DOWN * 0.35)
        self.play(FadeIn(c))
        notes = VGroup(
            T("No ports — it wraps the design", 22, YELLOW),
            T("uut = design under test", 22),
            T("reg → driven stimulus; wire → outputs", 22),
            T("$dumpfile / $dumpvars → VCD file", 22, GREEN),
            T("   open it in GTKWave", 20, GREY_B),
            T("$monitor prints on every change", 22, ORANGE),
            T("$display prints once per execution", 22, ORANGE),
            T("{a,b,cin} = i walks all 8 inputs", 22),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.22)
        fit(notes, 13.4 - c.width - 0.6)
        notes.next_to(c, RIGHT, buff=0.35)
        for n in notes:
            self.play(FadeIn(n, shift=LEFT * 0.2), run_time=0.5)
        self.wait(3)

        cap = new_page(self, "Simulating with iverilog")
        say(self, 'To simulate, compile the design and testbench with i verilog, dash o sim, then run the simulation with V V P sim. Monitor prints a line for every input combination, and you can then open the V C D file in G T K Wave.')
        term = RoundedRectangle(width=12.5, height=5.6, corner_radius=0.15, color=GREY_D, fill_color="#111118",
                                fill_opacity=1).shift(DOWN * 0.4)
        self.play(FadeIn(term))
        lines = ["$ iverilog -o sim fa.v tb_fa.v     # compile design + testbench",
                 "$ vvp sim                          # run (creates fa.vcd)"]
        out = []
        for i in range(8):
            a, b, ci = i >> 2 & 1, i >> 1 & 1, i & 1
            out.append(f"t={i * 10} a={a} b={b} cin={ci} sum={a ^ b ^ ci} cout={int(a + b + ci >= 2)}")
        y = 1.95
        for ln in lines:
            t = M(ln, 22, GREEN).move_to([-5.9, y, 0], aligned_edge=LEFT)
            self.play(AddTextLetterByLetter(t), run_time=1.2)
            y -= 0.45
        for ln in out:
            t = M(ln, 22, GREY_A).move_to([-5.9, y, 0], aligned_edge=LEFT)
            self.play(FadeIn(t), run_time=0.3)
            y -= 0.4
        cap.say("Then open fa.vcd in GTKWave to see the waveforms.", 3)

        clear_all(self)
        say(self, "That's the whole cheat sheet. Good luck with your viva!")
        end = T("Good luck with the viva!", 48, YELLOW, weight=BOLD)
        self.play(Write(end))
        self.wait(2)
        sync(self)
        self.play(FadeOut(end))


VO_SNIPPETS = {
    '4:1 MUX — behavioral (case)':
        'A four to one mux in behavioral style uses a case statement on the select lines.',
    '4:1 MUX — dataflow (conditional operator)':
        'The same mux in dataflow style uses nested conditional operators.',
    '2-to-4 decoder':
        'A two to four decoder: each output is one minterm of a and b.',
    '4-to-2 priority encoder (highest wins)':
        'A four to two priority encoder checks the highest input first, using an if, else-if chain.',
    'XOR gate — behavioral':
        'A behavioral ex-or gate: the output is zero if the inputs are equal, otherwise one.',
    'D flip-flop with synchronous reset':
        'And a D flip-flop with synchronous reset, using non-blocking assignments on the positive clock edge.',
}


SCENE_ORDER = ["V01_Boolean", "V02_Adders", "V03_Subtractors", "V04_Overflow", "V05_Mux", "V06_Decoder",
               "V07_PriorityEncoder", "V08_SevenSeg", "V09_Sequential", "V10_Verilog", "V11_Testbench"]
