"""Module 4: Capital budgeting — NPV, IRR, PI, payback, benefit-cost ratio, ARR."""

from manim import *

from common import (CORAL, GOLD, INK, LIME, MUTED, SKY, TEAL, VIOLET, Lesson,
                    T, axis_labels, box, bullets, chain)

IT_FLOWS = [70000, 120000, 140000, 140000, 40000]
IT_COST = 400000
IRR_FLOWS = [200, 300, 300, 400, 500]
IRR_COST = 1000
PI_FLOWS = [5000, 9000, 10000, 10000, 3000]
PI_COST = 25000


def npv(flows, cost, k):
    return sum(c / (1 + k) ** (i + 1) for i, c in enumerate(flows)) - cost


class CapitalBudgeting(Lesson):
    def construct(self):
        self.opening("Capital Budgeting", "NPV · IRR · PI · Payback · Benefit-Cost Ratio · ARR", SKY)
        self.feasibility()
        self.cash_flows()
        self.time_value()
        self.npv_example()
        self.irr()
        self.profitability_index()
        self.payback()
        self.bcr_arr()
        self.summary()

    def feasibility(self):
        self.section("Before taking on any project…", SKY)
        tech = box("a) Technical feasibility", SKY, 26).shift(LEFT * 3.3 + UP * 1.2)
        fin = box("b) Financial viability", GOLD, 26).shift(RIGHT * 3.3 + UP * 1.2)
        no = box("Not feasible → no project", CORAL, 22).next_to(tech, DOWN, buff=1.2)
        a1 = Arrow(tech.get_bottom(), no.get_top(), color=CORAL, buff=0.1)
        a2 = Arrow(tech.get_right(), fin.get_left(), color=LIME, buff=0.1)
        ok = T("feasible", 20, LIME).next_to(a2, UP, buff=0.1)
        tools = T("NPV · IRR · PI · Payback · BCR · ARR", 22, GOLD).next_to(fin, DOWN, buff=1.4)
        a3 = Arrow(fin.get_bottom(), tools.get_top(), color=GOLD, buff=0.1)
        self.play(FadeIn(tech))
        self.play(GrowArrow(a1), FadeIn(no))
        self.play(GrowArrow(a2), FadeIn(ok), FadeIn(fin))
        self.play(GrowArrow(a3), Write(tools))
        self.wait(2)
        self.clear_all()

    def cash_flows(self):
        self.section("Discounted vs Non-Discounted Cash Flow", SKY)
        root = box("Cash flows", INK, 26).shift(UP * 1.9)
        dcf = box("Discounted cash flow\n(considers opportunity cost)", TEAL, 22).shift(LEFT * 3.3 + UP * 0.2)
        ndcf = box("Non-discounted cash flow\n(ignores opportunity cost)", CORAL, 22).shift(RIGHT * 3.3 + UP * 0.2)
        l1 = Line(root.get_bottom(), dcf.get_top(), color=MUTED)
        l2 = Line(root.get_bottom(), ndcf.get_top(), color=MUTED)
        self.play(FadeIn(root))
        self.play(Create(l1), Create(l2), FadeIn(dcf), FadeIn(ndcf))
        dm = T("NPV · IRR · PI", 24, TEAL, weight="BOLD").next_to(dcf, DOWN, buff=0.3)
        nm = T("Payback period", 24, CORAL, weight="BOLD").next_to(ndcf, DOWN, buff=0.3)
        self.play(FadeIn(dm), FadeIn(nm))
        ex = VGroup(
            T("Project A → 10%   (chosen)", 22, LIME),
            T("Project B → 8%    (given up)", 22, MUTED),
            T("Opportunity cost of capital = 8%  (a.k.a. discount rate / cost of capital)", 21, GOLD),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.2).to_edge(DOWN, buff=0.45)
        self.play(LaggedStart(*[FadeIn(e) for e in ex], lag_ratio=0.4))
        self.wait(2.5)
        self.clear_all()

    def time_value(self):
        self.section("Time Value of Money", SKY)
        sub = T("₹1 today is worth more than ₹1 tomorrow — money can earn interest", 22, MUTED)
        sub.next_to(self.mobjects[-1], DOWN, buff=0.2)
        self.play(FadeIn(sub))
        axes = Axes(x_range=[0, 15, 5], y_range=[0, 350, 100], x_length=6.4, y_length=4.2,
                    axis_config={"color": MUTED, "include_tip": False}).shift(LEFT * 2.9 + DOWN * 0.9)
        self.play(Create(axes), FadeIn(axis_labels(axes, xs=(5, 10, 15), ys=(100, 200, 300))))
        xl = T("years (n)", 18, MUTED).next_to(axes.x_axis, DOWN, buff=0.4)
        self.play(FadeIn(xl))
        curve = axes.plot(lambda n: 100 * 1.08 ** n, x_range=[0, 15], color=GOLD)
        self.play(Create(curve), run_time=2)
        formula = box("FV = PV × (1 + k)ⁿ", GOLD, 30).shift(RIGHT * 3.6 + UP * 1.2)
        self.play(FadeIn(formula))
        rows = VGroup()
        for n in (1, 5, 15):
            fv = 100 * 1.08 ** n
            d = Dot(axes.c2p(n, fv), color=CORAL)
            lab = T(f"${fv:.2f}", 18, CORAL).next_to(d, DR if n == 1 else UL, buff=0.08)
            self.play(FadeIn(d, scale=2), FadeIn(lab), run_time=0.5)
            rows.add(T(f"n = {n:<2}  →  100(1.08)^{n} = ${fv:.2f}", 22, INK))
        rows.arrange(DOWN, aligned_edge=LEFT, buff=0.2).next_to(formula, DOWN, buff=0.4)
        self.play(LaggedStart(*[FadeIn(r) for r in rows], lag_ratio=0.3))
        pv = box("PV = FV ÷ (1 + k)ⁿ", TEAL, 30).next_to(rows, DOWN, buff=0.5)
        cap = T("Discounting: bring future money back to today", 18, TEAL).next_to(pv, DOWN, buff=0.15)
        self.play(TransformFromCopy(formula, pv), FadeIn(cap))
        self.wait(2.5)
        self.clear_all()

    def npv_example(self):
        self.section("Net Present Value (NPV)", SKY)
        rule = VGroup(
            T("NPV = PV of all cash inflows − PV of all cash outflows", 26, INK),
            T("NPV > 0 → Accept     NPV < 0 → Reject     NPV = 0 → consider intangibles", 21, GOLD),
        ).arrange(DOWN, buff=0.25).shift(UP * 0.8)
        self.play(Write(rule[0]))
        self.play(FadeIn(rule[1]))
        q = T("IT project: invest $400,000 today, inflows $70k, $120k, $140k, $140k, $40k", 21, MUTED)
        q.next_to(rule, DOWN, buff=0.6)
        self.play(FadeIn(q))
        self.wait(2)
        self.clear_all()

        k = ValueTracker(0.08)
        title = always_redraw(lambda: T(
            f"Discount rate k = {k.get_value() * 100:.0f}%", 30, GOLD, weight="BOLD").to_edge(UP, buff=0.4))
        axes = Axes(x_range=[0, 6, 1], y_range=[0, 150000, 50000], x_length=7.2, y_length=4.3,
                    axis_config={"color": MUTED, "include_tip": False}).shift(LEFT * 2.6 + DOWN * 0.6)
        self.add(title)
        ylabs = VGroup(*[T(f"{v // 1000}k", 18, MUTED).next_to(axes.c2p(0, v), LEFT, buff=0.15)
                         for v in (50000, 100000, 150000)])
        self.play(Create(axes), FadeIn(axis_labels(axes, xs=range(1, 6))), FadeIn(ylabs))
        xl = T("year", 18, MUTED).next_to(axes.x_axis, DOWN, buff=0.4)
        self.play(FadeIn(xl))

        def bar(i, value, col, op):
            p0, p1 = axes.c2p(i + 1 - 0.32, 0), axes.c2p(i + 1 + 0.32, value)
            return Rectangle(width=p1[0] - p0[0], height=max(p1[1] - p0[1], 0.001), color=col,
                             fill_opacity=op, stroke_width=1.5).move_to((p0 + p1) / 2)

        fv_bars = VGroup(*[bar(i, c, MUTED, 0.15) for i, c in enumerate(IT_FLOWS)])
        self.play(LaggedStart(*[GrowFromEdge(b, DOWN) for b in fv_bars], lag_ratio=0.15))
        fv_lab = T("future cash (FV)", 18, MUTED).next_to(axes, UP, buff=0.05).align_to(axes, LEFT)
        self.play(FadeIn(fv_lab))

        pv_bars = always_redraw(lambda: VGroup(*[
            bar(i, c / (1 + k.get_value()) ** (i + 1), TEAL, 0.8) for i, c in enumerate(IT_FLOWS)]))
        self.play(*[TransformFromCopy(f, p) for f, p in zip(fv_bars, pv_bars)], run_time=1.5)
        self.add(pv_bars)
        pv_lab = T("present value (PV)", 18, TEAL).next_to(fv_lab, RIGHT, buff=0.4)
        self.play(FadeIn(pv_lab))

        panel = always_redraw(lambda: self._npv_panel(k.get_value()))
        self.play(FadeIn(panel))
        self.wait(2.5)
        self.play(k.animate.set_value(0.15), run_time=3)
        self.wait(2.5)
        self.remove(title, pv_bars, panel)
        self.clear_all()

    def _npv_panel(self, k):
        pvs = [c / (1 + k) ** (i + 1) for i, c in enumerate(IT_FLOWS)]
        total = sum(pvs)
        val = total - IT_COST
        col = LIME if val >= 0 else CORAL
        rows = VGroup(*[T(f"Y{i + 1}: {c:,} / {1 + k:.2f}^{i + 1} = {p:,.0f}", 18, INK)
                        for i, (c, p) in enumerate(zip(IT_FLOWS, pvs))])
        rows.add(T(f"Σ PV = {total:,.0f}", 22, TEAL))
        rows.add(T(f"NPV = {total:,.0f} − 400,000", 22, INK))
        rows.add(T(f"= {val:,.0f}  →  {'ACCEPT' if val >= 0 else 'REJECT'}", 26, col, weight="BOLD"))
        return rows.arrange(DOWN, aligned_edge=LEFT, buff=0.16).to_edge(RIGHT, buff=0.4).shift(DOWN * 0.3)

    def irr(self):
        self.section("Internal Rate of Return (IRR)", SKY)
        sub = T("IRR = the discount rate at which NPV = 0", 26, INK).shift(UP * 2.1)
        self.play(FadeIn(sub))
        axes = Axes(x_range=[0, 30, 5], y_range=[-300, 700, 200], x_length=8, y_length=4.2,
                    axis_config={"color": MUTED, "include_tip": False}).shift(LEFT * 1.8 + DOWN * 0.8)
        self.play(Create(axes), FadeIn(axis_labels(axes, xs=(5, 10, 15, 20, 25, 30),
                                                    ys=(-200, 200, 600))))
        xl = T("discount rate k (%)", 18, MUTED).next_to(axes, DOWN, buff=0.45)
        yl = T("NPV ($)", 18, MUTED).next_to(axes.y_axis, UP, buff=0.1)
        self.play(FadeIn(xl), FadeIn(yl))
        curve = axes.plot(lambda r: npv(IRR_FLOWS, IRR_COST, r / 100), x_range=[0, 30], color=GOLD)
        self.play(Create(curve), run_time=2)

        k = ValueTracker(0)
        dot = always_redraw(lambda: Dot(axes.c2p(k.get_value(), npv(IRR_FLOWS, IRR_COST,
                                                                    k.get_value() / 100)), color=CORAL))
        readout = always_redraw(lambda: T(
            f"k = {k.get_value():.2f}%   NPV = {npv(IRR_FLOWS, IRR_COST, k.get_value() / 100):,.2f}",
            22, CORAL).to_edge(RIGHT, buff=0.4).shift(UP * 1.2))
        self.add(dot, readout)
        self.play(k.animate.set_value(12), run_time=1.5)
        oc = DashedLine(axes.c2p(12, -300), axes.c2p(12, 700), color=SKY)
        ocl = T("cost of capital 12%", 18, SKY).next_to(oc, UP, buff=0.05)
        self.play(Create(oc), FadeIn(ocl))
        self.wait(1)
        irr = 17.72
        self.play(k.animate.set_value(irr), run_time=2)
        il = T("IRR ≈ 17.72%", 24, LIME, weight="BOLD").next_to(axes.c2p(irr, 0), UR, buff=0.15)
        self.play(Flash(dot, color=LIME), Write(il))
        verdict = VGroup(
            T("IRR 17.72% > 12% → ACCEPT", 24, LIME, weight="BOLD"),
            T("IRR > k → NPV positive", 20, INK),
            T("IRR < k → NPV negative", 20, INK),
            T("IRR = k → NPV zero", 20, INK),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.2).to_edge(RIGHT, buff=0.4).shift(DOWN * 0.8)
        self.play(LaggedStart(*[FadeIn(v) for v in verdict], lag_ratio=0.3))
        self.wait(2.5)
        self.remove(dot, readout)
        self.clear_all()

    def profitability_index(self):
        self.section("Profitability Index (PI)", SKY)
        f = box("PI = PV of cash inflows ÷ cash outflow", GOLD, 28).shift(UP * 1.7)
        sub = T("for every $1 spent, how much comes back?", 20, MUTED).next_to(f, DOWN, buff=0.15)
        self.play(FadeIn(f), FadeIn(sub))
        pvs = [c / 1.12 ** (i + 1) for i, c in enumerate(PI_FLOWS)]
        total = sum(pvs)
        # stacked bar of PV inflows vs outflow bar
        scale = 3.3 / 28000
        base = DOWN * 3.0
        out = Rectangle(width=1.5, height=PI_COST * scale, color=CORAL, fill_opacity=0.8)
        out.move_to(base + LEFT * 3.4 + UP * PI_COST * scale / 2)
        stack, y = VGroup(), 0
        for p in pvs:
            r = Rectangle(width=1.5, height=p * scale, color=TEAL, fill_opacity=0.8, stroke_width=1)
            r.move_to(base + LEFT * 1.2 + UP * (y + p * scale / 2))
            stack.add(r)
            y += p * scale
        ol = T("Outflow\n$25,000", 18, CORAL).next_to(out, LEFT, buff=0.2)
        il = T("PV inflows @12%\n$26,814", 18, TEAL).next_to(stack, RIGHT, buff=0.2)
        self.play(GrowFromEdge(out, DOWN), FadeIn(ol))
        self.play(LaggedStart(*[GrowFromEdge(s, DOWN) for s in stack], lag_ratio=0.2), FadeIn(il))
        res = VGroup(T("PI = 26,814.29 ÷ 25,000", 26, INK),
                     T("= 1.07", 34, GOLD, weight="BOLD"),
                     T("PI > 1 → ACCEPT", 28, LIME, weight="BOLD")).arrange(DOWN, buff=0.3)
        res.shift(RIGHT * 3.6 + DOWN * 0.6)
        for r in res:
            self.play(Write(r), run_time=0.7)
        self.wait(2)
        self.clear_all()

    def payback(self):
        self.section("Payback Period", SKY)
        sub = T("Years needed to recover the initial outlay (no discounting)", 22, MUTED).shift(UP * 2.2)
        self.play(FadeIn(sub))
        axes = Axes(x_range=[0, 5, 1], y_range=[0, 40000, 10000], x_length=6.2, y_length=4,
                    axis_config={"color": MUTED, "include_tip": False}).shift(LEFT * 3 + DOWN * 0.8)
        self.play(Create(axes), FadeIn(axis_labels(axes, xs=range(1, 6),
                                                    ys=(10000, 20000, 30000, 40000), fmt="{:,}")))
        target = DashedLine(axes.c2p(0, 25000), axes.c2p(5, 25000), color=CORAL)
        tl = T("investment\n$25,000", 16, CORAL).next_to(target, RIGHT, buff=0.1)
        self.play(Create(target), FadeIn(tl))
        cum, pts = 0, [axes.c2p(0, 0)]
        for i, c in enumerate(PI_FLOWS):
            cum += c
            pts.append(axes.c2p(i + 1, cum))
        line = VMobject(color=TEAL).set_points_as_corners(pts)
        self.play(Create(line), run_time=2.5)
        labels = VGroup(*[T(f"{v:,}", 16, TEAL).next_to(p, UL, buff=0.05)
                          for v, p in zip([5000, 14000, 24000, 34000, 37000], pts[1:])])
        self.play(FadeIn(labels))
        cross = axes.c2p(3.1, 25000)
        mark = Dot(cross, color=GOLD, radius=0.1)
        self.play(FadeIn(mark, scale=2), Create(DashedLine(cross, axes.c2p(3.1, 0), color=GOLD)))
        work = VGroup(
            T("After 3 years: $24,000 recovered", 19, INK),
            T("Still needed: $1,000 of year 4's $10,000", 19, INK),
            T("= 1,000 / 10,000 = 0.1 year", 19, INK),
            T("Payback ≈ 3.1 years", 28, GOLD, weight="BOLD"),
            T("Accept if below the standard\nset by industry / leadership", 18, MUTED),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.2).to_edge(RIGHT, buff=0.3).shift(DOWN * 0.6)
        self.play(LaggedStart(*[FadeIn(w) for w in work], lag_ratio=0.35))
        self.wait(2.5)
        self.clear_all()

    def bcr_arr(self):
        self.section("Benefit-Cost Ratio", SKY)
        bcr = VGroup(
            T("Benefit / Cost  =", 28, INK),
            VGroup(T("Estimated revenue × P(success)", 24, LIME),
                   Line(LEFT * 3.2, RIGHT * 3.2, color=INK),
                   T("Estimated cost × P(meeting cost target)", 24, CORAL)).arrange(DOWN, buff=0.15),
        ).arrange(RIGHT, buff=0.3).shift(UP * 0.6)
        self.play(FadeIn(bcr))
        cap = T("A quantitative estimate to support a decision (ratio > 1 is favourable)", 20, MUTED)
        cap.next_to(bcr, DOWN, buff=0.5)
        self.play(FadeIn(cap))
        self.wait(2)
        self.clear_all()

        self.section("Accounting Rate of Return (ARR)", SKY)
        f = box("ARR = Average annual profit ÷ Average investment × 100%", GOLD, 24).shift(UP * 2)
        self.play(FadeIn(f))
        q = T("Machine $100,000 · inflows 20k, 20k, 10k, 10k, 30k · salvage $25,000", 20, MUTED)
        q.next_to(f, DOWN, buff=0.3)
        self.play(FadeIn(q))
        steps = VGroup(
            T("Total inflows = 40,000 + 20,000 + 30,000 = 90,000", 22, INK),
            T("Depreciation = 100,000 − 25,000 = 75,000", 22, INK),
            T("Total profit = 90,000 − 75,000 = 15,000", 22, INK),
            T("Avg annual profit = 15,000 ÷ 5 = 3,000", 22, TEAL),
            T("Avg investment = (100,000 + 25,000) ÷ 2 = 62,500", 22, TEAL),
            T("ARR = 3,000 ÷ 62,500 × 100 = 4.8%", 30, GOLD, weight="BOLD"),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.25).shift(DOWN * 0.9)
        for s in steps:
            self.play(FadeIn(s, shift=RIGHT * 0.2), run_time=0.6)
        rule = T("Accept if ARR > required rate of return", 20, LIME).to_edge(DOWN, buff=0.25)
        self.play(FadeIn(rule))
        self.wait(2.5)
        self.clear_all()

    def summary(self):
        self.section("How to choose between projects", SKY)
        n, a = chain(["1. Highest NPV", "2. Tie? → highest IRR", "3. Still tied? → earliest payback"],
                     [GOLD, TEAL, CORAL], DOWN, 0.5, 26, width=7.5)
        VGroup(n, a).shift(DOWN * 0.2)
        self.play_chain(n, a, 0.6)
        self.wait(3)
        self.clear_all()
