# MLflow tracking server + model registry. Metadata in PostgreSQL (mlflow-db), artifacts in the S3 store (SeaweedFS),
# proxied through the server (--serve-artifacts) so clients never need S3 credentials.
# Every package is pinned in requirements.lock: unpinned transitive deps (e.g. SQLAlchemy) break MLflow 2.19.
FROM python:3.11.11-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY requirements.lock /tmp/requirements.lock
RUN pip install --no-deps -r /tmp/requirements.lock && pip check
EXPOSE 5000
