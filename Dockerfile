FROM python:3.12-slim

WORKDIR /app
ENV SERVICE_ENV=container
ENV LOG_LEVEL=INFO
ENV FLASK_DEBUG=0

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5001

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5001/ready', timeout=3)"

CMD ["python", "app.py"]
