FROM apify/actor-python:3.12@sha256:5d6bcde0bbc82bb4e2293e09bd7a7e037222e858acddc546a463c5aa51f69e2a AS media-tools

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential nasm pkg-config xz-utils \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /ffmpeg
RUN curl --fail --silent --show-error --location --retry 2 \
        https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz -o source.tar.xz \
    && echo '8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e  source.tar.xz' | sha256sum --check \
    && tar -xf source.tar.xz --strip-components=1 \
    && ./configure --disable-autodetect --disable-debug --disable-doc --disable-network \
        --disable-programs --enable-ffmpeg --enable-ffprobe --disable-encoders \
        --enable-encoder=flac,pcm_s16le --disable-muxers --enable-muxer=flac,pcm_s16le \
        --disable-devices --enable-small \
    && make -j4 ffmpeg ffprobe \
    && strip ffmpeg ffprobe \
    && install -D -m 0755 ffmpeg /native/bin/ffmpeg \
    && install -D -m 0755 ffprobe /native/bin/ffprobe \
    && install -D -m 0644 COPYING.LGPLv2.1 /native/share/licenses/ffmpeg/COPYING.LGPLv2.1

FROM ghcr.io/astral-sh/uv:0.12.23@sha256:61d393e44e249f2e4b526b6c7ddcecce245946826e608e11c93ad4f5bba55b21 AS uv-tool
FROM apify/actor-python:3.12@sha256:5d6bcde0bbc82bb4e2293e09bd7a7e037222e858acddc546a463c5aa51f69e2a

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app/src

COPY --from=media-tools /native/ /usr/local/
COPY pyproject.toml uv.lock ./
RUN --mount=from=uv-tool,source=/uv,target=/usr/local/bin/uv \
    uv sync --locked --no-dev --no-cache --compile-bytecode \
    && python -m compileall -q -x '/site-packages/' /usr/local/lib/python3.12
COPY scripts/install-quality-models ./scripts/
RUN bash ./scripts/install-quality-models
COPY src/ ./src/
RUN python -m compileall -q ./src

CMD ["python", "-m", "reelsaid"]
