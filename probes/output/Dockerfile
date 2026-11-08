FROM python:3.12-slim-bookworm
WORKDIR /probe
RUN pip install --no-cache-dir apify==4.2.1 curl-cffi==0.17.0 numpy==2.5.4 pycountry==26.2.16 regex==2026.11.7
COPY reelsaid/ reelsaid/
COPY probe.py .
CMD ["python", "probe.py"]
