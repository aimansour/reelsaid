FROM node:22-bookworm-slim AS node
FROM python:3.12-slim-bookworm
WORKDIR /probe
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir curl_cffi==0.17.0 apify==4.2.1 webrtcvad-wheels \
    numpy==2.5.4 onnxruntime==1.31.1 ai-edge-litert==2.3.0
COPY install-quality-models .
ENV REELSAID_MODEL_DIR=/probe/.quality-models
RUN bash install-quality-models "$REELSAID_MODEL_DIR"
RUN curl -fsSL --retry 2 'https://upload.wikimedia.org/wikipedia/commons/4/42/Goldberg_Variations_01_Aria.ogg' -o /tmp/piano.ogg \
    && ffmpeg -nostdin -v error -ss 4 -i /tmp/piano.ogg -t 12 -ar 16000 -ac 1 piano.flac \
    && rm /tmp/piano.ogg
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY reelsaid/ reelsaid/
COPY instagram.py media_probe.py adapter_probe.py quality_probe.py ./
CMD ["python", "media_probe.py"]
