# Offline ML / MLOps image: training pipeline (dvc repro), MLflow client, DVC (scripts/train.sh, promote.sh, dvc.sh).
# Not part of the running stack. The repo is mounted at /srv/project and PYTHONPATH points at its ml/ folder,
# so the code DVC hashes is the code that runs; the copy installed here only provides the dependencies.
FROM python:3.11.11-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml /srv/ml/pyproject.toml
COPY netad_ml /srv/ml/netad_ml
COPY tests /srv/ml/tests
RUN pip install "/srv/ml[train,dev,mlops]"
WORKDIR /srv/project
