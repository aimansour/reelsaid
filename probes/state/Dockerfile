FROM python:3.12-slim-bookworm
WORKDIR /probe
RUN pip install --no-cache-dir apify==4.2.1
COPY probe.py .
CMD ["python", "probe.py"]
