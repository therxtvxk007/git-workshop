# Multi-stage: the runtime image carries no compiler and no test dependencies.
#
# The environment is built from `uv.lock` with `--frozen`, so the image contains
# the versions the lockfile pins and nothing else. The previous `pip install
# ".[boost,serve,llm]"` resolved fresh versions at build time, which meant the
# image and the tested environment could differ without anything saying so --
# a reproducibility hole in the one artefact most likely to be shipped.
FROM ghcr.io/astral-sh/uv:0.9.7-python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential libgomp1 && rm -rf /var/lib/apt/lists/*

# Dependencies first, from the lockfile alone, so a source-only change does not
# invalidate the dependency layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --extra boost --extra serve --extra llm

COPY README.md ./
COPY pramaan_x ./pramaan_x
RUN uv sync --frozen --no-editable --extra boost --extra serve --extra llm

# The hash of the lockfile the image was built from. Recorded in the image and
# served on /status, so a running container can be traced back to a dependency
# set rather than to a build date.
RUN sha256sum uv.lock | cut -d' ' -f1 > /opt/venv/uv.lock.sha256

# ---------------------------------------------------------------- runtime ---
FROM python:3.12-slim-bookworm AS runtime

# libgomp is required by LightGBM and XGBoost at runtime; without it the import
# succeeds and the first fit segfaults, which is a miserable thing to debug.
RUN apt-get update && apt-get install -y --no-install-recommends \
      libgomp1 curl && rm -rf /var/lib/apt/lists/* && \
    useradd --create-home --uid 10001 pramaan

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    OMP_NUM_THREADS=4 \
    PRAMAAN_LOCKFILE_SHA256_FILE=/opt/venv/uv.lock.sha256

WORKDIR /app
COPY --chown=pramaan:pramaan pramaan_x ./pramaan_x
COPY --chown=pramaan:pramaan configs ./configs
RUN mkdir -p /app/artifacts /app/.cache && chown -R pramaan:pramaan /app

# Surfaced with `docker inspect`, so the lockfile identity is readable without
# starting the container.
ARG UV_LOCK_SHA256=""
LABEL org.opencontainers.image.title="pramaan-x" \
      org.opencontainers.image.description="Precursor-evidence retrieval cascade (stages 0-3); not a forecasting system" \
      org.opencontainers.image.source="https://github.com/therxtvxk007/git-workshop" \
      dev.pramaan.uv-lock-sha256="${UV_LOCK_SHA256}"

USER pramaan
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS --noproxy '*' http://localhost:8000/health || exit 1

CMD ["python", "-m", "uvicorn", "pramaan_x.api:app", "--host", "0.0.0.0", "--port", "8000"]
