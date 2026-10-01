# CareerPilot API image for a Hugging Face Space (Docker SDK, free CPU tier).
# The index is not baked in: scripts/start_space.py downloads it from a private
# HF dataset at start-up (HF_TOKEN secret), then starts uvicorn on port 7860.
FROM python:3.11-slim

# Spaces run the container as uid 1000.
RUN useradd --create-home --uid 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_ENV=production \
    PORT=7860
WORKDIR $HOME/app

COPY --chown=user requirements-server.txt .
RUN pip install --no-cache-dir --user -r requirements-server.txt

COPY --chown=user src ./src
COPY --chown=user scripts/start_space.py ./scripts/start_space.py

EXPOSE 7860
CMD ["python", "scripts/start_space.py"]
