"""Synthetic event stream with known ground truth.

This is not decoration. Without a corpus whose latent process we control, none
of the claims the system makes -- lead time, false alarms at fixed recall,
certified false-negative risk -- can be checked. The generator deliberately
builds in every failure mode the cascade is supposed to survive:

  * syndication          one report reappears under many source ids, so naive
                         evidence counting mistakes repetition for corroboration
  * unforecastable events a fraction of events emit no precursor at all, so
                         perfect recall is genuinely unattainable and a model
                         claiming it is overfitting
  * regime changes       baseline intensity shifts at change points, giving
                         CUSUM and BOCPD something real to detect
  * post-event reporting documents published *after* an event describe it in
                         the clearest possible language -- the leakage trap
  * weak diffuse signal  precursors are individually uninformative; only
                         accumulation separates them from noise
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import numpy as np

from ..types import Document, Modality, Target
from ..util.hashing import content_hash

# --------------------------------------------------------------- lexicons ---

EVENT_TYPES = (
    "protest",
    "armed_clash",
    "infrastructure_failure",
    "cyber_incident",
    "supply_disruption",
    "flood",
)

# Precursor phrases: what actually appears in reporting *before* an event.
# Deliberately oblique -- none of these is a giveaway on its own.
PRECURSORS: dict[str, tuple[str, ...]] = {
    "protest": (
        "union representatives rejected the revised wage offer",
        "student groups announced a coordinated campus walkout",
        "the municipal permit for the rally remains under review",
        "opposition figures called for a general strike next week",
        "transport workers voted to escalate their industrial action",
    ),
    "armed_clash": (
        "additional paramilitary units were redeployed to the district",
        "border patrols reported increased movement after dark",
        "a curfew was extended for a further seventy two hours",
        "local commanders accused the other side of violating the truce",
        "residents described sporadic small arms fire overnight",
    ),
    "infrastructure_failure": (
        "engineers flagged deferred maintenance on the transmission corridor",
        "the substation has operated above rated load for three weeks",
        "inspectors recorded corrosion beyond tolerance on the span",
        "backup generation capacity was reported offline for servicing",
        "grid operators issued a third consecutive load advisory",
    ),
    "cyber_incident": (
        "credential stuffing attempts against the portal rose sharply",
        "an unpatched edge appliance remains exposed to the internet",
        "a ransomware affiliate advertised access to a regional operator",
        "administrators reported anomalous outbound traffic at night",
        "a supplier disclosed a breach affecting shared authentication",
    ),
    "supply_disruption": (
        "port congestion pushed average dwell times to record levels",
        "customs clearance backlogs lengthened for a fourth week",
        "a key terminal operator warned of imminent capacity limits",
        "freight forwarders began rerouting cargo through alternate ports",
        "warehouse occupancy exceeded ninety percent across the corridor",
    ),
    "flood": (
        "reservoir levels approached the seasonal spill threshold",
        "the meteorological department extended the heavy rainfall warning",
        "drainage channels remain obstructed after last month's works",
        "upstream catchment saturation reached unusually high levels",
        "embankment seepage was reported at two points along the bund",
    ),
}

# What gets written *after* the event. Unambiguous -- which is why it must
# never be visible to a forecast dated before the event.
POST_EVENT: dict[str, tuple[str, ...]] = {
    "protest": ("thousands marched through the city centre today",
                "the demonstration blocked the arterial road for six hours"),
    "armed_clash": ("an exchange of fire was confirmed early this morning",
                    "casualties were reported following the clash"),
    "infrastructure_failure": ("the outage affected an estimated four hundred thousand users",
                               "the span was closed after the structural failure"),
    "cyber_incident": ("systems were taken offline following the intrusion",
                       "the operator confirmed encryption of internal servers"),
    "supply_disruption": ("shipments were suspended following the closure",
                          "the terminal halted operations this afternoon"),
    "flood": ("floodwaters entered residential areas overnight",
              "relief camps were opened after the inundation"),
}

# Filler is generated combinatorially rather than drawn from a fixed list. A
# small stock pool would make unrelated documents genuinely near-identical, and
# the dedup stage would be measured against a corpus that does not exist.
FILLER_TEMPLATES = (
    "{org} {verb} its {period} {noun} on {day}",
    "a delegation from {org} concluded a {n} day visit to {place}",
    "{org} reported {noun} growth of {pct} percent over the {period}",
    "officials at {org} declined to comment on the {adj} {noun}",
    "the {adj} {noun} at {place} drew {n} participants on {day}",
    "{org} said the {noun} would be reviewed before {day}",
    "a {adj} {noun} was tabled by {org} for the coming {period}",
    "residents of {place} raised {n} objections to the {adj} {noun}",
    "the {period} {noun} published by {org} showed {adj} results",
    "{org} allocated {n} crore to the {adj} {noun} at {place}",
)
_ORGS = ("the municipal corporation", "the state transport authority",
         "the chamber of commerce", "the district administration",
         "the port trust", "the regional bank", "the water board",
         "the electricity board", "the planning department", "the trade council",
         "the housing authority", "the industries association")
_VERBS = ("published", "revised", "circulated", "approved", "deferred", "released")
_PERIODS = ("quarterly", "annual", "monthly", "half yearly", "fortnightly")
_NOUNS = ("performance summary", "budget statement", "tender notice",
          "audit report", "development plan", "fee schedule", "survey findings",
          "procurement list", "maintenance roster", "zoning proposal")
_ADJS = ("revised", "preliminary", "consolidated", "provisional", "amended",
         "draft", "interim", "updated")
_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")

LOCATIONS = (
    "Chennai", "Kochi", "Visakhapatnam", "Pune", "Guwahati", "Jaipur",
    "Bhopal", "Ranchi", "Surat", "Nagpur", "Coimbatore", "Patna",
    "Ludhiana", "Raipur", "Mysuru", "Vadodara",
)

# Sources grouped into syndication families. Copies inside a family are the
# same wire feed rewritten -- they are not independent evidence, and the
# source-independence feature must count families, not source ids.
SOURCE_FAMILIES: dict[str, tuple[str, ...]] = {
    "wire_a": ("wire_a_national", "wire_a_regional", "wire_a_digest", "wire_a_english"),
    "wire_b": ("wire_b_desk", "wire_b_syndicated", "wire_b_wire"),
    "local": ("local_daily", "local_eve", "local_web"),
    "state": ("state_bulletin", "state_gazette"),
    "trade": ("trade_weekly", "trade_portal"),
    "social": ("social_aggregate", "social_monitor"),
}
SOURCE_TO_FAMILY = {s: f for f, ss in SOURCE_FAMILIES.items() for s in ss}
ALL_SOURCES = tuple(SOURCE_TO_FAMILY)

# Reliability drives extractor confidence and the provenance score.
SOURCE_RELIABILITY = {
    "wire_a": 0.90, "wire_b": 0.85, "state": 0.80,
    "trade": 0.75, "local": 0.65, "social": 0.40,
}


@dataclass
class GroundTruth:
    """Everything the generator knows and the system is not allowed to see."""

    events: dict[str, list[datetime]] = field(default_factory=dict)      # target key -> dates
    forecastable: dict[tuple[str, str], bool] = field(default_factory=dict)  # (key, iso) -> had precursor
    intensity: dict[str, np.ndarray] = field(default_factory=dict)       # target key -> per-day latent
    change_points: dict[str, list[int]] = field(default_factory=dict)
    precursor_docs: dict[tuple[str, str], list[str]] = field(default_factory=dict)
    post_event_docs: set[str] = field(default_factory=set)
    duplicate_of: dict[str, str] = field(default_factory=dict)           # doc_id -> canonical doc_id
    targets: list[Target] = field(default_factory=list)
    start: datetime = datetime(2025, 1, 1, tzinfo=UTC)
    days: int = 540

    def events_in_window(self, start: datetime, end: datetime) -> set[str]:
        """Target keys with at least one event in [start, end)."""
        return {
            key for key, dates in self.events.items()
            if any(start <= d < end for d in dates)
        }

    def event_dates_in_window(self, start: datetime, end: datetime) -> dict[str, list[datetime]]:
        out: dict[str, list[datetime]] = {}
        for key, dates in self.events.items():
            hit = [d for d in dates if start <= d < end]
            if hit:
                out[key] = hit
        return out


@dataclass
class SynthConfig:
    n_locations: int = 12
    n_event_types: int = 6
    days: int = 540
    start: datetime = datetime(2025, 1, 1, tzinfo=UTC)
    base_rate: float = 0.006             # per target per day, before modulation
    precursor_lead_days: tuple[int, int] = (2, 21)
    precursor_docs_per_event: tuple[int, int] = (2, 7)
    unforecastable_fraction: float = 0.18   # events with no precursor at all
    filler_docs_per_day: int = 14
    syndication_alpha: float = 2.2       # Pareto tail on copy count
    max_copies: int = 9
    post_event_docs_per_event: tuple[int, int] = (1, 4)
    change_points_per_target: tuple[int, int] = (0, 3)
    seed: int = 20260824


class SyntheticCorpus:
    """Generates documents and the ground truth they were generated from."""

    def __init__(self, cfg: SynthConfig | None = None) -> None:
        self.cfg = cfg or SynthConfig()
        self.rng = np.random.default_rng(self.cfg.seed)
        self.targets = [
            Target(location=loc, event_type=et)
            for loc in LOCATIONS[: self.cfg.n_locations]
            for et in EVENT_TYPES[: self.cfg.n_event_types]
        ]

    # -------------------------------------------------------- intensity ---

    def _latent_intensity(self, target: Target) -> tuple[np.ndarray, list[int]]:
        """Per-day latent intensity: baseline x seasonal x regime x tension."""
        cfg, rng = self.cfg, self.rng
        T = cfg.days
        t = np.arange(T)

        # Baseline varies by target -- some places/types are simply commoner.
        baseline = cfg.base_rate * np.exp(rng.normal(0.0, 0.55))

        # Annual and weekly seasonality. Floods are strongly seasonal; cyber
        # incidents essentially are not. That difference is what makes MTRM's
        # per-event-type horizon selection worth having.
        seasonal_amp = {"flood": 0.95, "protest": 0.35, "supply_disruption": 0.30,
                        "armed_clash": 0.20, "infrastructure_failure": 0.25,
                        "cyber_incident": 0.05}[target.event_type]
        phase = rng.uniform(0, 2 * np.pi)
        annual = 1.0 + seasonal_amp * np.sin(2 * np.pi * t / 365.25 + phase)
        weekly_amp = 0.25 if target.event_type == "protest" else 0.05
        weekly = 1.0 + weekly_amp * np.sin(2 * np.pi * t / 7.0)

        # Regime changes: piecewise multiplicative level shifts.
        n_cp = rng.integers(cfg.change_points_per_target[0], cfg.change_points_per_target[1] + 1)
        cps = sorted(rng.choice(np.arange(30, T - 30), size=int(n_cp), replace=False).tolist()) if n_cp else []
        regime = np.ones(T)
        level = 1.0
        prev = 0
        for cp in cps:
            regime[prev:cp] = level
            level *= float(np.exp(rng.normal(0.0, 0.7)))
            prev = cp
        regime[prev:] = level

        # Slow AR(1) "tension" -- persistent drift that gives long-window
        # retrieval (LANTERN's long arm) something to lock onto.
        tension = np.zeros(T)
        for i in range(1, T):
            tension[i] = 0.97 * tension[i - 1] + rng.normal(0.0, 0.12)
        tension = np.exp(tension - tension.mean())

        lam = baseline * annual * weekly * regime * tension
        return np.clip(lam, 1e-6, 0.9), cps

    # -------------------------------------------------------- generation ---

    def generate(self) -> tuple[list[Document], GroundTruth]:
        cfg, rng = self.cfg, self.rng
        gt = GroundTruth(start=cfg.start, days=cfg.days, targets=list(self.targets))
        docs: list[Document] = []
        seq = 0

        def new_id() -> str:
            nonlocal seq
            seq += 1
            return f"d{seq:07d}"

        # 1. Latent processes and events.
        pending: list[tuple[Target, datetime, bool]] = []   # (target, date, forecastable)
        for target in self.targets:
            lam, cps = self._latent_intensity(target)
            key = target.key()
            gt.intensity[key] = lam
            gt.change_points[key] = cps
            draws = rng.random(cfg.days)
            fired = np.nonzero(draws < lam)[0]
            dates = [cfg.start + timedelta(days=int(d)) for d in fired]
            gt.events[key] = dates
            for d in dates:
                forecastable = rng.random() > cfg.unforecastable_fraction
                gt.forecastable[(key, d.isoformat())] = forecastable
                pending.append((target, d, forecastable))

        # 2. Precursor documents, emitted before their event.
        for target, date, forecastable in pending:
            key = target.key()
            if not forecastable:
                continue
            n_docs = int(rng.integers(*cfg.precursor_docs_per_event))
            phrases = PRECURSORS[target.event_type]
            made: list[str] = []
            for _ in range(n_docs):
                lead = int(rng.integers(*cfg.precursor_lead_days))
                pub = date - timedelta(days=lead, hours=int(rng.integers(0, 24)))
                if pub < cfg.start:
                    continue
                body = self._compose(target, rng.choice(phrases), rng, precursor=True)
                canonical = self._emit(docs, new_id(), body, target, pub, rng, gt)
                made.append(canonical)
            if made:
                gt.precursor_docs[(key, date.isoformat())] = made

        # 3. Post-event reports. These are the leakage trap.
        for target, date, _ in pending:
            n_docs = int(rng.integers(*cfg.post_event_docs_per_event))
            for _ in range(n_docs):
                lag = int(rng.integers(0, 3))
                pub = date + timedelta(days=lag, hours=int(rng.integers(1, 24)))
                if pub >= cfg.start + timedelta(days=cfg.days):
                    continue
                body = self._compose(target, rng.choice(POST_EVENT[target.event_type]),
                                     rng, precursor=False)
                canonical = self._emit(docs, new_id(), body, target, pub, rng, gt)
                gt.post_event_docs.add(canonical)

        # 4. Background noise, so the retained stream is not trivially separable.
        for day in range(cfg.days):
            for _ in range(cfg.filler_docs_per_day):
                pub = cfg.start + timedelta(days=day, hours=int(rng.integers(0, 24)))
                loc = str(rng.choice(LOCATIONS[: cfg.n_locations]))
                body = (f"{loc}: {self._filler(rng, loc)}. "
                        f"{self._filler(rng, loc)}. {self._filler(rng, loc)}.")
                target = Target(location=loc, event_type="none")
                self._emit(docs, new_id(), body, target, pub, rng, gt, noise=True)

        docs.sort(key=lambda d: d.published_at)
        return docs, gt

    # ------------------------------------------------------------ helpers ---

    def _filler(self, rng, place: str) -> str:
        """One filler sentence, assembled from slots. The template space is
        large enough (~10^7) that two unrelated documents colliding is a real
        duplicate rather than an artefact of a short vocabulary list."""
        tpl = str(rng.choice(FILLER_TEMPLATES))
        return tpl.format(
            org=str(rng.choice(_ORGS)), verb=str(rng.choice(_VERBS)),
            period=str(rng.choice(_PERIODS)), noun=str(rng.choice(_NOUNS)),
            adj=str(rng.choice(_ADJS)), day=str(rng.choice(_DAYS)),
            place=place, n=int(rng.integers(2, 400)),
            pct=round(float(rng.uniform(0.4, 18.0)), 1),
        )

    def _compose(self, target: Target, phrase: str, rng, *, precursor: bool) -> str:
        """Bury the signal in plausible surroundings. A precursor sentence that
        arrived alone in a two-sentence document would make stage 1 trivial."""
        loc = target.location
        pad = [self._filler(rng, loc) for _ in range(int(rng.integers(1, 4)))]
        parts = [*pad[:1], f"In {loc}, {phrase}", *pad[1:]]
        if precursor and rng.random() < 0.5:
            parts.append(self._filler(rng, loc))
        return ". ".join(parts) + "."

    def _emit(self, docs: list[Document], doc_id: str, body: str, target: Target,
              pub: datetime, rng, gt: GroundTruth, *, noise: bool = False) -> str:
        """Write one canonical document plus its syndicated copies."""
        family = str(rng.choice(list(SOURCE_FAMILIES)))
        source = str(rng.choice(SOURCE_FAMILIES[family]))
        title = f"{target.location} update"
        canonical = Document(
            doc_id=doc_id,
            source_id=source,
            title=title,
            text=body,
            published_at=pub,
            retrieved_at=pub + timedelta(minutes=int(rng.integers(1, 240))),
            language="en",
            modality=Modality.TEXT,
            content_hash=content_hash(title, body),
            meta={"synth_target": target.key(), "synth_noise": noise,
                  "source_family": family},
        )
        docs.append(canonical)

        # Syndication: Pareto-tailed copy count, mostly 0-1 but occasionally
        # a story that reappears everywhere.
        n_copies = min(int(rng.pareto(self.cfg.syndication_alpha)), self.cfg.max_copies)
        for _ in range(n_copies):
            fam2 = str(rng.choice(list(SOURCE_FAMILIES)))
            src2 = str(rng.choice(SOURCE_FAMILIES[fam2]))
            text2 = self._paraphrase(body, rng)
            cid = f"{doc_id}c{rng.integers(1000, 9999)}"
            docs.append(Document(
                doc_id=cid,
                source_id=src2,
                title=title,
                text=text2,
                published_at=pub + timedelta(hours=int(rng.integers(0, 30))),
                retrieved_at=pub + timedelta(hours=int(rng.integers(1, 36))),
                content_hash=content_hash(title, text2),
                meta={"synth_target": target.key(), "synth_noise": noise,
                      "source_family": fam2, "syndicated": True},
            ))
            gt.duplicate_of[cid] = doc_id
        return doc_id

    @staticmethod
    def _paraphrase(text: str, rng) -> str:
        """Wire-desk rewriting: light substitution and boilerplate, never a
        rewrite deep enough to defeat shingle overlap -- that is the point."""
        subs = {" said ": " stated ", " reported ": " noted ", "  ": " ",
                " remains ": " continues to be ", " rose ": " climbed ",
                " announced ": " declared "}
        out = text
        for a, b in subs.items():
            if rng.random() < 0.5:
                out = out.replace(a, b)
        if rng.random() < 0.7:
            out = out + " (Agency copy.)"
        return out
