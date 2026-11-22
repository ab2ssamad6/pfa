# Offline ML / MLOps image: training pipeline (dvc repro), MLflow client, DVC (scripts/train.sh, promote.sh, dvc.sh).
# Not part of the running stack. The repo is mounted at /srv/project and PYTHONPATH points at its ml/ folder,
# so the code DVC hashes is the code that runs; the copy installed here only provides the dependencies.
FROM python:3.11.11-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
# every package pinned (requirements.lock), then the project itself without re-resolving
COPY requirements.lock /tmp/requirements.lock
RUN pip install --no-deps -r /tmp/requirements.lock
COPY pyproject.toml /srv/ml/pyproject.toml
COPY netad_ml /srv/ml/netad_ml
COPY tests /srv/ml/tests
RUN pip install --no-deps "/srv/ml" && pip check
# /etc/passwd writable so the entrypoint can add the runtime (host) uid
COPY entrypoint.sh /usr/local/bin/netad-entrypoint
RUN chmod 755 /usr/local/bin/netad-entrypoint && chmod 666 /etc/passwd
ENV USER=netad LOGNAME=netad
ENTRYPOINT ["/usr/local/bin/netad-entrypoint"]
WORKDIR /srv/project
