"""HTTP API.

Thin by design: every handler validates, delegates to `PramaanService`, and
formats. No analysis lives here, so the API and the CLI cannot drift apart.

Errors are typed rather than generic. An endpoint that needs an index it does
not have returns 503 with the action that fixes it, because "Internal Server
Error" tells an operator nothing they can act on.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from . import __version__
from .config import Config
from .service import NotReady, PramaanService
from .util.logging import configure, get_logger

log = get_logger("api")

_service: PramaanService | None = None


def get_service() -> PramaanService:
    global _service
    if _service is None:
        _service = PramaanService(Config())
    return _service


# ------------------------------------------------------------- schemas ---


class IngestRequest(BaseModel):
    model_config = {"extra": "forbid"}
    days: int = Field(default=240, ge=30, le=2000,
                      description="Length of the synthetic corpus, in days.")
    seed: int | None = Field(default=None, description="Overrides the config seed.")


class SearchRequest(BaseModel):
    model_config = {"extra": "forbid"}
    query: str = Field(min_length=1, max_length=1000)
    as_of: datetime | None = Field(
        default=None,
        description="Forecast origin. Documents *published* at or after this are "
                    "excluded. Acquisition time (`retrieved_at`) is NOT applied "
                    "here -- see `cutoff_rule` in the response. Omit only for "
                    "retrospective study.",
    )
    k: int = Field(default=20, ge=1, le=200)
    stop_after: Literal["sparse", "dense", "fusion", "late", "rerank"] = "rerank"


class Component(BaseModel):
    bm25: float | None = None
    dense: float | None = None
    late: float | None = None
    cross: float | None = None
    rrf: float | None = None
    recency: float | None = None
    source_independence: float | None = None


class SearchHit(BaseModel):
    doc_id: str
    score: float
    components: dict[str, float]
    published_at: datetime | None
    source_id: str
    source_family: str
    title: str
    span: str


class SearchResponse(BaseModel):
    query: str
    as_of: datetime | None
    cutoff_rule: str = Field(
        description="Which temporal rule this response actually enforced. "
                    "`publication_only` means acquisition latency was not "
                    "applied and the result is not a backtest measurement."
    )
    measures: str = Field(
        description="What the ranking is and is not evidence about."
    )
    cascade: dict[str, Any]
    results: list[SearchHit]


class StatusResponse(BaseModel):
    ready: bool
    profile: str
    config_fingerprint: str
    documents_raw: int
    documents_canonical: int
    built_at: datetime | None
    build_seconds: float
    stage0: dict[str, Any] | None


class ClusterResponse(BaseModel):
    canonical: str
    members: list[str]
    size: int
    distinct_source_families: int
    independence: float = Field(
        description="Distinct source families over cluster size. Low values mean "
                    "the story is one voice republished, not corroboration."
    )


# ----------------------------------------------------------------- app ---


def create_app(config: Config | None = None) -> FastAPI:
    configure()
    app = FastAPI(
        title="PRAMAAN-X evidence retrieval",
        version=__version__,
        summary="Precursor-evidence retrieval cascade (stages 0-3). Not a forecasting service.",
        description=(
            "Evidence retrieval and cascade telemetry.\n\n"
            "**This service retrieves evidence. It does not forecast events.** "
            "Stages 4 (risk models) and 5 (conformal risk control) are not "
            "implemented, so nothing here produces a calibrated probability, a "
            "tier or a lead time.\n\n"
            "`/search` takes an `as_of` forecast origin and applies a "
            "**publication cutoff only**: documents published at or after that "
            "instant are never returned. It does *not* apply the full "
            "availability rule (`max(published_at, retrieved_at)`), because the "
            "served index is built once over the whole corpus rather than per "
            "origin. Use the `oracle_target_retrieval` benchmark "
            "(`pramaan bench`) for anything reported as a measurement; this "
            "endpoint is an interactive tool, and its response says so in "
            "`cutoff_rule`."
        ),
    )
    if config is not None:
        global _service
        _service = PramaanService(config)

    @app.exception_handler(NotReady)
    async def _not_ready(_request, exc: NotReady):
        raise HTTPException(status_code=503, detail=str(exc))

    static = Path(__file__).parent / "static"

    @app.get("/", include_in_schema=False)
    def dashboard():
        """Analyst console. Served from the API so there is one origin and no
        CORS configuration to get wrong; a Next.js front end consuming the same
        endpoints drops in without any server-side change."""
        return FileResponse(static / "index.html")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return Response(
            content=(
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
                '<rect width="32" height="32" rx="6" fill="#0d6a8b"/>'
                '<path d="M8 22V10h6a4 4 0 010 8H8" stroke="#fff" stroke-width="2.5" fill="none"/>'
                "</svg>"
            ),
            media_type="image/svg+xml",
        )

    @app.get("/health", tags=["ops"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/status", response_model=StatusResponse, tags=["ops"])
    def status(svc: PramaanService = Depends(get_service)) -> dict[str, Any]:
        return svc.status()

    @app.get("/config", tags=["ops"])
    def config_(svc: PramaanService = Depends(get_service)) -> dict[str, Any]:
        return {"fingerprint": svc.config.fingerprint(), "config": svc.config.to_dict()}

    @app.post("/ingest/synthetic", response_model=StatusResponse, tags=["corpus"])
    def ingest(req: IngestRequest,
               svc: PramaanService = Depends(get_service)) -> dict[str, Any]:
        """Build a synthetic corpus and index it. Used for demos and CI."""
        return svc.load_synthetic(days=req.days, seed=req.seed)

    @app.post("/search", response_model=SearchResponse, tags=["retrieval"])
    def search(req: SearchRequest,
               svc: PramaanService = Depends(get_service)) -> dict[str, Any]:
        try:
            return svc.search(req.query, as_of=req.as_of, k=req.k,
                              stop_after=req.stop_after)
        except NotReady as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/documents/{doc_id}", tags=["corpus"])
    def document(doc_id: str,
                 svc: PramaanService = Depends(get_service)) -> dict[str, Any]:
        try:
            return svc.document(doc_id)
        except NotReady as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except KeyError:
            raise HTTPException(status_code=404,
                                detail=f"no document {doc_id!r}") from None

    @app.get("/documents/{doc_id}/cluster", response_model=ClusterResponse,
             tags=["corpus"])
    def cluster(doc_id: str,
                svc: PramaanService = Depends(get_service)) -> dict[str, Any]:
        """Near-duplicate cluster and its source independence."""
        try:
            return svc.cluster(doc_id)
        except NotReady as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/timeline", tags=["corpus"])
    def timeline(days: int = Query(default=90, ge=1, le=2000),
                 svc: PramaanService = Depends(get_service)) -> dict[str, Any]:
        try:
            return svc.timeline(days=days)
        except NotReady as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    return app


app = create_app()
