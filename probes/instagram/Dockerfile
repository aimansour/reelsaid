FROM python:3.12-slim-bookworm
WORKDIR /probe
RUN pip install --no-cache-dir curl_cffi==0.17.0 yt-dlp==2026.10.26 instaloader
COPY probe.py .
CMD ["python", "probe.py"]
