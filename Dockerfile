# =============================================================================
# Legafy AI — CPU-only, multi-stage image (Akridion Labs)
#
# Stage 1 (builder) compiles wheels for every pinned dependency so the
# runtime stage never needs a compiler toolchain. Stage 2 (runtime) installs
# those wheels only, drops root, and runs uvicorn as an unprivileged user.
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1: builder — build-essential lives ONLY here.
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY requirements.txt .

# Pre-build wheels for every runtime dependency so stage 2 is a pure
# `pip install --no-index` with no compilation.
RUN pip wheel --wheel-dir /wheels -r requirements.txt

# ---------------------------------------------------------------------------
# Stage 2: runtime — no compilers, no build-essential, non-root user.
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

LABEL org.opencontainers.image.title="Legafy AI" \
      org.opencontainers.image.vendor="Akridion Labs LLP" \
      org.opencontainers.image.source="https://github.com/akridion-labs/legafy-ai" \
      org.opencontainers.image.licenses="Apache-2.0"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    LEGAFY_WORKERS=2

# Non-root runtime user (fixed uid so bind-mounted volumes have stable
# ownership across rebuilds).
RUN groupadd --gid 10001 legafy \
    && useradd --uid 10001 --gid legafy --create-home --shell /usr/sbin/nologin legafy

WORKDIR /workspace

# Install the pre-built wheels only — no build-essential, no network compile.
COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels requirements.txt

# Application code + runtime data. Order chosen to keep the cache warm when
# only app/ changes during iteration.
COPY app/ app/
COPY data/ data/
COPY pyproject.toml .

# Runtime-only output directory (audit vault, generated drafts). Contents are
# never baked into the image — this just guarantees the mount point exists
# with correct ownership before the volume is layered over it.
RUN mkdir -p /workspace/generated && chown -R legafy:legafy /workspace

USER legafy

EXPOSE 8000

# Prefer the python stdlib over adding a curl dependency to the runtime image.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status == 200 else 1)"]

ENTRYPOINT ["/bin/sh", "-c"]
CMD ["exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${LEGAFY_WORKERS:-2}"]
