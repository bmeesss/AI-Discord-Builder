FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Keep runtime files writable without running the bot as root.
# /app/data holds the local JSON storage (rollback history, conversations).
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/logs /app/data \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; port = os.getenv('WEB_PORT') or os.getenv('PORT') or 8080; urllib.request.urlopen(f'http://127.0.0.1:{port}/healthz', timeout=3)"

CMD ["python", "main.py"]
