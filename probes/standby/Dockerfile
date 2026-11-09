FROM apify/actor-python:3.12@sha256:5d6bcde0bbc82bb4e2293e09bd7a7e037222e858acddc546a463c5aa51f69e2a
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY probe.py .
CMD ["python", "probe.py"]
