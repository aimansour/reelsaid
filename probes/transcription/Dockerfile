FROM node:22-bookworm-slim AS node
FROM python:3.12-slim-bookworm
WORKDIR /probe
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg
RUN pip install --no-cache-dir curl_cffi==0.17.0 apify==4.2.1 webrtcvad-wheels
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY reelsaid/ reelsaid/
COPY instagram.py media_probe.py adapter_probe.py ./
CMD ["python", "media_probe.py"]
