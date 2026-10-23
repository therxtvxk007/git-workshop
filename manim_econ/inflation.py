"""Module 3: Inflation — causes, effects, control measures, repo & reverse repo."""

from manim import *

from common import (CORAL, GOLD, INK, LIME, MUTED, SKY, TEAL, VIOLET, Lesson,
                    T, axis_labels, box, bullets, chain)


def burger(scale=1.0, layers=1):
    bun_top = ArcBetweenPoints(LEFT * 1.1, RIGHT * 1.1, angle=-PI * 0.9, color="#e0a050")
    bun_top.add_line_to(LEFT * 1.1).set_fill("#e0a050", 1).set_stroke(width=0)
    stack = VGroup(bun_top)
    y = -0.05
    for _ in range(layers):
        for col, h in (("#7cc35a", 0.1), ("#6b3b25", 0.22), ("#ffd23f", 0.08)):
            stack.add(Rectangle(width=2.2, height=h, color=col, fill_opacity=1,
                                stroke_width=0).move_to(UP * (y - h / 2)))
            y -= h
    stack.add(RoundedRectangle(width=2.2, height=0.3, corner_radius=0.12, color="#e0a050",
                               fill_opacity=1, stroke_width=0).move_to(UP * (y - 0.15)))
    return stack.scale(scale)


class Inflation(Lesson):
    def construct(self):
        self.opening("Inflation", "Causes · Effects · Control · Repo & Reverse Repo", CORAL)
        self.definition()
        self.village_story()
        self.causes()
        self.effects()
        self.effects_on_investment_production()
        self.monetary_policy()
        self.fiscal_policy()
        self.supply_management()
        self.repo_rates()
        self.recap()

    def definition(self):
        self.section("What is Inflation?", CORAL)
        d = T("More money in the economy than stuff to spend it on\n→ prices rise", 28, INK)
        d.shift(UP * 1.7)
        self.play(Write(d))
        then = burger(0.9, 3).shift(LEFT * 3 + DOWN * 1)
        now = burger(0.9, 1).shift(RIGHT * 3 + DOWN * 1)
        lt = T("THEN · ₹150", 26, LIME).next_to(then, DOWN, buff=0.3)
        ln = T("NOW · ₹150", 26, CORAL).next_to(now, DOWN, buff=0.3)
        self.play(FadeIn(then, shift=UP * 0.3), FadeIn(lt))
        self.play(TransformFromCopy(then, now), FadeIn(ln))
        msg = T("Same money, less burger: purchasing power falls", 24, GOLD).to_edge(DOWN, buff=0.3)
        self.play(Write(msg))
        self.wait(2)
        self.clear_all()

    def village_story(self):
        self.section("A Village Story", CORAL)
        steps = ["Economy not growing → RBI lends at 1%", "Banks flush with cash → cheap loans",
                 "People buy luxuries (electric bikes)", "Demand > supply → shops run out",
                 "Sellers raise prices: ₹1,00,000 → ₹1,50,000", "INFLATION"]
        cols = [SKY, SKY, TEAL, GOLD, CORAL, CORAL]
        nodes, arrows = chain(steps, cols, DOWN, 0.22, 20, width=6.2)
        VGroup(nodes, arrows).scale(0.92).to_edge(LEFT, buff=0.6).shift(DOWN * 0.35)
        self.play_chain(nodes, arrows, 0.5)

        # bike price tag climbing
        tracker = ValueTracker(100000)
        tag = always_redraw(lambda: box(f"Bike  ₹{int(tracker.get_value()):,}", GOLD, 28)
                            .move_to(RIGHT * 3.6 + UP * 1.2))
        self.add(tag)
        self.play(tracker.animate.set_value(150000), run_time=2.5)
        after = VGroup(
            T("If it continues…", 22, MUTED),
            T("Currency value ↓", 24, CORAL),
            T("Purchasing power ↓ → Demand ↓", 24, CORAL),
            T("Business dull → Unemployment ↑", 24, CORAL),
            T("→ RECESSION", 28, VIOLET, weight="BOLD"),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.2).move_to(RIGHT * 3.6 + DOWN * 1.3)
        self.play(LaggedStart(*[FadeIn(a, shift=LEFT * 0.2) for a in after], lag_ratio=0.4))
        note = T("Moderate inflation is good for a short time; runaway inflation is not", 20, GOLD)
        note.to_edge(DOWN, buff=0.15)
        self.play(FadeIn(note))
        self.wait(2)
        self.clear_all()

    def causes(self):
        self.section("Causes of Inflation", CORAL)
        names = ["Money\nSupply", "National\nDebt", "Demand-Pull\nEffect", "Cost-Push\nEffect",
                 "Exchange\nRates"]
        cols = [SKY, VIOLET, GOLD, CORAL, TEAL]
        cards = VGroup(*[box(n, c, 22, 2.35, 1.3) for n, c in zip(names, cols)])
        cards.arrange(RIGHT, buff=0.25).shift(UP * 1.4)
        self.play(LaggedStart(*[FadeIn(c, shift=DOWN * 0.3) for c in cards], lag_ratio=0.2))
        details = [
            ("Money supply grows faster than the economy\n→ each rupee is worth less", SKY),
            ("Govt. in debt: raise taxes OR print money\n→ printing money causes inflation", VIOLET),
            ("Company growth ↑ → wages ↑ → purchasing power ↑\n→ demand ↑ beyond supply → prices ↑", GOLD),
            ("Raw-material & labour costs ↑ → passed to consumer\nBiscuit price ₹50 → ₹100 to keep profit", CORAL),
            ("Weaker currency vs the dollar\n→ imports cost more → prices ↑", TEAL),
        ]
        current = None
        for card, (text, col) in zip(cards, details):
            d = T(text, 24, col).shift(DOWN * 1.3)
            hl = SurroundingRectangle(card, color=col, buff=0.08)
            if current:
                self.play(FadeOut(current[0]), FadeOut(current[1]), run_time=0.3)
            self.play(Create(hl), FadeIn(d, shift=UP * 0.2), run_time=0.6)
            self.wait(1.4)
            current = (d, hl)
        self.wait(0.5)
        self.clear_all()

    def effects(self):
        self.section("Effects of Inflation", CORAL)
        axes = Axes(x_range=[0, 10, 2], y_range=[0, 12, 4], x_length=5.5, y_length=3.6,
                    axis_config={"color": MUTED, "include_tip": False}).shift(LEFT * 3.2 + DOWN * 0.6)
        xl = T("years", 18, MUTED).next_to(axes.x_axis, DOWN, buff=0.35)
        yl = T("items ₹100 buys", 18, MUTED).next_to(axes.y_axis, UP, buff=0.1)
        self.play(Create(axes), FadeIn(xl), FadeIn(yl),
                  FadeIn(axis_labels(axes, xs=(2, 4, 6, 8, 10), ys=(4, 8, 12))))
        rate = 0.10
        curve = axes.plot(lambda t: 10 / (1 + rate) ** t, x_range=[0, 10], color=CORAL)
        dot = Dot(axes.c2p(0, 10), color=CORAL)
        self.play(Create(curve), MoveAlongPath(dot, curve), run_time=3)
        cap = T("At 10% inflation, ₹100 buys\n10 items today, ~4 in 10 years", 20, CORAL)
        cap.next_to(axes, DOWN, buff=0.7)
        self.play(FadeIn(cap))
        effects = bullets(["Reduced purchasing power", "Currency value declines",
                           "Higher cost of living → slower growth",
                           "Moderate (2–3%) inflation is healthy:\nhigher wages, profits, momentum"],
                          22, bullet_color=CORAL)
        effects.shift(RIGHT * 3.3 + DOWN * 0.2)
        self.play(LaggedStart(*[FadeIn(e, shift=LEFT * 0.2) for e in effects], lag_ratio=0.4))
        self.play(Indicate(effects[3], color=LIME))
        self.wait(2)
        self.clear_all()

    def effects_on_investment_production(self):
        self.section("Effects on Investment & Production", CORAL)
        inv_h = T("Investment", 28, SKY, weight="BOLD")
        inv = bullets(["Uncertainty & risk → investors hesitate",
                       "Interest rates ↑ → borrowing costlier",
                       "Real returns eroded (esp. fixed income)"], 20, bullet_color=SKY)
        prod_h = T("Production", 28, GOLD, weight="BOLD")
        prod = bullets(["Short-term stimulus at moderate inflation",
                        "Resources shift to non-essential goods",
                        "Uncertainty → output ↓",
                        "Input costs ↑ → margins squeezed"], 20, bullet_color=GOLD)
        left = VGroup(inv_h, inv).arrange(DOWN, aligned_edge=LEFT, buff=0.3)
        right = VGroup(prod_h, prod).arrange(DOWN, aligned_edge=LEFT, buff=0.3)
        VGroup(left, right).arrange(RIGHT, buff=0.9, aligned_edge=UP).shift(UP * 0.6)
        self.play(FadeIn(left, shift=RIGHT * 0.2))
        self.play(FadeIn(right, shift=LEFT * 0.2))
        n, a = chain(["Prices rise", "Inflation", "Demand ↓", "Production ↓"],
                     [CORAL, CORAL, GOLD, GOLD], RIGHT, 0.5, 20)
        VGroup(n, a).to_edge(DOWN, buff=0.6)
        self.play_chain(n, a, 0.4)
        self.wait(2)
        self.clear_all()

    def monetary_policy(self):
        self.section("Control 1 · Monetary Policy (RBI)", SKY)
        steps = ["Reduce excess money supply", "RBI raises interest rate (slowly)",
                 "Investment & purchasing power ↓", "Aggregate demand ↓", "Prices decline",
                 "Inflation controlled ✓"]
        cols = [SKY, SKY, TEAL, TEAL, LIME, LIME]
        nodes, arrows = chain(steps, cols, DOWN, 0.22, 21, width=5.6)
        VGroup(nodes, arrows).scale(0.9).shift(LEFT * 2.5 + DOWN * 0.35)
        self.play_chain(nodes, arrows, 0.45)
        warn = box("Overdo it → business losses\n→ unemployment → recession", CORAL, 22)
        warn.shift(RIGHT * 3.8 + DOWN * 0.4)
        arr = Arrow(nodes[3].get_right(), warn.get_left(), color=CORAL, buff=0.1)
        self.play(GrowArrow(arr), FadeIn(warn))
        self.wait(2)
        self.clear_all()

    def fiscal_policy(self):
        self.section("Control 2 · Fiscal Policy (Government)", GOLD)
        sub = T("Revenue & expenditure policy of the government", 22, MUTED).shift(UP * 2.2)
        self.play(FadeIn(sub))
        steps = ["Increase taxes", "Disposable income ↓", "Consumption ↓", "Aggregate demand ↓",
                 "Prices decline"]
        nodes, arrows = chain(steps, [GOLD] * 3 + [TEAL, LIME], RIGHT, 0.3, 19)
        VGroup(nodes, arrows).scale_to_fit_width(13).shift(UP * 0.9)
        self.play_chain(nodes, arrows, 0.4)

        income = ValueTracker(1000)
        bar = always_redraw(lambda: Rectangle(width=income.get_value() / 1000 * 5, height=0.55,
                                              color=TEAL, fill_opacity=0.8)
                            .align_to(LEFT * 4.5, LEFT).shift(DOWN * 0.9))
        lbl = always_redraw(lambda: T(f"Take-home ₹{int(income.get_value())}", 22, INK)
                            .next_to(bar, RIGHT, buff=0.3))
        cap = T("Income ₹1000: tax raised from ₹100 to ₹150", 22, MUTED).next_to(bar, UP, buff=0.25)
        cap.align_to(LEFT * 4.5, LEFT)
        self.add(bar, lbl)
        self.play(FadeIn(cap))
        self.play(income.animate.set_value(900), run_time=1)
        self.play(income.animate.set_value(850), run_time=1)
        other = T("Also: cut govt. spending · reduce import duties · ban/limit exports · "
                  "raise stock limits", 19, GOLD).to_edge(DOWN, buff=0.4)
        self.play(FadeIn(other))
        self.wait(2)
        self.clear_all()

    def supply_management(self):
        self.section("Control 3 · Supply Management", LIME)
        items = ["Restrict exports of scarce goods,\nincrease imports",
                 "Enforce Essential Commodities Act 1952\n(stop hoarding & speculation)",
                 "Tax concessions, subsidies & support\nto raise production",
                 "Higher MSP (Minimum Support Price)\nto boost food supply"]
        grid = VGroup(*[box(i, LIME, 20, 6.0, 1.4, fill=0.1) for i in items])
        grid.arrange_in_grid(2, 2, buff=0.35).shift(UP * 0.2)
        self.play(LaggedStart(*[FadeIn(g, scale=0.95) for g in grid], lag_ratio=0.3))
        goal = T("Goal: enough supply so demand is met and prices stay calm.\n"
                 "Hoarding shrinks supply → artificial inflation", 21, GOLD).to_edge(DOWN, buff=0.35)
        self.play(Write(goal))
        self.wait(2.5)
        self.clear_all()

    def repo_rates(self):
        self.section("Repo Rate vs Reverse Repo Rate", VIOLET)
        rbi = box("RBI\n(central bank)", VIOLET, 28, 3.2, 1.6).shift(LEFT * 4 + DOWN * 0.3)
        bank = box("Commercial\nbanks", SKY, 28, 3.2, 1.6).shift(RIGHT * 4 + DOWN * 0.3)
        self.play(FadeIn(rbi), FadeIn(bank))

        top = Arrow(rbi.get_right() + UP * 0.4, bank.get_left() + UP * 0.4, color=CORAL, buff=0.15)
        bot = Arrow(bank.get_left() + DOWN * 0.4, rbi.get_right() + DOWN * 0.4, color=TEAL, buff=0.15)
        repo = T("REPO: RBI lends to banks", 22, CORAL).next_to(top, UP, buff=0.15)
        rev = T("REVERSE REPO: banks park money with RBI", 22, TEAL).next_to(bot, DOWN, buff=0.15)
        self.play(GrowArrow(top), FadeIn(repo))
        coins = VGroup(*[Circle(0.12, color=GOLD, fill_opacity=1) for _ in range(4)])
        for i, c in enumerate(coins):
            c.move_to(top.get_start())
        self.play(LaggedStart(*[c.animate.move_to(top.get_end()) for c in coins], lag_ratio=0.25),
                  run_time=1.5)
        self.play(FadeOut(coins))
        self.play(GrowArrow(bot), FadeIn(rev))
        coins2 = VGroup(*[Circle(0.12, color=GOLD, fill_opacity=1).move_to(bot.get_start())
                          for _ in range(4)])
        self.play(LaggedStart(*[c.animate.move_to(bot.get_end()) for c in coins2], lag_ratio=0.25),
                  run_time=1.5)
        self.play(FadeOut(coins2))
        self.wait(1)
        self.play(*[m.animate.shift(UP * 1.2).scale(0.8) for m in (rbi, bank, top, bot, repo, rev)])

        effects = VGroup(
            T("Repo ↑ → borrowing costlier → loans ↓ → inflation ↓", 22, CORAL),
            T("Repo ↓ → cheap loans → spending ↑ → growth ↑", 22, LIME),
            T("Reverse repo ↑ → banks deposit surplus → liquidity ↓ → inflation ↓", 22, TEAL),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.3).to_edge(DOWN, buff=0.5)
        for e in effects:
            self.play(FadeIn(e, shift=UP * 0.15), run_time=0.7)
        self.wait(2.5)
        self.clear_all()

    def recap(self):
        self.section("Recap", CORAL)
        lines = VGroup(
            T("Inflation = too much money chasing too few goods", 26, CORAL),
            T("Causes: money supply · debt · demand-pull · cost-push · exchange rate", 22, INK),
            T("Effects: purchasing power ↓ · cost of living ↑ · (2–3% is healthy)", 22, INK),
            T("Controls: monetary · fiscal · supply management", 22, INK),
            T("Tools: raise repo / reverse repo to cool prices", 22, VIOLET),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.4)
        for l in lines:
            self.play(FadeIn(l, shift=RIGHT * 0.2), run_time=0.6)
        self.wait(3)
        self.clear_all()
