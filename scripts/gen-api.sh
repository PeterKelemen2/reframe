#!/usr/bin/env bash
# Regenerate frontend/src/api/schema.d.ts from the server's OpenAPI document.
#   scripts/gen-api.sh          write the file
#   scripts/gen-api.sh --check  write nothing; exit 1 with a diff when the file is stale
# Needs `uv sync` and `npm ci` (in frontend/) first.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
target="$root/frontend/src/api/schema.d.ts"
check=false
case "${1:-}" in
  "") ;;
  --check) check=true ;;
  *) echo "usage: $0 [--check]" >&2; exit 2 ;;
esac

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

uv run --project "$root" python "$root/scripts/export-openapi.py" "$work/openapi.json"
# openapi-typescript and its TypeScript come from frontend/node_modules (pinned there).
(cd "$root/frontend" && npm exec --offline --silent -- openapi-typescript "$work/openapi.json" \
  --output "$work/schema.d.ts" >/dev/null)

if $check; then
  if ! diff -u --label "$target (current)" --label "$target (generated)" \
    "$target" "$work/schema.d.ts"; then
    echo "frontend/src/api/schema.d.ts is stale: run scripts/gen-api.sh and commit it" >&2
    exit 1
  fi
  echo "frontend/src/api/schema.d.ts is up to date"
else
  mkdir -p "$(dirname "$target")"
  cp "$work/schema.d.ts" "$target"
  echo "wrote $target"
fi
