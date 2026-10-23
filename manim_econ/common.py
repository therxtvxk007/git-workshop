"""Shared styling and layout helpers for the economics Manim scenes."""

from manim import (
    DOWN,
    LEFT,
    RIGHT,
    UP,
    Arrow,
    Create,
    FadeIn,
    FadeOut,
    GrowArrow,
    Line,
    RoundedRectangle,
    Scene,
    Text,
    VGroup,
    Write,
    config,
)

config.background_color = "#0f1117"

FONT = "Inter"
INK = "#e8e8e8"
MUTED = "#9aa0a6"
GOLD = "#f5b942"
TEAL = "#3ec1b4"
CORAL = "#ff6b6b"
SKY = "#5aa9ff"
LIME = "#8bd450"
VIOLET = "#b48cff"


def T(text, size=28, color=INK, weight="NORMAL", **kw):
    return Text(text, font=FONT, font_size=size, color=color, weight=weight, **kw)


def title_bar(text, color=GOLD):
    title = T(text, 40, color, weight="BOLD").to_edge(UP, buff=0.45)
    rule = Line(LEFT, RIGHT, color=color, stroke_width=3)
    rule.set_width(title.width + 0.4).next_to(title, DOWN, buff=0.12)
    return VGroup(title, rule)


def box(text, color=TEAL, size=24, width=None, height=None, fill=0.15):
    label = T(text, size, INK)
    w = width or label.width + 0.5
    h = height or label.height + 0.4
    rect = RoundedRectangle(corner_radius=0.15, width=w, height=h,
                            color=color, stroke_width=2.5)
    rect.set_fill(color, opacity=fill)
    label.move_to(rect)
    return VGroup(rect, label)


def bullets(lines, size=24, color=INK, bullet_color=GOLD, buff=0.28):
    rows = VGroup()
    for line in lines:
        dot = T("•", size, bullet_color)
        txt = T(line, size, color)
        rows.add(VGroup(dot, txt).arrange(RIGHT, buff=0.18, aligned_edge=UP))
    return rows.arrange(DOWN, aligned_edge=LEFT, buff=buff)


def chain(labels, colors=None, direction=DOWN, buff=0.45, size=22, width=None):
    """Boxes joined by arrows, e.g. a cause -> effect chain."""
    colors = colors or [TEAL] * len(labels)
    nodes = VGroup(*[box(l, c, size, width=width) for l, c in zip(labels, colors)])
    nodes.arrange(direction, buff=buff)
    arrows = VGroup(*[
        Arrow(a.get_edge_center(direction), b.get_edge_center(-direction),
              buff=0.06, color=MUTED, stroke_width=3, max_tip_length_to_length_ratio=0.35)
        for a, b in zip(nodes[:-1], nodes[1:])
    ])
    return nodes, arrows


def bracket(mob, color=INK, buff=0.15, tick=0.2):
    """LaTeX-free stand-in for Brace on the right-hand side of a mobject."""
    from manim import VMobject
    x = mob.get_right()[0] + buff
    top, bot = mob.get_top()[1], mob.get_bottom()[1]
    path = VMobject(color=color, stroke_width=3)
    path.set_points_as_corners([[x - tick, top, 0], [x, top, 0], [x, bot, 0], [x - tick, bot, 0]])
    nib = Line([x, (top + bot) / 2, 0], [x + tick, (top + bot) / 2, 0], color=color, stroke_width=3)
    return VGroup(path, nib)


def axis_labels(axes, xs=(), ys=(), size=18, color=MUTED, fmt="{:g}"):
    """Text tick labels (avoids the LaTeX-backed numbers_to_include)."""
    labels = VGroup()
    for x in xs:
        labels.add(T(fmt.format(x), size, color).next_to(axes.c2p(x, 0), DOWN, buff=0.15))
    for y in ys:
        labels.add(T(fmt.format(y), size, color).next_to(axes.c2p(0, y), LEFT, buff=0.15))
    return labels


class Lesson(Scene):
    """Scene with helpers for sectioned, slide-like lessons."""

    def clear_all(self, run_time=0.6):
        if self.mobjects:
            self.play(*[FadeOut(m) for m in self.mobjects], run_time=run_time)

    def opening(self, title, subtitle, color=GOLD):
        t = T(title, 54, color, weight="BOLD")
        s = T(subtitle, 26, MUTED).next_to(t, DOWN, buff=0.35)
        self.play(Write(t), run_time=1.2)
        self.play(FadeIn(s, shift=UP * 0.2))
        self.wait(1.2)
        self.clear_all()

    def section(self, text, color=GOLD):
        bar = title_bar(text, color)
        self.play(FadeIn(bar[0], shift=DOWN * 0.2), Create(bar[1]))
        return bar

    def play_chain(self, nodes, arrows, step=0.45):
        self.play(FadeIn(nodes[0], shift=UP * 0.15), run_time=step)
        for a, n in zip(arrows, nodes[1:]):
            self.play(GrowArrow(a), FadeIn(n, shift=UP * 0.15), run_time=step)
