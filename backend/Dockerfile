# Build context: repository root (needs ml/ for the shared netad_ml package).
FROM python:3.11.11-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /srv

# 1) shared ML package (pins numpy/pandas/scikit-learn — must match the version that trained the bundle)
COPY ml/pyproject.toml /srv/ml/pyproject.toml
COPY ml/netad_ml /srv/ml/netad_ml
RUN pip install /srv/ml

# 2) API / worker dependencies
COPY backend/requirements.txt /srv/backend/requirements.txt
RUN pip install -r /srv/backend/requirements.txt

COPY backend/ /srv/backend/
WORKDIR /srv/backend
RUN useradd --system --uid 10001 --home /srv app && chmod +x docker-entrypoint.sh
USER app
EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

# Test image: adds test deps and the mock server so the backend suite runs in a container.
# pgserver (bundled PostgreSQL) refuses to run as root, hence USER app.
FROM runtime AS test
USER root
COPY backend/requirements-dev.txt /srv/backend/requirements-dev.txt
COPY mock_zabbix/requirements.txt /srv/mock_zabbix/requirements.txt
RUN pip install -r /srv/backend/requirements-dev.txt -r /srv/mock_zabbix/requirements.txt
ENV LANG=C.UTF-8 LC_ALL=C.UTF-8
USER app
CMD ["python", "-m", "pytest", "-q"]
