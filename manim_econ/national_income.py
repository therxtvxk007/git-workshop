"""Module 3: GDP, GNP, NNP, methods of estimation, measurement difficulties."""

from manim import *

from common import (CORAL, GOLD, INK, LIME, MUTED, SKY, TEAL, VIOLET, Lesson,
                    T, axis_labels, box, bracket, bullets, chain)


class NationalIncome(Lesson):
    def construct(self):
        self.opening("National Income", "GDP · GNP · NNP — how a nation measures its output")
        self.gdp_definition()
        self.final_vs_intermediate()
        self.three_methods()
        self.expenditure()
        self.income_method()
        self.value_added()
        self.not_counted()
        self.gdp_to_nnp()
        self.difficulties()
        self.recap()

    def gdp_definition(self):
        self.section("Gross Domestic Product (GDP)")
        parts = [("monetary value", GOLD), ("of all FINAL goods & services", TEAL),
                 ("produced WITHIN a country", SKY), ("in ONE year", CORAL)]
        cards = VGroup(*[box(p, c, 24, width=5.4) for p, c in parts]).arrange(DOWN, buff=0.25)
        cards.shift(LEFT * 3 + DOWN * 0.4)
        for c in cards:
            self.play(FadeIn(c, shift=RIGHT * 0.3), run_time=0.5)

        border = RoundedRectangle(width=5, height=4.2, corner_radius=0.3, color=SKY)
        border.shift(RIGHT * 3.3 + DOWN * 0.4)
        india = T("India", 26, SKY).next_to(border, UP, buff=0.1)
        indian = box("Indian firms", LIME, 22).move_to(border).shift(UP * 0.9)
        foreign = box("Foreign firms in India", VIOLET, 22).move_to(border).shift(DOWN * 0.6)
        tick = T("both count toward Indian GDP", 20, GOLD).next_to(border, DOWN, buff=0.15)
        self.play(Create(border), FadeIn(india))
        self.play(FadeIn(indian), FadeIn(foreign))
        self.play(Write(tick))
        note = T("Measured every year → is the economy growing? are policies working?", 22, MUTED)
        note.to_edge(DOWN, buff=0.25)
        self.play(FadeIn(note))
        self.wait(2)
        self.clear_all()

    def final_vs_intermediate(self):
        self.section("Final vs Intermediate Goods")
        top_n, top_a = chain(["Tomato", "Household kitchen", "FINAL good ✓"],
                             [CORAL, TEAL, LIME], RIGHT, 0.6)
        bot_n, bot_a = chain(["Tomato", "Pizza shop", "INTERMEDIATE ✗"],
                             [CORAL, SKY, GOLD], RIGHT, 0.6)
        VGroup(top_n, top_a).shift(UP * 1.1)
        VGroup(bot_n, bot_a).shift(DOWN * 0.9)
        self.play_chain(top_n, top_a)
        self.play_chain(bot_n, bot_a)
        msg = T("Only the pizza (the final product) is counted —\n"
                "counting the tomato again would be DOUBLE COUNTING", 24, GOLD)
        msg.to_edge(DOWN, buff=0.4)
        self.play(Write(msg), Indicate(bot_n[2], color=CORAL))
        self.wait(2)
        self.clear_all()

    def three_methods(self):
        self.section("3 Ways to Measure GDP")
        cards = VGroup(
            box("Expenditure\napproach", SKY, 26, 3.6, 2),
            box("Income\napproach", TEAL, 26, 3.6, 2),
            box("Value Added\napproach", GOLD, 26, 3.6, 2),
        ).arrange(RIGHT, buff=0.5)
        self.play(LaggedStart(*[FadeIn(c, shift=UP * 0.3) for c in cards], lag_ratio=0.3))
        star = T("most accurate result", 22, GOLD).next_to(cards[2], DOWN, buff=0.3)
        self.play(Write(star), cards[2][0].animate.set_fill(GOLD, 0.35))
        self.wait(1.5)
        self.clear_all()

    def expenditure(self):
        self.section("(i) Expenditure Approach", SKY)
        rows = [("Consumers", "Consumer spending", "C", SKY, 2.0),
                ("Businesses", "Investment spending", "I", TEAL, 1.0),
                ("Government", "Govt. spending", "G", GOLD, 1.1),
                ("Other countries", "Exports − Imports", "X−M", CORAL, 0.45)]
        table = VGroup()
        for who, what, sym, col, _ in rows:
            table.add(VGroup(T(who, 24, INK), T("→", 24, MUTED), T(what, 24, col),
                             T(sym, 26, col, weight="BOLD")))
        for r in table:
            r[0].set_x(-5.2, LEFT)
        table.arrange(DOWN, buff=0.4, aligned_edge=LEFT).to_edge(LEFT, buff=0.6).shift(UP * 0.3)
        for r in table:
            r[1].next_to(r[0], RIGHT, buff=0.3)
            r[2].next_to(r[1], RIGHT, buff=0.3)
            r[3].next_to(r[2], RIGHT, buff=0.3)

        # Stacked bar for GDP
        base = DOWN * 2.1 + RIGHT * 4.6
        segs, y = VGroup(), 0
        for *_, col, h in rows:
            seg = Rectangle(width=1.4, height=h, color=col, fill_opacity=0.75, stroke_width=1)
            seg.move_to(base + UP * (y + h / 2))
            segs.add(seg)
            y += h
        for r, s, row in zip(table, segs, rows):
            lab = T(row[2], 22, BLACK, weight="BOLD").move_to(s)
            self.play(FadeIn(r, shift=RIGHT * 0.2), GrowFromEdge(s, DOWN), FadeIn(lab), run_time=0.7)
            self.add(lab)
        brace = bracket(segs)
        gdp = T("GDP", 28, INK, weight="BOLD").next_to(brace, RIGHT)
        self.play(GrowFromCenter(brace), Write(gdp))
        formula = box("GDP = C + I + G + (X − M)", GOLD, 32)
        formula.to_edge(DOWN, buff=0.45).shift(LEFT * 2.2)
        self.play(FadeIn(formula, scale=0.9))
        mp = T("= GDP at market price (GDPₘₚ)", 22, MUTED).next_to(formula, DOWN, buff=0.12)
        self.play(FadeIn(mp))
        self.wait(2.2)
        self.clear_all()

    def income_method(self):
        self.section("(ii) Income Approach", TEAL)
        eq = T("Income = Wages + Rent + Interest + Profit", 32, INK)
        eq.shift(UP * 1.4)
        self.play(Write(eq))
        phone = box("Consumer buys a phone\n₹20,000", SKY, 24).shift(LEFT * 3.5 + DOWN * 1.2)
        self.play(FadeIn(phone))
        targets = [("Wages\n(engineers)", TEAL), ("Rent\n(factory)", GOLD),
                   ("Interest\n(lender)", VIOLET), ("Profit\n(owner)", LIME)]
        tbox = VGroup(*[box(t, c, 20, 2.2, 1.1) for t, c in targets]).arrange(DOWN, buff=0.15)
        tbox.shift(RIGHT * 3 + DOWN * 1.1).scale(0.9)
        arrows = VGroup(*[Arrow(phone.get_right(), b.get_left(), buff=0.1, color=MUTED,
                                stroke_width=2.5) for b in tbox])
        self.play(LaggedStart(*[AnimationGroup(GrowArrow(a), FadeIn(b))
                                for a, b in zip(arrows, tbox)], lag_ratio=0.3))
        note = T("Every rupee spent becomes someone's income", 22, GOLD).to_edge(DOWN, buff=0.3)
        self.play(Write(note))
        self.wait(2)
        self.clear_all()

    def value_added(self):
        self.section("(iii) Value Added Approach", GOLD)
        axes = Axes(x_range=[0, 3, 1], y_range=[0, 350, 100], x_length=6, y_length=4,
                    axis_config={"color": MUTED, "include_tip": False}
                    ).shift(LEFT * 2.6 + DOWN * 0.6)
        self.play(Create(axes), FadeIn(axis_labels(axes, ys=(100, 200, 300))))

        def bar(i, lo, hi, col):
            p0, p1 = axes.c2p(i - 0.3, lo), axes.c2p(i + 0.3, hi)
            return Rectangle(width=p1[0] - p0[0], height=p1[1] - p0[1], color=col,
                             fill_opacity=0.8, stroke_width=1).move_to((p0 + p1) / 2)

        stage_labels = VGroup(T("Raw cotton\n→ Yarn (A)", 18, INK).next_to(axes.c2p(1, 0), DOWN),
                              T("Yarn\n→ Hat (B)", 18, INK).next_to(axes.c2p(2, 0), DOWN))
        yarn = bar(1, 0, 100, TEAL)
        hat_old = bar(2, 0, 100, TEAL)
        hat_new = bar(2, 100, 300, GOLD)
        self.play(FadeIn(stage_labels[0]), GrowFromEdge(yarn, DOWN))
        l1 = T("+100", 22, TEAL).next_to(yarn, UP, buff=0.1)
        self.play(FadeIn(l1))
        self.play(FadeIn(stage_labels[1]), TransformFromCopy(yarn, hat_old))
        self.play(GrowFromEdge(hat_new, DOWN))
        l2 = T("+200 value added", 22, GOLD).next_to(hat_new, UP, buff=0.1)
        self.play(FadeIn(l2))

        calc = VGroup(
            T("Hat sells for ₹300", 24, INK),
            T("Value added = 100 + 200", 24, INK),
            T("GDP = ₹300  ✓", 28, GOLD, weight="BOLD"),
            T("Adding sale prices (100 + 300 = 400)\nwould DOUBLE COUNT the yarn ✗", 20, CORAL),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.35).shift(RIGHT * 3.6 + DOWN * 0.2)
        for c in calc:
            self.play(FadeIn(c, shift=LEFT * 0.2), run_time=0.6)
        self.wait(2)
        self.clear_all()

        self.section("Value Added: Pizza example", GOLD)
        n, a = chain(["Tomatoes ₹1,000", "Pizza sold ₹10,000"], [CORAL, GOLD], RIGHT, 1.2, 26)
        n.shift(UP * 1.2)
        a.shift(UP * 1.2)
        self.play_chain(n, a)
        rows = VGroup(
            T("Value added by farmer      =  ₹1,000", 26, CORAL),
            T("Value added by pizzeria   =  10,000 − 1,000  =  ₹9,000", 26, GOLD),
            T("Total GDP                      =  ₹10,000", 30, LIME, weight="BOLD"),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.35).shift(DOWN * 1)
        for r in rows:
            self.play(Write(r), run_time=0.9)
        self.wait(2)
        self.clear_all()

    def not_counted(self):
        self.section("Things that DON'T count toward GDP", CORAL)
        items = ["Intermediate goods", "Used (second-hand) goods",
                 "Things produced in a previous year", "Financial transactions",
                 "Bonds / stocks", "Transfer payments (pensions, dole)"]
        grid = VGroup(*[box(i, CORAL, 21, 5.4, 0.85, fill=0.1) for i in items])
        grid.arrange_in_grid(rows=3, cols=2, buff=(0.9, 0.3)).shift(DOWN * 0.2 + RIGHT * 0.25)
        for g in grid:
            cross = T("✗", 26, CORAL).next_to(g[0], LEFT, buff=0.12)
            self.play(FadeIn(g, shift=UP * 0.15), FadeIn(cross), run_time=0.45)
        why = T("Reason: no NEW goods or services are produced", 24, GOLD).to_edge(DOWN, buff=0.35)
        self.play(Write(why))
        self.wait(2)
        self.clear_all()

    def gdp_to_nnp(self):
        self.section("From GDP to GNP to NNP")
        axes_y = 0
        base = DOWN * 2.6
        def col_rect(h, col, x, y0=0):
            r = Rectangle(width=1.6, height=h, color=col, fill_opacity=0.8, stroke_width=1)
            return r.move_to(base + RIGHT * x + UP * (y0 + h / 2))
        gdp = col_rect(3.6, SKY, -4.5)
        nfia = col_rect(0.8, LIME, -1.5, 3.6)
        gnp = col_rect(4.4, TEAL, 1.0)
        dep = col_rect(0.7, CORAL, 3.4, 3.7)
        nnp = col_rect(3.7, GOLD, 5.6)
        labels = [
            (gdp, "GDP\nC+I+G+(X−M)"), (nfia, "+ NFIA"), (gnp, "GNP"),
            (dep, "− Depreciation"), (nnp, "NNP"),
        ]
        floor = Line(base + LEFT * 6.3, base + RIGHT * 6.6, color=MUTED)
        self.play(Create(floor))
        for rect, text in labels:
            lab = T(text, 20, INK).next_to(rect, UP, buff=0.12)
            self.play(GrowFromEdge(rect, DOWN), FadeIn(lab), run_time=0.7)
        defs = VGroup(
            T("GNP = GDP + Net Factor Income from Abroad", 22, TEAL),
            T("NNP = GNP − Depreciation (wear & tear)", 22, GOLD),
        ).arrange(DOWN, aligned_edge=LEFT).to_corner(UL).shift(DOWN * 1.1)
        self.play(FadeIn(defs))
        self.wait(2)
        self.clear_all()

        self.section("Depreciation example", CORAL)
        machine = box("Machinery  ₹1,00,000\nlifetime 10 years", CORAL, 26).shift(UP * 1.2)
        self.play(FadeIn(machine))
        tracker = ValueTracker(100000)
        bar_max = 6
        bar = always_redraw(lambda: Rectangle(
            width=bar_max * tracker.get_value() / 100000, height=0.6, color=CORAL,
            fill_opacity=0.8).align_to(LEFT * 3, LEFT).shift(DOWN * 0.6))
        val = always_redraw(lambda: T(f"₹{int(tracker.get_value()):,}", 24, INK)
                            .next_to(bar, RIGHT, buff=0.3))
        self.add(bar, val)
        self.play(tracker.animate.set_value(0), run_time=3, rate_func=linear)
        per = T("1,00,000 ÷ 10 = ₹10,000 per year", 30, GOLD, weight="BOLD").shift(DOWN * 2)
        self.play(Write(per))
        self.wait(2)
        self.clear_all()

    def difficulties(self):
        self.section("Difficulties in Measuring National Income")
        a_head = T("A. Theoretical / Conceptual", 26, SKY, weight="BOLD")
        a = bullets(["Transfer payments", "Illegal income (gambling, smuggling)",
                     "Unpaid services (homemakers, charity)", "Production for self-consumption"],
                    22, bullet_color=SKY)
        b_head = T("B. Practical / Statistical", 26, CORAL, weight="BOLD")
        b = bullets(["Double counting", "Non-monetised sector (barter)",
                     "Inadequate & unreliable data", "No standard depreciation rates"],
                    22, bullet_color=CORAL)
        left = VGroup(a_head, a).arrange(DOWN, aligned_edge=LEFT, buff=0.35)
        right = VGroup(b_head, b).arrange(DOWN, aligned_edge=LEFT, buff=0.35)
        VGroup(left, right).arrange(RIGHT, buff=0.8, aligned_edge=UP).shift(DOWN * 0.3)
        self.play(FadeIn(a_head))
        self.play(LaggedStart(*[FadeIn(x, shift=RIGHT * 0.2) for x in a], lag_ratio=0.3))
        self.play(FadeIn(b_head))
        self.play(LaggedStart(*[FadeIn(x, shift=RIGHT * 0.2) for x in b], lag_ratio=0.3))
        self.wait(2.5)
        self.clear_all()

    def recap(self):
        self.section("Recap")
        eqs = VGroup(
            T("GDP   = C + I + G + (X − M)", 32, SKY),
            T("GNP   = GDP + NFIA", 32, TEAL),
            T("NNP   = GNP − Depreciation", 32, GOLD),
            T("NNPₘₚ = C + I + G + (X − M) + NFIA − Depreciation", 26, LIME),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.45)
        for e in eqs:
            self.play(Write(e), run_time=0.9)
        self.wait(3)
        self.clear_all()
