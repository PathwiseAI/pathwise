FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/
COPY sample_repo/ ./sample_repo/
COPY scripts/ ./scripts/

# Environment defaults
ENV FALKORDB_HOST=falkordb \
    FALKORDB_PORT=6379 \
    PATHWISE_HOST=0.0.0.0 \
    PATHWISE_PORT=8000 \
    ALLOWED_ROOT=/app \
    PYTHONPATH=/app

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["python", "-m", "app.main"]
