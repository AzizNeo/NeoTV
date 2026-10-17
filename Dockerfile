# syntax=docker/dockerfile:1.7
# Backend image: API (gunicorn), Celery workers and beat all run this image —
# one artefact, different commands (see docker-compose.yml).
FROM python:3.12-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

FROM base AS deps
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*
COPY requirements.lock ./
# Hash-locked install: the image gets exactly the versions CI tested (tools/lock_deps).
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --require-hashes --only-binary=:all: -r requirements.lock

FROM base AS runtime
# ffmpeg: live transcoding (worker-transcode); tini: proper PID 1 signal handling.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg tini \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system neotv && useradd --system --gid neotv --home /srv/neotv neotv
COPY --from=deps /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH \
    ENV=prod \
    HLS_OUTPUT_ROOT=/var/lib/neotv/hls
WORKDIR /srv/neotv
COPY --chown=neotv:neotv app ./app
COPY --chown=neotv:neotv migrations ./migrations
COPY --chown=neotv:neotv tools ./tools
COPY --chown=neotv:neotv run.py celery_worker.py gunicorn.conf.py ./
# state/: small writable data of single-host setups (the demo's generated secrets, console mail).
RUN mkdir -p /var/lib/neotv/hls /var/lib/neotv/state instance && chown -R neotv:neotv /var/lib/neotv instance
USER neotv
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=4).status == 200 else 1)"
ENTRYPOINT ["tini", "--"]
CMD ["gunicorn", "app.wsgi:app", "--worker-class", "gthread", "--workers", "2", "--threads", "8", \
     "--bind", "0.0.0.0:8000", "--forwarded-allow-ips", "*", "--access-logfile", "-", "--graceful-timeout", "30"]
