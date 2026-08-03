"""Find the airport pair that needs the most layovers to connect.

Models the world's scheduled flight network as an undirected graph (airports =
nodes, non-stop routes = edges) and finds its diameter: the pair of airports
whose shortest itinerary requires the largest number of flights. Layovers =
flights - 1.

Data: OpenFlights routes.dat / airports.dat
  https://raw.githubusercontent.com/jpatokal/openflights/master/data/

Usage:
    python analyze_layovers.py [--data-dir DIR] [--keep-heliports]
"""

import argparse
import collections
import csv
import os
import urllib.request

BASE_URL = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/"
FILES = ("airports.dat", "routes.dat")

# Scheduled heliport and seaplane "milk runs" (Greenland's coastal heliports,
# Kenmore Air's San Juan Islands water aerodromes) list every hop as its own
# segment, which inflates hop counts without reflecting how anyone actually
# travels. Excluded by default.
EXCLUDE_NAME_WORDS = ("Heliport", "Seaplane", "Water Aerodrome")
# Codes that appear in routes.dat but are missing from airports.dat; all are
# Greenland heliports or Washington State seaplane bases.
EXCLUDE_CODES = {"SVR", "QUV", "QFN", "WSX", "DHB", "RCE", "FBS", "LKE",
                 "JUK", "IKE", "SRK"}


def fetch(data_dir):
    os.makedirs(data_dir, exist_ok=True)
    for fname in FILES:
        path = os.path.join(data_dir, fname)
        if not os.path.exists(path):
            urllib.request.urlretrieve(BASE_URL + fname, path)
    return data_dir


def load_airports(data_dir):
    airports = {}
    with open(os.path.join(data_dir, "airports.dat"), encoding="utf-8") as f:
        for row in csv.reader(f):
            if len(row) > 4 and row[4] not in ("", "\\N"):
                airports[row[4]] = (row[1], row[2], row[3])
    return airports


def load_graph(data_dir, airports, keep_heliports):
    def skip(code):
        if keep_heliports:
            return False
        if code in EXCLUDE_CODES:
            return True
        name = airports.get(code, ("",))[0]
        return name == "" or any(w in name for w in EXCLUDE_NAME_WORDS)

    graph = collections.defaultdict(set)
    with open(os.path.join(data_dir, "routes.dat"), encoding="utf-8") as f:
        for row in csv.reader(f):
            if len(row) < 5:
                continue
            src, dst = row[2], row[4]
            if src == "\\N" or dst == "\\N" or src == dst:
                continue
            if skip(src) or skip(dst):
                continue
            # Routes are near-always operated in both directions.
            graph[src].add(dst)
            graph[dst].add(src)
    return graph


def bfs(graph, source):
    dist = {source: 0}
    queue = collections.deque([source])
    while queue:
        node = queue.popleft()
        for nbr in graph[node]:
            if nbr not in dist:
                dist[nbr] = dist[node] + 1
                queue.append(nbr)
    return dist


def components(graph):
    seen, comps = set(), []
    for node in graph:
        if node not in seen:
            reached = set(bfs(graph, node))
            comps.append(reached)
            seen |= reached
    return sorted(comps, key=len, reverse=True)


def shortest_path(graph, dist, source, target):
    path, node = [target], target
    while node != source:
        node = next(n for n in graph[node] if dist.get(n, 1 << 30) == dist[node] - 1)
        path.append(node)
    return path[::-1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--keep-heliports", action="store_true",
                        help="include heliports and seaplane bases")
    args = parser.parse_args()

    data_dir = fetch(args.data_dir)
    airports = load_airports(data_dir)
    graph = load_graph(data_dir, airports, args.keep_heliports)

    def label(code):
        name, city, country = airports.get(code, ("unknown", "?", "?"))
        return f"{code} ({name}, {city}, {country})"

    comps = components(graph)
    main_comp = comps[0]
    edges = sum(len(v) for v in graph.values()) // 2
    print(f"airports: {len(graph)}  non-stop links: {edges}")
    print(f"main network: {len(main_comp)}  stranded groups: {[len(c) for c in comps[1:]]}\n")

    diameter, pairs, eccentricity = 0, [], {}
    for source in main_comp:
        dist = bfs(graph, source)
        worst = max(dist.values())
        eccentricity[source] = worst
        if worst > diameter:
            diameter, pairs = worst, []
        if worst == diameter:
            pairs += [(source, k) for k, v in dist.items() if v == diameter]

    print(f"=== Network diameter: {diameter} flights = {diameter - 1} layovers ===")
    shown = set()
    for src, dst in pairs:
        key = tuple(sorted((src, dst)))
        if key in shown:
            continue
        shown.add(key)
        path = shortest_path(graph, bfs(graph, src), src, dst)
        print(f"\n{label(src)}\n  <-> {label(dst)}\n  {' -> '.join(path)}")

    print("\n=== Hardest-to-reach airports (worst-case itinerary) ===")
    for code, ecc in sorted(eccentricity.items(), key=lambda kv: -kv[1])[:12]:
        print(f"  {ecc - 1} layovers: {label(code)}")

    hist = collections.Counter()
    for source in main_comp:
        hist.update(bfs(graph, source).values())
    total = sum(hist.values())
    print("\n=== Distribution over all airport pairs ===")
    for hops in sorted(h for h in hist if h):
        print(f"  {hops - 1:2d} layovers: {hist[hops] / total * 100:5.2f}%")


if __name__ == "__main__":
    main()
