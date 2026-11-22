#!/usr/bin/env bash
# Package the runtime ML artifacts (model bundle + replay pool) for a GitHub Release, so a fresh clone can run
# ./scripts/start.sh without DVC credentials. Writes dist/netad-artifacts-<tag>.tar.gz and artifacts/release.lock
# (download URL + sha256, committed to git and verified by start.sh).
#
#   ./scripts/package_artifacts.sh [tag] [owner/repo]     default tag v1.0, repo from the "origin" git remote
#
# Then: commit artifacts/release.lock, push, and publish the tarball:
#   gh release create <tag> dist/netad-artifacts-<tag>.tar.gz --title "NetAD <tag>" --notes "Model + replay pool"
source "$(dirname "$0")/_common.sh"

TAG="${1:-v1.0}"
REPO="${2:-}"
if [[ -z "$REPO" ]]; then
  url="$(git remote get-url origin 2>/dev/null || true)"
  [[ "$url" == *github.com* ]] && REPO="$(sed -E 's#.*github\.com[:/]##; s#\.git$##' <<<"$url")"
fi
[[ -n "$REPO" ]] || fail "no GitHub repo: pass it as ./scripts/package_artifacts.sh $TAG <owner>/<repo>"

ls artifacts/models/*/metadata.json >/dev/null 2>&1 || fail "no model bundle in artifacts/models/"
[[ -f artifacts/replay/replay_pool.parquet ]] || fail "no replay pool in artifacts/replay/"

NAME="netad-artifacts-${TAG}.tar.gz"
mkdir -p dist
tar -czf "dist/$NAME" artifacts/models artifacts/replay
SHA="$(sha256_of "dist/$NAME")"
cat > artifacts/release.lock <<LOCK
# Written by scripts/package_artifacts.sh. start.sh downloads this tarball when artifacts/ is empty and no DVC
# credentials are configured, and refuses it unless the sha256 matches.
ARTIFACTS_URL=https://github.com/${REPO}/releases/download/${TAG}/${NAME}
ARTIFACTS_SHA256=${SHA}
LOCK
info "built dist/$NAME ($(du -h "dist/$NAME" | cut -f1), sha256 $SHA)"
info "next:"
info "  git add artifacts/release.lock && git commit -m 'release: artifacts $TAG' && git push"
info "  gh release create $TAG dist/$NAME --title 'NetAD $TAG' --notes 'Model bundle + replay pool'"
