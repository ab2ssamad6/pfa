FROM python:3.11.11-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /srv/mock_zabbix
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY zabbix_mock ./zabbix_mock
COPY scenarios ./scenarios
RUN useradd --system --uid 10002 app
USER app
EXPOSE 8081
# The replay pool (artifacts/replay) is mounted read-only at /artifacts.
CMD ["uvicorn", "zabbix_mock.main:app", "--host", "0.0.0.0", "--port", "8081"]
