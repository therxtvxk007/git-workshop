"""Module 4: Value Analysis / Value Engineering (VAVE)."""

from manim import *

from common import (CORAL, GOLD, INK, LIME, MUTED, SKY, TEAL, VIOLET, Lesson,
                    T, box, bullets, chain)


class ValueEngineering(Lesson):
    def construct(self):
        self.opening("Value Engineering", "Value Analysis · Objective · Types · Process · "
                     "Applications · Advantages", TEAL)
        self.what_is_vave()
        self.origin()
        self.value_equation()
        self.four_strategies()
        self.objective_quadrant()
        self.types_of_value()
        self.process_wheel()
        self.applications()
        self.advantages()
        self.summary()

    def what_is_vave(self):
        self.section("What is VAVE?", TEAL)
        va = box("VA · Value Analysis\nAnalyse the value\nof the product", SKY, 24, 4.6, 2.2)
        ve = box("VE · Value Engineering\nModify the product\naccording to VA", GOLD, 24, 4.6, 2.2)
        VGroup(va, ve).arrange(RIGHT, buff=1.6).shift(UP * 0.6)
        arr = Arrow(va.get_right(), ve.get_left(), color=MUTED, buff=0.1)
        self.play(FadeIn(va, shift=RIGHT * 0.3))
        self.play(GrowArrow(arr), FadeIn(ve, shift=LEFT * 0.3))
        d = T("Ensure a product's cost is no greater than needed to carry out its functions", 22, INK)
        d.next_to(VGroup(va, ve), DOWN, buff=0.6)
        self.play(Write(d))
        outs = VGroup(*[box(o, TEAL, 20) for o in
                        ("happier customers", "cost savings", "better productivity")])
        outs.arrange(RIGHT, buff=0.4).to_edge(DOWN, buff=0.5)
        self.play(LaggedStart(*[FadeIn(o, shift=UP * 0.2) for o in outs], lag_ratio=0.3))
        note = T("VE and VAVE are used interchangeably", 18, MUTED).next_to(outs, UP, buff=0.2)
        self.play(FadeIn(note))
        self.wait(2)
        self.clear_all()

    def origin(self):
        self.section("Where did VAVE originate?", TEAL)
        line = NumberLine(x_range=[0, 3, 1], length=10, color=MUTED, include_ticks=False)
        line.shift(DOWN * 0.2)
        self.play(Create(line))
        events = [
            (0, "World War II", "Shortage of\nvital materials", CORAL),
            (1.5, "Lawrence Miles, GE", "Sources alternative\nmaterials", SKY),
            (3, "Discovery", "Function kept, money\nsaved, performance ↑", LIME),
        ]
        for x, head, body, col in events:
            p = line.n2p(x)
            dot = Dot(p, color=col, radius=0.12)
            h = T(head, 24, col, weight="BOLD").next_to(dot, UP, buff=0.3)
            b = T(body, 20, INK).next_to(dot, DOWN, buff=0.3)
            self.play(FadeIn(dot, scale=1.5), FadeIn(h, shift=DOWN * 0.2), FadeIn(b), run_time=0.8)
        self.wait(2)
        self.clear_all()

    def value_equation(self):
        self.section("How do you calculate value?", TEAL)
        f = ValueTracker(100)
        c = ValueTracker(100)

        eq = always_redraw(lambda: VGroup(
            T("Value", 40, GOLD, weight="BOLD"), T("=", 40, INK),
            VGroup(T(f"Function {f.get_value():.0f}", 32, TEAL),
                   Line(LEFT * 1.9, RIGHT * 1.9, color=INK),
                   T(f"Cost {c.get_value():.0f}", 32, CORAL)).arrange(DOWN, buff=0.15),
            T("=", 40, INK),
            T(f"{f.get_value() / c.get_value():.2f}", 44, GOLD, weight="BOLD"),
        ).arrange(RIGHT, buff=0.35).shift(UP * 1.4))
        self.play(FadeIn(eq))
        defs = VGroup(
            T("Value = what the product is worth to the customer", 22, GOLD),
            T("Function = properties & qualities of the product", 22, TEAL),
            T("Cost = cost of goods sold (COGS)", 22, CORAL),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.25).shift(DOWN * 1.6)
        self.play(LaggedStart(*[FadeIn(d) for d in defs], lag_ratio=0.3))
        self.play(c.animate.set_value(80), run_time=1.5)
        self.play(f.animate.set_value(130), run_time=1.5)
        self.play(c.animate.set_value(100), f.animate.set_value(100), run_time=1)
        self.wait(1)
        self.clear_all()

    def four_strategies(self):
        self.section("4 ways to raise value", TEAL)
        cases = [("F ↑", "C ↓", "Improve & cut cost"), ("F ↑", "C →", "Improve, same cost"),
                 ("F →", "C ↓", "Same function, cheaper"), ("F ↑↑", "C ↓", "Much better & cheaper")]
        cards = VGroup()
        for fn, co, cap in cases:
            circ = Circle(1.05, color=MUTED, fill_opacity=0.08)
            frac = VGroup(T(fn, 30, TEAL, weight="BOLD"), Line(LEFT * 0.7, RIGHT * 0.7, color=INK),
                          T(co, 30, CORAL, weight="BOLD")).arrange(DOWN, buff=0.1).move_to(circ)
            lab = T(cap, 18, INK).next_to(circ, DOWN, buff=0.25)
            cards.add(VGroup(circ, frac, lab))
        cards.arrange(RIGHT, buff=0.45).shift(UP * 0.2)
        self.play(LaggedStart(*[FadeIn(c, scale=0.8) for c in cards], lag_ratio=0.25))
        ex = T("e.g. a ₹20k phone that keeps its price but gains a longer life → more value",
               20, GOLD).to_edge(DOWN, buff=0.6)
        self.play(FadeIn(ex))
        self.wait(2.5)
        self.clear_all()

    def objective_quadrant(self):
        self.section("Objective of VAVE", TEAL)
        size = 2.4
        quads = VGroup(
            box("High cost\nLow value", SKY, 20, size, size, 0.45),
            box("High cost\nHigh value", MUTED, 20, size, size, 0.12),
            box("Low cost\nLow value", MUTED, 20, size, size, 0.12),
            box("Low cost\nHigh value", CORAL, 20, size, size, 0.45),
        ).arrange_in_grid(2, 2, buff=0).shift(LEFT * 2.5 + DOWN * 0.4)
        x_ax = Arrow(quads.get_corner(DL) + DOWN * 0.1, quads.get_corner(DR) + DOWN * 0.1 + RIGHT * 0.5,
                     color=INK, buff=0)
        y_ax = Arrow(quads.get_corner(DL) + LEFT * 0.1, quads.get_corner(UL) + LEFT * 0.1 + UP * 0.5,
                     color=INK, buff=0)
        xl = T("VALUE", 20, INK, weight="BOLD").next_to(x_ax, DOWN, buff=0.1)
        yl = T("COST", 20, INK, weight="BOLD").rotate(PI / 2).next_to(y_ax, LEFT, buff=0.1)
        self.play(GrowArrow(x_ax), GrowArrow(y_ax), FadeIn(xl), FadeIn(yl))
        self.play(LaggedStart(*[FadeIn(q) for q in quads], lag_ratio=0.2))
        product = Dot(quads[0].get_center(), radius=0.15, color=GOLD)
        self.play(FadeIn(product, scale=2))
        self.play(product.animate.move_to(quads[3].get_center()), run_time=2, path_arc=-PI / 3)
        target = T("TARGET", 26, CORAL, weight="BOLD").next_to(quads[3], RIGHT, buff=0.3)
        self.play(Write(target), Circumscribe(quads[3], color=GOLD))
        txt = T("Weigh cost/benefit of every function\n& component; bring in specialists to\n"
                "propose materials, designs, processes.\nCut cost, keep or improve function.",
                20, INK).shift(RIGHT * 4 + UP * 1.4)
        self.play(FadeIn(txt))
        self.wait(2)
        self.clear_all()

    def types_of_value(self):
        self.section("Types of Value", TEAL)
        types = [("Use value", "How useful it is —\ndo shoes protect your feet?", SKY),
                 ("Cost value", "What was paid to make/buy it\n(incl. shipping, taxes)", GOLD),
                 ("Esteem value", "Status, prestige, respect,\nself-confidence", CORAL),
                 ("Exchange value", "What it can be sold or\ntraded for (market value)", TEAL)]
        cards = VGroup(*[VGroup(box(n, c, 24, 3.0, 0.8, 0.35), T(d, 18, INK))
                         .arrange(DOWN, buff=0.25) for n, d, c in types])
        cards.arrange(RIGHT, buff=0.3).shift(UP * 0.8)
        self.play(LaggedStart(*[FadeIn(c, shift=UP * 0.3) for c in cards], lag_ratio=0.3))
        note = T("There is no single standard definition of 'value'", 20, MUTED).next_to(cards, DOWN, buff=0.4)
        self.play(FadeIn(note))

        # T-shirt cost value example
        ax_left = LEFT * 0.9 + DOWN * 2.6
        cbar = Rectangle(width=5 * 0.3, height=0.45, color=GOLD, fill_opacity=0.85)
        cbar.move_to(ax_left, aligned_edge=LEFT)
        pbar = Rectangle(width=10 * 0.3, height=0.45, color=LIME, fill_opacity=0.85)
        pbar.next_to(cbar, RIGHT, buff=0)
        cl = T("cost $5", 18, BLACK).move_to(cbar)
        pl = T("profit $10", 18, BLACK).move_to(pbar)
        head = T("T-shirt from wholesaler:", 20, INK).next_to(cbar, LEFT, buff=0.3)
        total = T("= selling price $15", 20, INK).next_to(pbar, RIGHT, buff=0.3)
        self.play(FadeIn(head), GrowFromEdge(cbar, LEFT), FadeIn(cl))
        self.play(GrowFromEdge(pbar, LEFT), FadeIn(pl), FadeIn(total))
        self.wait(2.5)
        self.clear_all()

    def process_wheel(self):
        self.section("Value Engineering Process", TEAL)
        steps = ["Reliable &\ncredible info", "Identify\nfunction", "Ideation",
                 "Objective\nevaluation", "Develop-\nmental\nstrategies", "Implemen-\ntation"]
        notes = ["Research — information brings value",
                 "Clarify the information into actionable functions",
                 "Brainstorm: better quality at lower expense",
                 "Compare alternatives without bias: cost, function, reliability",
                 "Research & in-depth analysis of shortlisted ideas; firm up costs",
                 "Put the chosen alternative into practice"]
        cols = [SKY, TEAL, GOLD, CORAL, VIOLET, LIME]
        center = LEFT * 2.8 + DOWN * 0.4
        radius = 2.2
        hub = Circle(0.9, color=INK).move_to(center)
        hub_t = T("VE\nprocess", 22, INK, weight="BOLD").move_to(hub)
        self.play(Create(hub), FadeIn(hub_t))
        prev = None
        for i, (s, n, c) in enumerate(zip(steps, notes, cols)):
            ang = PI / 2 - i * TAU / 6
            pos = center + radius * np.array([np.cos(ang), np.sin(ang), 0])
            label = T(s, 15, INK)
            label.scale_to_fit_width(min(label.width, 1.25))
            node = VGroup(Circle(0.72, color=c, fill_opacity=0.25), label).move_to(pos)
            num = T(str(i + 1), 18, c, weight="BOLD").next_to(node, UR, buff=-0.15)
            note = T(f"{i + 1}. {n}", 22, c).move_to(RIGHT * 3.6 + DOWN * 0.4)
            note.scale_to_fit_width(min(note.width, 6.2))
            anims = [FadeIn(node, scale=0.7), FadeIn(num)]
            if prev is not None:
                anims.append(FadeOut(prev))
            self.play(*anims, FadeIn(note, shift=LEFT * 0.2), run_time=0.7)
            self.wait(1.2)
            prev = note
        ring = Circle(radius, color=MUTED, stroke_width=2).move_to(center)
        self.play(Create(ring), FadeOut(prev))
        tip = T("Most effective when done BEFORE design,\nnot after", 22, GOLD).move_to(RIGHT * 3.6)
        self.play(Write(tip))
        self.wait(2)
        self.clear_all()

    def applications(self):
        self.section("Application Areas", TEAL)
        apps = [("Construction &\nCivil", "Cut cost, keep\nfunction & safety", SKY),
                ("Manufacturing &\nIndustrial design", "Redesign, material\nsubstitution", GOLD),
                ("Automotive &\nAerospace", "Reduce weight,\ncost, complexity", CORAL),
                ("Architecture &\nBuilding services", "HVAC, space,\nenergy efficiency", VIOLET),
                ("Healthcare &\nMedical", "Quality care at\nlower cost", LIME)]
        cols = VGroup(*[VGroup(box(a, c, 19, 2.45, 1.2, 0.3), T(d, 17, INK)).arrange(DOWN, buff=0.3)
                        for a, d, c in apps]).arrange(RIGHT, buff=0.2)
        self.play(LaggedStart(*[FadeIn(c, shift=UP * 0.3) for c in cols], lag_ratio=0.25))
        self.wait(2.5)
        self.clear_all()

    def advantages(self):
        self.section("Advantages of Value Engineering", TEAL)
        adv = ["Cost reduction", "Improved functionality", "Profitability", "Innovation",
               "Resource optimisation", "Better decisions", "Project improvement",
               "Team collaboration", "Customer satisfaction", "Sustainability"]
        cols = [SKY, TEAL, GOLD, CORAL, VIOLET, LIME, SKY, TEAL, GOLD, LIME]
        grid = VGroup(*[box(a, c, 21, 3.9, 0.75, 0.2) for a, c in zip(adv, cols)])
        grid.arrange_in_grid(5, 2, buff=(0.6, 0.22), flow_order="dr").shift(DOWN * 0.25)
        for g in grid:
            self.play(FadeIn(g, shift=RIGHT * 0.2), run_time=0.3)
        self.play(Indicate(grid[3], color=GOLD))
        self.wait(2)
        self.clear_all()

    def summary(self):
        self.section("Summary", TEAL)
        pts = bullets(["A systematic process to improve value: cut cost, enhance function",
                       "Essential functions at the lowest total cost over the life\n"
                       "(capital, staffing, energy, maintenance)",
                       "Creative, organised effort by multi-disciplinary teams",
                       "Explore alternative designs, materials and methods\n"
                       "without sacrificing functionality"], 24, bullet_color=TEAL, buff=0.4)
        self.play(LaggedStart(*[FadeIn(p, shift=RIGHT * 0.2) for p in pts], lag_ratio=0.4))
        eq = box("V = F / C", GOLD, 36).to_edge(DOWN, buff=0.5)
        self.play(FadeIn(eq, scale=0.8))
        self.wait(3)
        self.clear_all()
