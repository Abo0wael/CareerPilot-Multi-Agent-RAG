# CareerPilot API image for a Hugging Face Space (Docker SDK, free CPU tier).
#
# Built from the folder staged by scripts/deploy_space.py, which contains this file,
# requirements-server.txt, src/, index/careerpilot.db (WAL checkpointed) and .llm_cache/.
# The database and cache are not in git; they reach the Space only through that script.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    INDEX_PATH=/app/index/careerpilot.db \
    LLM_CACHE_DIR=/app/.llm_cache

# Spaces run the container as UID 1000. index/ and .llm_cache/ must be writable by it:
# SQLite WAL creates -wal/-shm next to the database, and GroqClient creates/writes the cache.
RUN useradd --create-home --uid 1000 user \
    && mkdir -p /app/index /app/.llm_cache \
    && chown -R user:user /app
WORKDIR /app

COPY requirements-server.txt .
RUN pip install --no-cache-dir -r requirements-server.txt

COPY --chown=user src ./src
COPY --chown=user index/careerpilot.db ./index/careerpilot.db
COPY --chown=user .llm_cache ./.llm_cache

USER user
EXPOSE 7860

# --proxy-headers: behind the Space proxy, request.client becomes the real client IP,
# which the per-IP rate limit (RATE_LIMIT) depends on.
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "7860", "--proxy-headers", "--forwarded-allow-ips", "*"]
