FROM python:3.12-slim

# OCI-labels - GHCR laeser disse for at vise beskrivelse, repo-link og
# licens paa pakke-siden. 'image.source' kobler pakken til repoet
# (vises som "from voltedge-mvp" paa GitHub), 'image.description' vises
# under pakkenavnet i UI'en.
LABEL org.opencontainers.image.source="https://github.com/SebastianZiti/voltedge-mvp"
LABEL org.opencontainers.image.description="VoltEdge MVP - Smart Charging Operations Intelligence (Flask + SQLite + sklearn + Prometheus/Grafana). Eksamens-MVP for 6. semester."
LABEL org.opencontainers.image.licenses="MIT"

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV SERVICE_ENV=production
ENV LOG_LEVEL=INFO
ENV FLASK_DEBUG=0
ENV DB_PATH=/data/voltedge.db

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Sikkerhed: opret en ikke-root bruger og kør appen som denne.
# Hvis en angriber bryder ind via appen, har de KUN denne brugers rettigheder
# inde i containeren — ikke root. Det er en "defense in depth"-foranstaltning.
RUN useradd --create-home --shell /bin/bash appuser \
 && mkdir -p /data \
 && chown -R appuser:appuser /app /data
USER appuser

EXPOSE 5001

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5001/ready', timeout=3)"

CMD ["python", "app.py"]
