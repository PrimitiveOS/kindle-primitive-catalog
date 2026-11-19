#!/bin/sh
# What CI runs for the catalog: every listing is checked, the index is built, and the index is checked against its schema.
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
for app in apps/*/; do sh scripts/check-app.sh "$app"; done
python3 -I scripts/build-index.py --out "$(mktemp -d)" >/dev/null
python3 -I scripts/build-index.py --now 2026-11-19T10:00:00Z >/dev/null
python3 -I - <<'PY'
import json
from jsonschema import Draft202012Validator, FormatChecker
errors = list(Draft202012Validator(json.load(open("schema/index.schema.json")), format_checker=FormatChecker())
              .iter_errors(json.load(open("site/v1/index.json"))))
if errors:
    raise SystemExit("index.json: " + errors[0].message)
print("ok   site/v1/index.json")
PY
