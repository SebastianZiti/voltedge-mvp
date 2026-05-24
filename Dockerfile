FROM python:3.12-slim

WORKDIR /app
ENV SERVICE_ENV=container
ENV LOG_LEVEL=INFO
ENV FLASK_DEBUG=0

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Sikkerhed: opret en ikke-root bruger og kør appen som denne.
# Hvis en angriber bryder ind via appen, har de KUN denne brugers rettigheder
# inde i containeren — ikke root. Det er en "defense in depth"-foranstaltning.
RUN useradd --create-home --shell /bin/bash appuser \
 && chown -R appuser:appuser /app
USER appuser

EXPOSE 5001

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5001/ready', timeout=3)"

CMD ["python", "app.py"]
