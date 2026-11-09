FROM apify/actor-python:3.12@sha256:5d6bcde0bbc82bb4e2293e09bd7a7e037222e858acddc546a463c5aa51f69e2a

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app/src

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl ffmpeg \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-cache --compile-bytecode \
    && python -m compileall -q -x '/site-packages/' /usr/local/lib/python3.12
COPY scripts/install-quality-models ./scripts/
RUN bash ./scripts/install-quality-models
COPY src/ ./src/
RUN python -m compileall -q ./src

CMD ["python", "-m", "reelsaid"]
