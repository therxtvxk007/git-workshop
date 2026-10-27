"""Manim video: Counters — introduction, asynchronous binary / non-binary
up and down counters (based on the DE & LD class notes).

Render all scenes (720p):
    manim -qm counters.py -a
then concatenate in SCENE_ORDER with ./render.sh.
"""

from manim import *

FONT = "DejaVu Sans"
SUB = "₀₁₂₃₄₅₆₇₈₉"

config.background_color = "#0d0d12"


# ---------------------------------------------------------------- helpers
def T(s, size=30, color=WHITE, **kw):
    return Text(s, font=FONT, font_size=size, color=color, **kw)


def heading(s, color=YELLOW):
    t = T(s, 40, color, weight=BOLD)
    if t.width > 12.5:
        t.set_width(12.5)
    t.to_edge(UP, buff=0.35)
    line = Line(t.get_corner(DL), t.get_corner(DR), color=color).shift(DOWN * 0.12)
    return VGroup(t, line)


def qbar(i, size=24, color=WHITE):
    q = T(f"Q{SUB[i]}", size, color)
    bar = Line(LEFT, RIGHT, color=color, stroke_width=2)
    bar.set_width(q.width * 0.55).next_to(q, UP, buff=0.04).align_to(q, LEFT)
    return VGroup(q, bar)


def bits(state, n=3):
    return format(state, f"0{n}b")


def anchor(p):
    return Dot(p, radius=0.01).set_opacity(0)


def wire(points, color=WHITE, sw=3):
    return VMobject(color=color, stroke_width=sw).set_points_as_corners(
        [np.array(p, dtype=float) for p in points]
    )


def jk_ff(i, neg_edge=True, clr=False, pre=False, color=RED_B):
    """JK flip-flop block with J=K=1 tied inputs."""
    box = Rectangle(width=1.6, height=2.0, color=WHITE, stroke_width=3)
    j = T(f"J{SUB[i]}", 22, color).move_to(box.get_corner(UL) + RIGHT * 0.3 + DOWN * 0.35)
    k = T(f"K{SUB[i]}", 22, color).move_to(box.get_corner(DL) + RIGHT * 0.3 + UP * 0.35)
    q = T(f"Q{SUB[i]}", 22, color).move_to(box.get_corner(UR) + LEFT * 0.3 + DOWN * 0.35)
    qb = qbar(i, 22, color).move_to(box.get_corner(DR) + LEFT * 0.3 + UP * 0.35)
    left = box.get_left()
    tri = Polygon(left + UP * 0.15, left + DOWN * 0.15, left + RIGHT * 0.22,
                  color=color, stroke_width=3)
    parts = VGroup(box, j, k, q, qb, tri)
    clk_pt = left
    if neg_edge:
        bub = Circle(radius=0.07, color=color, stroke_width=3).next_to(tri, LEFT, buff=0)
        parts.add(bub)
        clk_pt = bub.get_left()
    jl = Line(box.get_left() + UP * 0.65 + LEFT * 0.5, box.get_left() + UP * 0.65)
    kl = Line(box.get_left() + DOWN * 0.65 + LEFT * 0.5, box.get_left() + DOWN * 0.65)
    parts.add(jl, kl, T("1", 20).next_to(jl, UP, buff=0.05), T("1", 20).next_to(kl, UP, buff=0.05))
    bottom_pt, top_pt = box.get_bottom(), box.get_top()
    if clr:
        b = Circle(radius=0.07, color=PINK, stroke_width=3).next_to(box, DOWN, buff=0)
        parts.add(b, T("Clr", 16, PINK).next_to(b, LEFT, buff=0.05).shift(DOWN * 0.12))
        bottom_pt = b.get_bottom()
    if pre:
        b = Circle(radius=0.07, color=ORANGE, stroke_width=3).next_to(box, UP, buff=0)
        parts.add(b, T("Pr", 16, ORANGE).next_to(b, LEFT, buff=0.05).shift(UP * 0.12))
        top_pt = b.get_top()
    q_pt = box.get_right() + UP * 0.65
    for p in (clk_pt, q_pt, bottom_pt, top_pt):
        parts.add(anchor(p))
    # anchors are the last 4 submobjects: clk, q, bottom, top
    return parts


def ff_pt(ff, name):
    idx = {"clk": -4, "q": -3, "bottom": -2, "top": -1}[name]
    return ff[idx].get_center()


def ripple_chain(neg_edge=True, clr=False, pre=False, xs=(-3.6, 0.0, 3.6), y=0.8):
    ffs = VGroup(*[jk_ff(i, neg_edge, clr, pre) for i in range(3)])
    for ff, x in zip(ffs, xs):
        ff.move_to([x, y, 0])
    clk_in = Line(ff_pt(ffs[0], "clk") + LEFT * 1.0, ff_pt(ffs[0], "clk"), color=RED)
    clk_lbl = T("clk", 22, RED).next_to(clk_in, UP, buff=0.05).align_to(clk_in, LEFT)
    links = VGroup()
    for a, b in zip(ffs[:-1], ffs[1:]):
        qp, cp = ff_pt(a, "q"), ff_pt(b, "clk")
        mx = qp[0] + 0.45
        links.add(wire([qp, [mx, qp[1], 0], [mx, cp[1], 0], cp]))
    return ffs, VGroup(clk_in, clk_lbl), links


def and_gate(center, nand=False, color=PINK, w=0.9, h=0.8):
    c = np.array(center, dtype=float)
    l, r = c[0] - w / 2, c[0] + w / 2 - h / 2
    top, bot = c[1] + h / 2, c[1] - h / 2
    body = VMobject(color=color, stroke_width=3)
    body.set_points_as_corners([[r, top, 0], [l, top, 0], [l, bot, 0], [r, bot, 0]])
    arc = ArcBetweenPoints([r, bot, 0], [r, top, 0], angle=PI, color=color, stroke_width=3)
    g = VGroup(body, arc)
    out = np.array([r + h / 2, c[1], 0])
    if nand:
        b = Circle(radius=0.08, color=color, stroke_width=3).move_to(out + RIGHT * 0.08)
        g.add(b)
        out = out + RIGHT * 0.16
    g.in1 = np.array([l, c[1] + h / 4, 0])
    g.in2 = np.array([l, c[1] - h / 4, 0])
    g.out = out
    return g


def or_gate(center, nor=False, color=ORANGE, w=1.0, h=0.8):
    c = np.array(center, dtype=float)
    l, r = c[0] - w / 2, c[0] + w / 2
    top, bot = c[1] + h / 2, c[1] - h / 2
    back = ArcBetweenPoints([l, bot, 0], [l, top, 0], angle=-0.9, color=color, stroke_width=3)
    up = ArcBetweenPoints([l, top, 0], [r, c[1], 0], angle=-0.6, color=color, stroke_width=3)
    dn = ArcBetweenPoints([l, bot, 0], [r, c[1], 0], angle=0.6, color=color, stroke_width=3)
    g = VGroup(back, up, dn)
    out = np.array([r, c[1], 0])
    if nor:
        b = Circle(radius=0.08, color=color, stroke_width=3).move_to(out + RIGHT * 0.08)
        g.add(b)
        out = out + RIGHT * 0.16
    g.in1 = np.array([l + 0.12, c[1] + h / 4, 0])
    g.in2 = np.array([l + 0.12, c[1] - h / 4, 0])
    g.out = out
    return g


def waveform(levels, x0, y0, dx, h, color):
    pts = []
    for i, lv in enumerate(levels):
        x = x0 + i * dx
        if i > 0 and levels[i - 1] != lv:
            pts.append([x, y0 + levels[i - 1] * h, 0])
        pts.append([x, y0 + lv * h, 0])
    pts.append([x0 + len(levels) * dx, y0 + levels[-1] * h, 0])
    return VMobject(color=color, stroke_width=4).set_points_as_corners(pts)


def state_cycle(states, radius=1.3, color=GREEN, size=30):
    labels = VGroup()
    n = len(states)
    for i, s in enumerate(states):
        ang = PI / 2 - TAU * i / n
        labels.add(T(s, size, color).move_to(radius * np.array([np.cos(ang), np.sin(ang), 0])))
    arrows = VGroup()
    for i in range(n):
        a, b = labels[i], labels[(i + 1) % n]
        arrows.add(CurvedArrow(a.get_center(), b.get_center(), angle=-TAU / (n + 2),
                               color=color, stroke_width=3, tip_length=0.18)
                   .scale(0.55))
    return VGroup(labels, arrows)


class Caption:
    """Bottom-of-screen narration line."""

    def __init__(self, scene):
        self.scene, self.cur = scene, None

    def say(self, s, wait=2.0, color=GREY_A):
        new = T(s, 24, color).to_edge(DOWN, buff=0.3)
        if new.width > 13:
            new.set_width(13)
        if self.cur is None:
            self.scene.play(FadeIn(new, shift=UP * 0.2), run_time=0.6)
        else:
            self.scene.play(FadeOut(self.cur, shift=UP * 0.2), FadeIn(new, shift=UP * 0.2), run_time=0.6)
        self.cur = new
        self.scene.wait(wait)

    def clear(self):
        if self.cur is not None:
            self.scene.play(FadeOut(self.cur), run_time=0.4)
            self.cur = None


def clear_all(scene):
    scene.play(*[FadeOut(m) for m in scene.mobjects], run_time=0.8)


# ---------------------------------------------------------------- scenes
class S01_Intro(Scene):
    def construct(self):
        cap = Caption(self)
        title = T("Counters", 72, YELLOW, weight=BOLD)
        sub = T("Asynchronous Binary & Non-Binary  •  Up & Down Counters", 28, GREY_B)
        sub.next_to(title, DOWN, buff=0.4)
        self.play(Write(title), run_time=1.5)
        self.play(FadeIn(sub, shift=UP * 0.2))
        self.wait(1.5)
        self.play(FadeOut(sub), title.animate.scale(0.6).to_edge(UP, buff=0.35))

        b1 = T("•  A type of sequential circuit", 32).to_edge(LEFT, buff=1).shift(UP * 2)
        b2 = T("•  It counts the number of clock pulses", 32).next_to(b1, DOWN, aligned_edge=LEFT, buff=0.4)
        self.play(FadeIn(b1, shift=RIGHT * 0.3))
        self.play(FadeIn(b2, shift=RIGHT * 0.3))

        clk = waveform([0, 1] * 8, -5.5, -0.6, 0.55, 0.7, BLUE)
        self.play(Create(clk), run_time=2)
        count = T("0", 48, GREEN).next_to(clk, RIGHT, buff=0.5)
        self.add(count)
        for k in range(8):
            x = -5.5 + (2 * k + 1) * 0.55
            arr = Arrow([x, 0.5, 0], [x, 0.15, 0], color=GREEN, buff=0, stroke_width=4,
                        max_tip_length_to_length_ratio=0.4)
            self.play(FadeIn(arr, shift=DOWN * 0.1),
                      Transform(count, T(str(k + 1), 48, GREEN).move_to(count)), run_time=0.3)
        cap.say("Every clock edge advances the count by one.", 1.5)
        clear_all(self)
        cap.cur = None

        h = heading("n-bit counter")
        self.play(FadeIn(h))
        l1 = T("n-bit binary number  →  2ⁿ possible states", 34, ORANGE).shift(UP * 1.9)
        l2 = T("2-bit counter  →  2 flip-flops", 32).shift(UP * 0.9)
        l3 = T("n-bit counter  →  n flip-flops", 32).shift(UP * 0.1)
        self.play(Write(l1))
        self.play(FadeIn(l2, shift=UP * 0.2))
        self.play(FadeIn(l3, shift=UP * 0.2))
        self.wait(1)

        root = T("Counters", 32, RED).shift(DOWN * 1.0)
        up = T("Up counter", 30, RED).shift(DOWN * 2.3 + LEFT * 3)
        dn = T("Down counter", 30, RED).shift(DOWN * 2.3 + RIGHT * 3)
        e1 = Line(root.get_bottom(), up.get_top(), color=RED)
        e2 = Line(root.get_bottom(), dn.get_top(), color=RED)
        self.play(FadeIn(root), Create(e1), Create(e2), FadeIn(up), FadeIn(dn))
        cap.say("Counters count either upward or downward.", 2)
        clear_all(self)


class S02_UpDownModN(Scene):
    def construct(self):
        cap = Caption(self)
        h = heading("2-bit Up vs Down Counter")
        self.play(FadeIn(h))
        upc = state_cycle(["00", "01", "10", "11"]).shift(LEFT * 3.3 + UP * 0.2)
        dnc = state_cycle(["00", "11", "10", "01"]).shift(RIGHT * 3.3 + UP * 0.2)
        ul = T("Up counter", 30, GREEN).next_to(upc, DOWN, buff=0.5)
        dl = T("Down counter", 30, GREEN).next_to(dnc, DOWN, buff=0.5)
        self.play(Write(upc[0]), Write(dnc[0]))
        self.play(LaggedStart(*[Create(a) for a in upc[1]], lag_ratio=0.4),
                  LaggedStart(*[Create(a) for a in dnc[1]], lag_ratio=0.4), run_time=2.5)
        self.play(FadeIn(ul), FadeIn(dl))
        # highlight traversal
        for i in range(4):
            self.play(Indicate(upc[0][i], color=YELLOW), Indicate(dnc[0][i], color=YELLOW), run_time=0.5)
        cap.say("Up: 00 → 01 → 10 → 11 → 00     Down: 00 → 11 → 10 → 01 → 00", 2.5)
        clear_all(self)
        cap.cur = None

        h = heading("Mod-N Counter")
        self.play(FadeIn(h))
        l1 = T("A counter can be represented as a  Mod-N counter", 32, ORANGE).shift(UP * 2)
        l2 = T("N  =  number of states", 32, ORANGE).shift(UP * 1.2)
        l3 = T("2-bit counter  →  2² = 4 states  →  Mod-4 counter", 32).shift(UP * 0.2)
        self.play(Write(l1))
        self.play(FadeIn(l2, shift=UP * 0.2))
        self.play(FadeIn(l3, shift=UP * 0.2))
        f1 = T("2ⁿ = N", 40, YELLOW)
        f2 = T("n = log₂ N", 40, YELLOW)
        fg = VGroup(f1, f2).arrange(RIGHT, buff=1.5).shift(DOWN * 1.2)
        box = SurroundingRectangle(fg, color=YELLOW, buff=0.3)
        self.play(Write(f1))
        self.play(TransformFromCopy(f1, f2), Create(box))
        cap.say("n = number of flip-flops,  N = number of states", 2.5)
        clear_all(self)
        cap.cur = None

        h = heading("Example: Mod-6 Counter")
        self.play(FadeIn(h))
        steps = VGroup(
            T("n = log₂ 6", 36),
            T("n = 2.584", 36),
            T("n = 3  flip-flops   (always round up)", 36, YELLOW),
        ).arrange(DOWN, buff=0.6).shift(UP * 0.4)
        for s in steps:
            self.play(Write(s))
            self.wait(0.6)
        cap.say("2 flip-flops give only 4 states (< 6), so we need 3.", 2.5)
        clear_all(self)


class S03_BinaryNonBinary(Scene):
    def construct(self):
        cap = Caption(self)
        root = T("Counter", 34, YELLOW).shift(UP * 3.1)
        bl = T("Binary Counter", 32, YELLOW).shift(UP * 2.0 + LEFT * 3.5)
        nl = T("Non-Binary Counter", 32, YELLOW).shift(UP * 2.0 + RIGHT * 3.5)
        self.play(FadeIn(root))
        self.play(Create(Line(root.get_bottom(), bl.get_top(), color=YELLOW)),
                  Create(Line(root.get_bottom(), nl.get_top(), color=YELLOW)),
                  FadeIn(bl), FadeIn(nl))

        col = VGroup(*[T(bits(i), 26, WHITE) for i in range(8)]).arrange(DOWN, buff=0.15)
        col.next_to(bl, DOWN, buff=0.35)
        ret = CurvedArrow(col[-1].get_right() + RIGHT * 0.1, col[0].get_right() + RIGHT * 0.1,
                          angle=PI / 2, color=GREEN)
        self.play(LaggedStart(*[FadeIn(c, shift=DOWN * 0.1) for c in col], lag_ratio=0.2))
        self.play(Create(ret))
        note1 = T("3-bit: 2³ = 8\nexplores ALL\npossible states", 24, GREEN).next_to(col, LEFT, buff=0.6)
        self.play(FadeIn(note1))

        mod6 = VGroup(*[T(bits(i), 26, BLUE_B) for i in range(6)]).arrange(DOWN, buff=0.15)
        mod6.next_to(nl, DOWN, buff=0.35).shift(LEFT * 1.3)
        unused = VGroup(T("110", 26, GREY), T("111", 26, GREY)).arrange(DOWN, buff=0.15)
        unused.next_to(mod6, RIGHT, buff=1.0).align_to(mod6, DOWN)
        cross = Cross(unused, stroke_color=RED)
        ret2 = CurvedArrow(mod6[-1].get_left() + LEFT * 0.1, mod6[0].get_left() + LEFT * 0.1,
                           angle=-PI / 2, color=BLUE)
        self.play(LaggedStart(*[FadeIn(c, shift=DOWN * 0.1) for c in mod6], lag_ratio=0.2))
        self.play(Create(ret2), FadeIn(unused))
        self.play(Create(cross))
        note2 = T("Mod-6: does NOT explore\nall possible states", 24, BLUE_B).next_to(VGroup(mod6, unused), DOWN, buff=0.4)
        self.play(FadeIn(note2))
        cap.say("Non-binary counter: skips some of the 2ⁿ states.", 3)
        clear_all(self)
        cap.cur = None

        h = heading("Summary")
        self.play(FadeIn(h))
        r1 = T("2-bit counter  ⇒  N = 4  ⇒  Mod-4  ⇒  Binary counter", 32).shift(UP * 1.8)
        r2 = T("Mod-3, Mod-2 counters (n = 2)  ⇒  Non-binary counters", 32, ORANGE).shift(UP * 0.9)
        self.play(Write(r1))
        self.play(Write(r2))
        m3 = state_cycle(["00", "01", "10"], radius=0.9, color=ORANGE, size=26).shift(LEFT * 2.5 + DOWN * 1.3)
        m2 = state_cycle(["00", "01"], radius=0.7, color=ORANGE, size=26).shift(RIGHT * 2.5 + DOWN * 1.3)
        self.play(FadeIn(m3), FadeIn(m2))
        self.play(FadeIn(T("Mod-3", 24, GREY_B).next_to(m3, LEFT)),
                  FadeIn(T("Mod-2", 24, GREY_B).next_to(m2, RIGHT)))
        self.wait(3)
        clear_all(self)


class S04_AsyncVsSync(Scene):
    def construct(self):
        h = heading("Asynchronous vs Synchronous Counters")
        self.play(FadeIn(h))
        a = T("Asynchronous", 32, YELLOW).move_to([-3.4, 2.3, 0])
        s = T("Synchronous", 32, YELLOW).move_to([3.4, 2.3, 0])
        hl = Line([-6.6, 1.85, 0], [6.6, 1.85, 0])
        vl = Line([0, 2.7, 0], [0, -3.3, 0])
        self.play(FadeIn(a), FadeIn(s), Create(hl), Create(vl))
        rows = [
            ("No single clock for all FFs\n(ripple: each FF clocks the next)", "Single common clock for all FFs"),
            ("Slower", "Faster"),
            ("Designed using JK / T FFs only", "Can be designed with any FF"),
            ("Random sequences cannot\nbe generated", "Random sequences can\nbe generated"),
        ]
        y = 1.2
        for l, r in rows:
            lt = T(l, 24, PINK).move_to([-3.4, y, 0])
            rt = T(r, 24, PINK).move_to([3.4, y, 0])
            self.play(FadeIn(lt, shift=RIGHT * 0.2), FadeIn(rt, shift=LEFT * 0.2), run_time=0.8)
            self.wait(1.2)
            y -= 1.25
        self.wait(2)
        clear_all(self)


def state_board(scene, pos, init="000", color=YELLOW):
    hdr = VGroup(T("Q₂", 28, GREY_B), T("Q₁", 28, GREY_B), T("Q₀", 28, GREY_B)).arrange(RIGHT, buff=0.55)
    digs = VGroup(*[T(c, 44, color) for c in init])
    for d, hh in zip(digs, hdr):
        d.next_to(hh, DOWN, buff=0.25)
    dec = T(f"= {int(init, 2)}", 30, GREY_B).next_to(digs, RIGHT, buff=0.5)
    g = VGroup(hdr, digs, dec).move_to(pos)
    return g


def update_board(scene, board, new, run_time=0.5, color=YELLOW, flash_color=GREEN):
    hdr, digs, dec = board
    anims = []
    for i, c in enumerate(new):
        if digs[i].text != c:
            nd = T(c, 44, color).move_to(digs[i])
            anims.append(Transform(digs[i], nd))
            digs[i].text = c
            anims.append(Flash(nd, color=flash_color, line_length=0.15, flash_radius=0.35))
    nd = T(f"= {int(new, 2)}", 30, GREY_B).move_to(dec, aligned_edge=LEFT)
    anims.append(Transform(dec, nd))
    scene.play(*anims, run_time=run_time)


class S05_AsyncUp(Scene):
    def construct(self):
        cap = Caption(self)
        h = heading("Asynchronous 3-bit Binary Up Counter")
        self.play(FadeIn(h))
        info = T("8 states  •  3 JK flip-flops  •  J = K = 1 (toggle)  •  negative-edge triggered",
                 22, GREY_B).next_to(h, DOWN, buff=0.2)
        self.play(FadeIn(info))
        ffs, clk, links = ripple_chain(neg_edge=True, y=0.9)
        self.play(LaggedStart(*[FadeIn(f) for f in ffs], lag_ratio=0.3), run_time=1.5)
        self.play(Create(clk[0]), FadeIn(clk[1]), Create(links), run_time=1.5)
        cap.say("External clock drives only FF0.  Q₀ clocks FF1, Q₁ clocks FF2 — a ripple chain.", 2.5)
        cap.say("J = K = 1  ⇒  Qₙ₊₁ = Q̄ₙ : each FF toggles on a falling edge of its clock.", 2.5)

        board = state_board(self, [0, -2.0, 0])
        self.play(FadeIn(board))
        state = 0
        for _ in range(8):
            nxt = (state + 1) % 8
            # show the ripple: which FFs toggle
            pulses = []
            for i in range(3):
                if (state ^ nxt) >> i & 1:
                    pulses.append(Indicate(ffs[i][0], color=GREEN, scale_factor=1.05))
            self.play(LaggedStart(*pulses, lag_ratio=0.5), run_time=0.6)
            update_board(self, board, bits(nxt), run_time=0.4)
            state = nxt
        cap.say("Counts 000 → 001 → … → 111 → 000  (Mod-8 up counter)", 2)
        clear_all(self)
        cap.cur = None
        timing_diagram(self, "Timing Diagram — Up Counter", clk_levels=[1, 0] * 8,
                       state_fn=lambda c: c % 8, edge="fall")


def timing_diagram(scene, title, clk_levels, state_fn, edge):
    h = heading(title, GREEN)
    scene.play(FadeIn(h))
    x0, dx, hgt = -4.6, 0.62, 0.6
    names = ["clk", "Q₀", "Q₁", "Q₂"]
    colors = [WHITE, BLUE, PINK, GREEN]
    ys = [1.6, 0.4, -0.8, -2.0]
    n = len(clk_levels)
    counts = [(k + 1) // 2 for k in range(n)]
    states = [state_fn(c) for c in counts]
    rows = [clk_levels] + [[(s >> b) & 1 for s in states] for b in range(3)]
    labels = VGroup(*[T(nm, 26, col).move_to([x0 - 0.8, y + hgt / 2, 0])
                      for nm, col, y in zip(names, colors, ys)])
    scene.play(FadeIn(labels))
    waves = VGroup(*[waveform(r, x0, y, dx, hgt, col) for r, col, y in zip(rows, colors, ys)])
    # edge markers on the clock
    marks = VGroup()
    for k in range(1, n):
        if (edge == "fall" and clk_levels[k - 1] == 1 and clk_levels[k] == 0) or \
           (edge == "rise" and clk_levels[k - 1] == 0 and clk_levels[k] == 1):
            x = x0 + k * dx
            d = DOWN if edge == "fall" else UP
            marks.add(Arrow([x, ys[0] + hgt / 2 - d[1] * 0.25, 0], [x, ys[0] + hgt / 2 + d[1] * 0.2, 0],
                            buff=0, color=YELLOW, stroke_width=3, max_tip_length_to_length_ratio=0.5))
    scene.play(Create(waves[0]), run_time=2)
    scene.play(FadeIn(marks))
    for w in waves[1:]:
        scene.play(Create(w), run_time=2, rate_func=linear)
    # state labels under each interval
    st_lbls = VGroup()
    prev = None
    for k in range(n):
        if states[k] != prev:
            end = k
            while end + 1 < n and states[end + 1] == states[k]:
                end += 1
            xc = x0 + (k + end + 1) / 2 * dx
            st_lbls.add(T(bits(states[k]), 18, YELLOW).move_to([xc, -2.6, 0]))
            prev = states[k]
    scene.play(LaggedStart(*[FadeIn(s) for s in st_lbls], lag_ratio=0.15), run_time=2)
    cap = Caption(scene)
    cap.say("Each output toggles on the triggering edge of the stage before it.", 3)
    clear_all(scene)


class S06_Observations(Scene):
    def construct(self):
        cap = Caption(self)
        h = heading("Observations")
        self.play(FadeIn(h))
        tbl_hdr = VGroup(T("Edge trigger", 28, YELLOW), T("Next clock from", 28, YELLOW),
                         T("Counter", 28, YELLOW)).arrange(RIGHT, buff=0.9).move_to([-2.4, 1.9, 0])
        self.play(FadeIn(tbl_hdr))
        data = [("−ve (falling)", "Q", "UP", GREEN),
                ("+ve (rising)", "Q", "DOWN", RED),
                ("+ve (rising)", "Q̄", "UP", GREEN),
                ("−ve (falling)", "Q̄", "DOWN", RED)]
        y = 1.0
        for e, src, kind, col in data:
            row = VGroup(T(e, 26), T(src, 26), T(kind, 26, col, weight=BOLD))
            for r, hh in zip(row, tbl_hdr):
                r.move_to([hh.get_center()[0], y, 0])
            self.play(FadeIn(row, shift=RIGHT * 0.2), run_time=0.7)
            y -= 0.8
        self.wait(1)
        cap.say("Treat Q as +ve and Q̄ as −ve:  signs differ ⇒ UP,  signs same ⇒ DOWN", 3.5)

        jk_rows = [("J", "K", "Qₙ₊₁"), ("0", "0", "Qₙ"), ("0", "1", "0"), ("1", "0", "1"), ("1", "1", "Q̄ₙ")]
        jk = VGroup()
        for r, row in enumerate(jk_rows):
            jk.add(VGroup(*[T(c, 26, YELLOW if (r == 4 and ci == 2) else (GREY_B if r == 0 else WHITE))
                            .move_to([4.3 + ci * 0.9, 1.9 - r * 0.6, 0]) for ci, c in enumerate(row)]))
        jk.add(Line([3.9, 1.6, 0], [6.4, 1.6, 0], stroke_width=2), Line([5.65, 2.2, 0], [5.65, -0.7, 0], stroke_width=2))
        self.play(FadeIn(jk))
        self.play(Indicate(jk[4], color=YELLOW))
        cap.say("J = K = 1 makes every JK flip-flop a toggle flip-flop.", 2.5)
        clear_all(self)


def kmap(values, title, color=RED):
    """2x4 K-map: rows Q2 = 0/1, columns Q1Q0 in Gray order 00 01 11 10."""
    cw, ch = 1.0, 0.8
    cells = VGroup()
    order = [0, 1, 3, 2]
    for r in range(2):
        for ci, cc in enumerate(order):
            m = r * 4 + cc
            sq = Rectangle(width=cw, height=ch, color=WHITE, stroke_width=2).move_to([ci * cw, -r * ch, 0])
            v = T(values[m], 28, color if values[m] != "0" else GREY_B).move_to(sq)
            idx = T(str(m), 14, GREY).move_to(sq.get_corner(DR) + UL * 0.15)
            cells.add(VGroup(sq, v, idx))
    col_lbls = VGroup(*[T(s, 20, YELLOW).next_to(cells[i][0], UP, buff=0.1)
                        for i, s in enumerate(["00", "01", "11", "10"])])
    row_lbls = VGroup(*[T(s, 20, YELLOW).next_to(cells[i * 4][0], LEFT, buff=0.15) for i, s in enumerate("01")])
    corner = T("Q₂ \\ Q₁Q₀", 18, YELLOW).next_to(col_lbls[0], LEFT, buff=0.3).shift(UP * 0.1)
    ttl = T(title, 24, color).next_to(VGroup(col_lbls, corner), UP, buff=0.2)
    g = VGroup(cells, col_lbls, row_lbls, corner, ttl)
    g.cells = cells
    return g


def cell(km, m):
    pos = {0: 0, 1: 1, 3: 2, 2: 3}
    r, c = divmod(m, 4)
    return km.cells[r * 4 + pos[c]][0]


class S07_Mod5Up(Scene):
    def construct(self):
        cap = Caption(self)
        h = heading("Asynchronous Mod-5 Up Counter  (Non-Binary)")
        self.play(FadeIn(h))
        l1 = T("N = 5  ⇒  n = log₂ 5 ≈ 2.32  ⇒  at least 3 FFs   (2 FFs → only 4 states ✗)", 26).shift(UP * 2.2)
        self.play(Write(l1))
        seq = VGroup(*[T(bits(i), 32, GREEN) for i in range(5)]).arrange(DOWN, buff=0.25).shift(LEFT * 5.3 + DOWN * 0.5)
        nums = VGroup(*[T(f"({i + 1})", 22, RED).next_to(seq[i], RIGHT, buff=0.3) for i in range(5)])
        self.play(LaggedStart(*[FadeIn(s) for s in seq], lag_ratio=0.2), FadeIn(nums))
        bad = T("101", 32, RED).next_to(seq, DOWN, buff=0.35)
        self.play(FadeIn(bad, shift=DOWN * 0.2))
        arr = CurvedArrow(bad.get_left() + LEFT * 0.1, seq[0].get_left() + LEFT * 0.1, angle=-PI / 2, color=RED)
        self.play(Create(arr))
        side = VGroup(
            T("Asynchronous inputs:", 26, GREEN),
            T("Preset (Pr)  →  forces Q = 1", 26, GREEN),
            T("Clear (Clr)  →  forces Q = 0", 26, GREEN),
            T("Up counting uses CLEAR:", 26, RED),
            T("as soon as 101 appears → clear → 000", 26, RED),
            T("Non-binary counter ⇒ extra combinational circuit", 26, WHITE),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.25).move_to([1.6, -0.5, 0])
        for s in side:
            self.play(FadeIn(s, shift=LEFT * 0.2), run_time=0.6)
        self.wait(2.5)
        clear_all(self)
        cap.cur = None

        # Truth table + K-map
        h = heading("Designing the Clear Logic", PINK)
        self.play(FadeIn(h))
        hdr = VGroup(*[T(s, 24, YELLOW) for s in ["Q₂", "Q₁", "Q₀", "Clr̄ (low)", "Clr (high)"]])
        xs = [0.6, 1.4, 2.2, 3.6, 5.3]
        for t, x in zip(hdr, xs):
            t.move_to([x, 2.4, 0])
        rows = VGroup()
        clr_low = ["1", "1", "1", "1", "1", "0", "X", "X"]
        clr_high = ["0", "0", "0", "0", "0", "1", "X", "X"]
        for s in range(8):
            y = 1.8 - s * 0.55
            b = bits(s)
            col = RED if s == 5 else (GREY if s > 5 else WHITE)
            r = VGroup(*[T(c, 24, col).move_to([xs[i], y, 0]) for i, c in enumerate(b)],
                       T(clr_low[s], 24, col).move_to([xs[3], y, 0]),
                       T(clr_high[s], 24, col).move_to([xs[4], y, 0]))
            rows.add(r)
        self.play(FadeIn(hdr), LaggedStart(*[FadeIn(r) for r in rows], lag_ratio=0.1))
        self.play(Create(SurroundingRectangle(rows[5], color=RED)))
        cap.say("Active-low clear: Clr̄ = 0 clears.   Active-high clear: Clr = 1 clears.", 2.5)
        cap.say("110 and 111 never occur → don't care (X).", 2)

        km = kmap(clr_low, "K-map for Clr̄ (active low)").scale(0.85).move_to([-4.0, 1.0, 0])
        self.play(FadeIn(km))
        g1 = SurroundingRectangle(VGroup(cell(km, 0), cell(km, 2)), color=PINK, buff=0.05)
        g2a = SurroundingRectangle(VGroup(cell(km, 0), cell(km, 4)), color=BLUE, buff=0.08)
        g2b = SurroundingRectangle(VGroup(cell(km, 2), cell(km, 6)), color=BLUE, buff=0.08)
        self.play(Create(g1))
        cap.say("Top row  →  Q̄₂", 1.2)
        self.play(Create(g2a), Create(g2b))
        cap.say("Corner columns (Q₀ = 0)  →  Q̄₀", 1.2)
        eq = VGroup(T("Clr̄ = Q̄₂ + Q̄₀ = NOT(Q₂·Q₀)", 28, PINK),
                    T("⇒  NAND gate of Q₂ and Q₀", 28, PINK),
                    T("Active-high:  Clr = Q₂·Q₀  ⇒  AND gate", 28, ORANGE)
                    ).arrange(DOWN, aligned_edge=LEFT, buff=0.25).to_edge(LEFT, buff=0.5).shift(DOWN * 1.9)
        for e in eq:
            self.play(Write(e), run_time=1)
        self.wait(2.5)
        clear_all(self)
        cap.cur = None

        # Circuit
        h = heading("Mod-5 Up Counter Circuit (active-low clear)", PINK)
        self.play(FadeIn(h))
        ffs, clk, links = ripple_chain(neg_edge=True, clr=True, xs=(-5.2, -2.0, 1.2), y=0.6)
        self.play(FadeIn(ffs), FadeIn(clk), Create(links))
        gate = and_gate([4.6, 1.85, 0], nand=True)
        q0, q2 = ff_pt(ffs[0], "q"), ff_pt(ffs[2], "q")
        jx = q0[0] + 0.45
        w0 = wire([[jx, q0[1], 0], [jx, 2.7, 0], [3.8, 2.7, 0], [3.8, gate.in1[1], 0], gate.in1], PINK)
        w2 = wire([q2, [3.5, q2[1], 0], [3.5, gate.in2[1], 0], gate.in2], PINK)
        busy = ff_pt(ffs[0], "bottom")[1] - 0.45
        wout = wire([gate.out, [5.8, gate.out[1], 0], [5.8, busy, 0], [ff_pt(ffs[0], "bottom")[0], busy, 0]], PINK)
        drops = VGroup(*[Line([ff_pt(f, "bottom")[0], busy, 0], ff_pt(f, "bottom"), color=PINK) for f in ffs])
        dots = VGroup(Dot([jx, q0[1], 0], color=PINK, radius=0.06),
                      *[Dot([ff_pt(f, "bottom")[0], busy, 0], color=PINK, radius=0.06) for f in ffs[1:]])
        self.play(Create(gate), Create(w0), Create(w2))
        self.play(Create(wout), Create(drops), FadeIn(dots))
        self.add(T("NAND", 18, PINK).next_to(gate, UP, buff=0.05))

        board = state_board(self, [-2.0, -2.5, 0])
        board.scale(0.8)
        self.play(FadeIn(board))
        out_lbl = T("Clr̄ = 1", 24, PINK).move_to([4.9, 0.9, 0])
        self.play(FadeIn(out_lbl))
        for s in range(1, 6):
            update_board(self, board, bits(s), run_time=0.45)
            if s < 5:
                self.wait(0.4)
        nl = T("Clr̄ = 0 !", 24, RED).move_to(out_lbl)
        self.play(Transform(out_lbl, nl), Flash(gate.out, color=RED), wout.animate.set_color(RED),
                  drops.animate.set_color(RED), run_time=0.6)
        update_board(self, board, "000", run_time=0.4, flash_color=RED)
        self.play(Transform(out_lbl, T("Clr̄ = 1", 24, PINK).move_to(out_lbl)),
                  wout.animate.set_color(PINK), drops.animate.set_color(PINK), run_time=0.5)
        cap.say("101 lasts only momentarily — the NAND clears the counter to 000.", 3)
        clear_all(self)


class S08_AsyncDown(Scene):
    def construct(self):
        cap = Caption(self)
        h = heading("Asynchronous 3-bit Binary Down Counter")
        self.play(FadeIn(h))
        info = T("Initial state 111  •  J = K = 1  ⇒  Qₙ₊₁ = Q̄ₙ  •  positive-edge triggered, Q → next clk",
                 22, GREY_B).next_to(h, DOWN, buff=0.2)
        self.play(FadeIn(info))
        ffs, clk, links = ripple_chain(neg_edge=False, y=0.9)
        self.play(LaggedStart(*[FadeIn(f) for f in ffs], lag_ratio=0.3), run_time=1.5)
        self.play(Create(clk[0]), FadeIn(clk[1]), Create(links), run_time=1.5)
        board = state_board(self, [0, -2.0, 0], init="111", color=ORANGE)
        self.play(FadeIn(board))
        state = 7
        for _ in range(8):
            nxt = (state - 1) % 8
            pulses = [Indicate(ffs[i][0], color=ORANGE, scale_factor=1.05)
                      for i in range(3) if (state ^ nxt) >> i & 1]
            self.play(LaggedStart(*pulses, lag_ratio=0.5), run_time=0.6)
            update_board(self, board, bits(nxt), run_time=0.4, color=ORANGE, flash_color=ORANGE)
            state = nxt
        cap.say("Counts 111 → 110 → … → 000 → 111  (Mod-8 down counter)", 2)
        clear_all(self)
        cap.cur = None
        timing_diagram(self, "Timing Diagram — Down Counter", clk_levels=[0, 1] * 8,
                       state_fn=lambda c: (7 - c) % 8, edge="rise")


class S09_Mod5Down(Scene):
    def construct(self):
        cap = Caption(self)
        h = heading("Asynchronous Mod-5 Down Counter  (3 FFs)")
        self.play(FadeIn(h))
        side = VGroup(
            T("Down counting uses PRESET:", 28, RED),
            T("Active-low preset  →  Pr̄ = 0 sets 111", 26, RED),
            T("Active-high preset →  Pr = 1 sets 111", 26, RED),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.3).shift(LEFT * 2.8 + UP * 0.8)
        for s in side:
            self.play(FadeIn(s, shift=RIGHT * 0.2), run_time=0.7)
        seq = VGroup(*[T(bits(s), 32, ORANGE) for s in [7, 6, 5, 4, 3]]).arrange(DOWN, buff=0.25)
        seq.shift(RIGHT * 3.5 + DOWN * 0.2)
        self.play(LaggedStart(*[FadeIn(s) for s in seq], lag_ratio=0.2))
        bad = T("010", 32, RED).next_to(seq, DOWN, buff=0.3)
        self.play(FadeIn(bad))
        arr = CurvedArrow(bad.get_right() + RIGHT * 0.1, seq[0].get_right() + RIGHT * 0.1, angle=PI / 2, color=RED)
        self.play(Create(arr))
        cap.say("As soon as 010 appears → preset → back to 111.", 2.5)
        clear_all(self)
        cap.cur = None

        h = heading("Designing the Preset Logic", ORANGE)
        self.play(FadeIn(h))
        pr_low = ["X", "X", "0", "1", "1", "1", "1", "1"]  # indexed by state value
        hdr = VGroup(*[T(s, 24, YELLOW) for s in ["Q₂", "Q₁", "Q₀", "Pr̄ (low)", "Pr (high)"]])
        xs = [0.6, 1.4, 2.2, 3.6, 5.3]
        for t, x in zip(hdr, xs):
            t.move_to([x, 2.4, 0])
        rows = VGroup()
        for k, s in enumerate([7, 6, 5, 4, 3, 2, 1, 0]):
            y = 1.8 - k * 0.55
            col = RED if s == 2 else (GREY if s < 2 else WHITE)
            hi = {"X": "X", "0": "1", "1": "0"}[pr_low[s]]
            rows.add(VGroup(*[T(c, 24, col).move_to([xs[i], y, 0]) for i, c in enumerate(bits(s))],
                            T(pr_low[s], 24, col).move_to([xs[3], y, 0]),
                            T(hi, 24, col).move_to([xs[4], y, 0])))
        self.play(FadeIn(hdr), LaggedStart(*[FadeIn(r) for r in rows], lag_ratio=0.1))
        self.play(Create(SurroundingRectangle(rows[5], color=RED)))
        km = kmap(pr_low, "K-map for Pr̄ (active low)").scale(0.85).move_to([-4.0, 1.0, 0])
        self.play(FadeIn(km))
        g1 = SurroundingRectangle(VGroup(cell(km, 4), cell(km, 6)), color=YELLOW, buff=0.05)
        g2 = SurroundingRectangle(VGroup(cell(km, 1), cell(km, 7)), color=BLUE, buff=0.09)
        self.play(Create(g1))
        cap.say("Bottom row  →  Q₂", 1.2)
        self.play(Create(g2))
        cap.say("Middle columns (Q₀ = 1)  →  Q₀", 1.2)
        eq = VGroup(T("Pr̄ = Q₂ + Q₀   ⇒  OR gate", 28, ORANGE),
                    T("At 010:  0 + 0 = 0  ⇒ preset!", 28, RED),
                    T("Active-high:  Pr = NOT(Q₂ + Q₀)  ⇒  NOR gate", 28, YELLOW)
                    ).arrange(DOWN, aligned_edge=LEFT, buff=0.25).to_edge(LEFT, buff=0.5).shift(DOWN * 1.9)
        for e in eq:
            self.play(Write(e), run_time=1)
        self.wait(2.5)
        clear_all(self)
        cap.cur = None

        h = heading("Mod-5 Down Counter Circuit (active-low preset)", ORANGE)
        self.play(FadeIn(h))
        ffs, clk, links = ripple_chain(neg_edge=False, pre=True, xs=(-5.2, -2.0, 1.2), y=0.2)
        self.play(FadeIn(ffs), FadeIn(clk), Create(links))
        gate = or_gate([4.4, 0.85, 0])
        q0, q2 = ff_pt(ffs[0], "q"), ff_pt(ffs[2], "q")
        jx = q0[0] + 0.45
        w2 = wire([q2, [3.5, q2[1], 0], [3.5, gate.in1[1], 0], gate.in1], ORANGE)
        w0 = wire([[jx, q0[1], 0], [jx, -1.6, 0], [3.7, -1.6, 0], [3.7, gate.in2[1], 0], gate.in2], ORANGE)
        busy = ff_pt(ffs[0], "top")[1] + 0.45
        wout = wire([gate.out, [5.6, gate.out[1], 0], [5.6, busy, 0], [ff_pt(ffs[0], "top")[0], busy, 0]], ORANGE)
        drops = VGroup(*[Line([ff_pt(f, "top")[0], busy, 0], ff_pt(f, "top"), color=ORANGE) for f in ffs])
        dots = VGroup(Dot([jx, q0[1], 0], color=ORANGE, radius=0.06),
                      *[Dot([ff_pt(f, "top")[0], busy, 0], color=ORANGE, radius=0.06) for f in ffs[1:]])
        self.play(Create(gate), Create(w0), Create(w2))
        self.play(Create(wout), Create(drops), FadeIn(dots))
        self.add(T("OR", 18, ORANGE).next_to(gate, DOWN, buff=0.05))

        board = state_board(self, [-2.0, -2.6, 0], init="111", color=ORANGE).scale(0.8)
        self.play(FadeIn(board))
        out_lbl = T("Pr̄ = 1", 24, ORANGE).move_to([6.3, 0.0, 0])
        self.play(FadeIn(out_lbl))
        for s in [6, 5, 4, 3, 2]:
            update_board(self, board, bits(s), run_time=0.45, color=ORANGE, flash_color=ORANGE)
            if s > 2:
                self.wait(0.4)
        self.play(Transform(out_lbl, T("Pr̄ = 0 !", 24, RED).move_to(out_lbl)), Flash(gate.out, color=RED),
                  wout.animate.set_color(RED), drops.animate.set_color(RED), run_time=0.6)
        update_board(self, board, "111", run_time=0.4, color=ORANGE, flash_color=RED)
        self.play(Transform(out_lbl, T("Pr̄ = 1", 24, ORANGE).move_to(out_lbl)),
                  wout.animate.set_color(ORANGE), drops.animate.set_color(ORANGE), run_time=0.5)
        cap.say("010 is momentary — the OR output presets the counter back to 111.", 3)
        clear_all(self)
        cap.cur = None

        h = heading("Key Takeaways")
        self.play(FadeIn(h))
        pts = VGroup(
            T("•  n flip-flops → up to 2ⁿ states;  Mod-N needs n = ⌈log₂ N⌉ FFs", 26),
            T("•  Binary counters use all 2ⁿ states; non-binary ones skip some", 26),
            T("•  Asynchronous (ripple): each FF clocks the next — simple but slower", 26),
            T("•  Edge & output signs differ ⇒ UP;  same ⇒ DOWN", 26),
            T("•  Mod-N UP: detect N → CLEAR to 000", 26, PINK),
            T("•  Mod-N DOWN: detect the extra state → PRESET to 111", 26, ORANGE),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.35).shift(DOWN * 0.2)
        for p in pts:
            self.play(FadeIn(p, shift=RIGHT * 0.2), run_time=0.7)
        self.wait(4)
        clear_all(self)


SCENE_ORDER = ["S01_Intro", "S02_UpDownModN", "S03_BinaryNonBinary", "S04_AsyncVsSync",
               "S05_AsyncUp", "S06_Observations", "S07_Mod5Up", "S08_AsyncDown", "S09_Mod5Down"]
