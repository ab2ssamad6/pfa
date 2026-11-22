# MLflow tracking server + model registry. Metadata in PostgreSQL (mlflow-db), artifacts in MinIO (S3),
# proxied through the server (--serve-artifacts) so clients never need S3 credentials.
FROM python:3.11.11-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN pip install "mlflow==2.19.0" "psycopg2-binary==2.9.10" "boto3==1.35.90"
EXPOSE 5000
