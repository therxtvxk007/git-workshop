"""District neighbour relations, one graph per boundary vintage.

Neighbour features are among the strongest predictors in conflict forecasting,
and also among the easiest to leak through: if adjacency is stored as a single
current graph, a district created in 2023 appears as a neighbour in a 2019
feature window, and the model learns from a place that did not exist.

So adjacency is keyed by ``boundary_version``. A lookup for a vintage that was
never loaded raises rather than falling back to another vintage.

The graph can be declared from a table or derived from polygons. Deriving needs
GeoPandas and PySAL, which are an optional extra; :func:`queen_adjacency_from`
raises a clear install message rather than importing them at module scope.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable
from typing import Any

from pramaanx.schemas.geography import AdjacencyEdge


class AdjacencyError(ValueError):
    """The adjacency edges supplied are unusable."""


class DistrictAdjacency:
    """Symmetric neighbour lookup with deterministic multi-hop traversal."""

    def __init__(self, edges: Iterable[AdjacencyEdge]) -> None:
        graphs: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        for edge in edges:
            graph = graphs[edge.boundary_version]
            # Stored both ways at load time. Requiring the caller to supply both
            # directions turns a one-line omission into a silently asymmetric
            # neighbourhood, which shows up as a feature that works for half the
            # districts.
            graph[edge.district_id].add(edge.neighbour_id)
            graph[edge.neighbour_id].add(edge.district_id)
        self._graphs: dict[str, dict[str, frozenset[str]]] = {
            version: {node: frozenset(peers) for node, peers in sorted(graph.items())}
            for version, graph in sorted(graphs.items())
        }

    @classmethod
    def empty(cls) -> DistrictAdjacency:
        return cls([])

    @property
    def boundary_versions(self) -> list[str]:
        return sorted(self._graphs)

    def _graph(self, boundary_version: str) -> dict[str, frozenset[str]]:
        graph = self._graphs.get(boundary_version)
        if graph is None:
            raise AdjacencyError(
                f"no adjacency loaded for boundary version {boundary_version!r}; "
                f"loaded versions are {self.boundary_versions}. Neighbours are not "
                "carried over between vintages."
            )
        return graph

    def neighbours(self, district_id: str, *, boundary_version: str) -> list[str]:
        """Immediate neighbours, sorted."""
        return sorted(self._graph(boundary_version).get(district_id, frozenset()))

    def within_hops(self, district_id: str, *, boundary_version: str, hops: int) -> dict[str, int]:
        """Every district reachable in at most ``hops`` steps, with its distance.

        Breadth-first with a sorted frontier, so the result is identical on
        every run and every machine. The origin is excluded: a district is not
        its own neighbour, and including it would double-count its own history
        in every neighbour feature.
        """
        if hops < 0:
            raise AdjacencyError("hops must be non-negative")
        graph = self._graph(boundary_version)
        distances: dict[str, int] = {district_id: 0}
        queue: deque[str] = deque([district_id])
        while queue:
            node = queue.popleft()
            depth = distances[node]
            if depth >= hops:
                continue
            for neighbour in sorted(graph.get(node, frozenset())):
                if neighbour not in distances:
                    distances[neighbour] = depth + 1
                    queue.append(neighbour)
        del distances[district_id]
        return dict(sorted(distances.items()))

    def restricted_to(
        self, district_ids: Iterable[str], *, boundary_version: str
    ) -> DistrictAdjacency:
        """The same graph with every edge touching an unknown district dropped.

        Used when the adjacency table covers more districts than the universe in
        effect at a cutoff -- the extra edges are not evidence of anything, they
        are just a later vintage bleeding in.
        """
        allowed = set(district_ids)
        graph = self._graph(boundary_version)
        return DistrictAdjacency(
            AdjacencyEdge(
                boundary_version=boundary_version,
                district_id=node,
                neighbour_id=peer,
                method="declared",
            )
            for node, peers in graph.items()
            if node in allowed
            for peer in sorted(peers)
            if peer in allowed and peer > node
        )


def queen_adjacency_from(
    frame: Any,
    *,
    boundary_version: str,
    district_id_column: str = "district_id",
) -> list[AdjacencyEdge]:
    """Derive Queen contiguity from a GeoDataFrame of district polygons.

    Optional path. GeoPandas and PySAL are not core dependencies because the
    whole pipeline must run in CI without a geospatial stack; a declared
    adjacency table is the reproducible default and this is how that table gets
    generated once, from geoBoundaries ADM2 polygons.
    """
    try:
        from libpysal.weights import Queen  # type: ignore[import-not-found]
    except ImportError as error:  # pragma: no cover - exercised only without the extra
        raise AdjacencyError(
            "deriving adjacency needs the optional geo extra: "
            "pip install 'pramaan-x-zero-base[geo]'"
        ) from error

    if district_id_column not in frame.columns:
        raise AdjacencyError(f"polygon frame has no {district_id_column!r} column")
    ids = [str(value) for value in frame[district_id_column]]
    if len(set(ids)) != len(ids):
        raise AdjacencyError("polygon frame has duplicate district ids")

    weights = Queen.from_dataframe(frame, use_index=False)
    edges: list[AdjacencyEdge] = []
    for position, neighbours in weights.neighbors.items():
        district_id = ids[position]
        for neighbour_position in neighbours:
            neighbour_id = ids[neighbour_position]
            if neighbour_id <= district_id:
                continue  # each undirected edge recorded once
            edges.append(
                AdjacencyEdge(
                    boundary_version=boundary_version,
                    district_id=district_id,
                    neighbour_id=neighbour_id,
                    method="queen",
                )
            )
    return sorted(edges, key=lambda edge: (edge.district_id, edge.neighbour_id))
