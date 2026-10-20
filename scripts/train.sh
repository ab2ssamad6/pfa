#!/usr/bin/env bash
# Offline ML pipeline in Docker: CSV -> Parquet -> dedup/split -> train/evaluate -> bundle -> replay pool.
# Needs data/Dataset*.csv and roughly 8 GB RAM for Docker. Steps are skipped when their output exists;
# pass --force to redo everything.
source "$(dirname "$0")/_common.sh"
require_docker

ls data/*.csv >/dev/null 2>&1 || fail "no CSV datasets found in data/"
FORCE="${1:-}"
mkdir -p ml/work ml/reports artifacts
run() { compose --profile train run --rm trainer "$@"; }

if [[ "$FORCE" == "--force" || ! -f ml/work/parquet/conversion_report.json ]]; then
  info "1/4 converting CSV to Parquet"; run python -m netad_ml.convert --workers 2
fi
if [[ "$FORCE" == "--force" || ! -f ml/work/splits/prepare_report.json ]]; then
  info "2/4 de-duplicating and splitting"; run python -m netad_ml.prepare
fi
if [[ "$FORCE" == "--force" ]] || ! ls artifacts/models/*/metadata.json >/dev/null 2>&1; then
  info "3/4 training candidates (30-40 min)"; run python -m netad_ml.train ${FORCE:+--fresh}
fi
info "4/4 building the replay pool from the test split"; run python -m netad_ml.replay_pool
info "done — results in ml/reports/experiments.json, bundle in artifacts/models/"
