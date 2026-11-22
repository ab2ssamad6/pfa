#!/usr/bin/env bash
# Deploy a registered model version: MLflow registry -> artifacts/models/ (verified, sha256) -> DVC remote.
#   ./scripts/promote.sh             the newest trained version (alias "candidate")
#   ./scripts/promote.sh 3           registry version 3 (also how you roll back)
#   ./scripts/promote.sh production  re-export the current production version
source "$(dirname "$0")/_common.sh"
require_docker

REF="${1:-candidate}"
mlops_up
ml python -m netad_ml.registry promote "$REF"
info "versioning artifacts/models with DVC"
ml dvc add artifacts/models
ml dvc push artifacts/models.dvc
ml python -m netad_ml.registry list
info "promoted '$REF' to production. Next:"
info "  git add artifacts/models.dvc dvc.lock && git commit -m 'model: promote <version>'"
info "  ./scripts/restart.sh api worker      # the backend loads the new bundle on start"
