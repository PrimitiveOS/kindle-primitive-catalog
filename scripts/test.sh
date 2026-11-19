#!/bin/sh
# Build a fixture site with the same validation that CI uses for publication.
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
python3 -I scripts/build-index.py --out "$TMP/v1" --now 2026-11-19T10:00:00Z \
    --base-url https://catalog.example/v1
python3 -I - "$TMP/v1" <<'PY'
import json
import sys
from pathlib import Path

site = Path(sys.argv[1])
index = json.loads((site / "index.json").read_text())
collections = json.loads((site / "collections.json").read_text())
for card in index["apps"]:
    app_id = card["id"]
    listing = json.loads((site / "apps" / f"{app_id}.json").read_text())
    assert app_id == listing["id"]
    assert card["listing"] == f"https://catalog.example/v1/apps/{app_id}.json"
    assert (site / "icons" / f"{app_id}.png").is_file()
    for number in range(len(listing.get("screenshots", []))):
        assert (site / "shots" / f"{app_id}-{number}.png").is_file()
assert collections == json.loads(Path("collections.json").read_text())
print("ok   static catalog API")
PY
