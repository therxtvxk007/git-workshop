# Which two airports need the most layovers?

Computed by treating the world's scheduled flight network as a graph (airports =
nodes, non-stop routes = edges) and finding its **diameter** — the pair of
airports whose *best possible* itinerary still takes the most flights.

Data: [OpenFlights](https://github.com/jpatokal/openflights) — 3,241 airports,
18,913 non-stop links after filtering. Reproduce with
`python analyze_layovers.py`.

## Answer

**Peawanuck, Ontario (YPO) ↔ Birdsville, Queensland (BVI) — 12 flights, 11 layovers.**

```
BVI → BEU → BQL → ISA → BNE → LAX → YYZ → YTS → YMO → YFA → ZKE → YAT → YPO
```

Nine airports tie at the 11-layover maximum, and **YPO (Peawanuck) is on one
side of almost every one of them** — it is the single hardest-to-reach airport
in the network. Its partners at 11 layovers:

| Partner | Location |
| --- | --- |
| BVI Birdsville | Queensland, Australia |
| XTG Thargomindah | Queensland, Australia |
| PTJ Portland | Victoria, Australia |
| STZ Santa Terezinha | Mato Grosso, Brazil |
| CMP Santana do Araguaia | Pará, Brazil |
| FMI Kalemie | DR Congo |
| THU Thule / Pituffik | Greenland |
| YZG Salluit | Nunavik, Québec, Canada |

The one pair not involving YPO: **THU (Thule, Greenland) ↔ YZG (Salluit,
Québec)** — also 11 layovers, and geographically only ~1,500 km apart. They sit
at the ends of two different Arctic dead-end chains, so connecting them means
flying all the way south to Europe and back.

```
THU → NAQ → JUV → JAV → GOH → KEF → ZRH → YUL → YVP → YKG → YQC → YWB → YZG
```

## Why these pairs

Every long path has the same shape: a **dead-end regional chain** at each end,
joined by one or two hops through a global hub.

- YPO sits at the tip of Air Creebec's James Bay milk run
  (YPO → YAT → ZKE → YFA → YMO), five hops before reaching Toronto.
- Outback Queensland routes (BVI → BEU → BQL → ISA) are a mirror image on the
  Australian side.
- Greenland's west coast (THU → NAQ → JUV → JAV → GOH) is a single linear chain
  with no shortcuts.

The intercontinental leg is the *cheap* part — Toronto to Brisbane is 2 hops.
The cost is all in the last-mile chains.

## Context: how the rest of the world compares

| Layovers | Share of all airport pairs |
| --- | --- |
| 0 (non-stop) | 0.36% |
| 1 | 6.10% |
| 2 | 28.86% |
| 3 | 37.96% |
| 4 | 18.29% |
| 5 | 6.31% |
| 6 | 1.61% |
| 7 | 0.38% |
| 8 | 0.08% |
| 9 | 0.01% |
| 10–11 | <0.01% |

**91.6% of all airport pairs are within 4 layovers.** The 11-layover pairs are
a vanishingly thin tail — consistent with the published finding that the airline
network has a small, dense core and a fragile star-like periphery
([Verma et al., *Scientific Reports*](https://www.nature.com/articles/srep05638)).

Also worth noting: 21 airports sit in **four small pockets completely cut off**
from the main network (sizes 10, 4, 4, 3) — mostly intra-island operations with
no link to the global graph. Those pairs are unreachable by air at any number of
layovers, so they're excluded from the diameter.

## Method notes and caveats

- **Hop count, not travel time.** Minimum number of flights, ignoring schedules,
  overnight waits, seasonal service and whether any airline will actually sell
  the itinerary as one ticket. Real-world travel to Peawanuck would take days.
- **Heliports and seaplane bases are excluded by default.** Greenland's coastal
  heliports and Kenmore Air's San Juan Islands water aerodromes list every leg
  as a separate segment. Including them (`--keep-heliports`) pushes the diameter
  to **13 flights / 12 layovers**, with SVR (Savissivik, Greenland) and LPS
  (Lopez Island, WA) joining the set — but those chains are an artifact of how
  milk-run segments are recorded, not of genuine remoteness.
- **Routes treated as undirected.** OpenFlights routes are operated in both
  directions in essentially all cases.
- **The dataset is a snapshot** (OpenFlights route data is not continuously
  maintained). The specific pairs shift as regional carriers add and drop
  routes; the *structure* of the answer — Arctic Canada, outback Australia,
  interior Brazil, Greenland, eastern DR Congo — is stable.
