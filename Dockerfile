FROM ghcr.io/astral-sh/uv:0.13.7 AS uv
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    BOB_MODE=full \
    BOB_DATA_DIR=/data \
    BOB_HOST=0.0.0.0 \
    BOB_PORT=8000

WORKDIR /app
COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY bob ./bob
COPY web ./web
COPY LICENSE ./
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin bob \
    && mkdir -p /data/artifacts \
    && chown -R bob:bob /app /data

ENV PATH="/app/.venv/bin:$PATH"
USER bob

VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=3)"
CMD ["python", "-m", "bob"]
