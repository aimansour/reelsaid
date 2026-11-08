FROM python:3.12-slim-bookworm
WORKDIR /probe
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir apify==4.2.1 curl-cffi==0.17.0
COPY reelsaid/ reelsaid/
COPY probe.py .
CMD ["python", "probe.py"]
