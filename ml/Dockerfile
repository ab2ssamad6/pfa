# Offline training image (used by scripts/train.sh; not part of the running stack).
FROM python:3.11.11-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY pyproject.toml /srv/ml/pyproject.toml
COPY netad_ml /srv/ml/netad_ml
COPY tests /srv/ml/tests
RUN pip install "/srv/ml[train,dev]"
WORKDIR /srv/project
