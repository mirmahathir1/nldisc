# NLDisc backend (Flask). Source is bind-mounted at runtime via docker-compose;
# this image only installs Python dependencies.
FROM python:3.11-slim

# System libs commonly needed by pandas / numpy / sentence-transformers /
# hnswlib wheels.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install deps first for layer caching. Build context is ./backend.
COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

EXPOSE 5000

# app.py's __main__ binds 127.0.0.1 (loopback-only, unreachable through a
# published port), so we launch the module-level `app` via the Flask CLI bound
# to 0.0.0.0. --debug enables the reloader (polling stat-reloader, since
# watchdog isn't installed) for hot reload over the bind mount.
CMD ["flask", "--app", "backend.app", "run", "--host", "0.0.0.0", "--port", "5000", "--debug"]
