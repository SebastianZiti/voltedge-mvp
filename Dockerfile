FROM python:3.12-slim

LABEL org.opencontainers.image.source="https://github.com/SebastianZiti/voltedge-mvp"
LABEL org.opencontainers.image.description="VoltEdge MVP - Smart Charging Operations Intelligence (Flask + SQLite + sklearn + Prometheus/Grafana)."
LABEL org.opencontainers.image.licenses="MIT"

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV SERVICE_ENV=development
ENV LOG_LEVEL=INFO
ENV FLASK_DEBUG=0
ENV DB_PATH=/data/voltedge.db

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --create-home --shell /bin/bash appuser \
 && mkdir -p /data \
 && chown -R appuser:appuser /app /data
USER appuser

EXPOSE 5001

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5001/ready', timeout=3)"

CMD ["python", "app.py"]
