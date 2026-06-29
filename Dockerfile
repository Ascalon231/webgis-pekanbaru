FROM ghcr.io/osgeo/gdal:ubuntu-small-latest

RUN apt-get update && apt-get install -y python3-pip python3-venv && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN python3 -m venv /venv && \
    /venv/bin/pip install --no-cache-dir -r requirements.txt

COPY . .
ENV PATH="/venv/bin:$PATH"
EXPOSE 8080
CMD ["/venv/bin/gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--worker-class", "gevent", "server:app"]
