#!/bin/sh
# Build a fixture site with the same validation that CI uses for publication.
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
python3 -I scripts/test-download-counts.py
python3 -I scripts/test-check-assets.py
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
python3 -I scripts/build-index.py --out "$TMP/v1" --now 2026-11-19T10:00:00Z \
    --base-url https://catalog.example/v1
python3 -I - "$TMP/v1" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

site = Path(sys.argv[1])
index = json.loads((site / "index.json").read_text())
collections = json.loads((site / "collections.json").read_text())
for card in index["apps"]:
    app_id = card["id"]
    listing_path = site / "apps" / f"{app_id}.json"
    listing = json.loads(listing_path.read_bytes())
    assert app_id == listing["id"]
    assert card["listing"] == f"https://catalog.example/v1/apps/{app_id}.json"
    icon = site / "icons" / f"{app_id}.png"
    shots = [site / "shots" / f"{app_id}-{number}.png"
             for number in range(len(listing.get("screenshots", [])))]
    assert all(path.is_file() for path in shots)
    revision = hashlib.sha256()
    for path in [listing_path, icon, *shots[:2]]:
        payload = path.read_bytes()
        revision.update(len(payload).to_bytes(8, "big"))
        revision.update(payload)
    assert card["revision"] == revision.hexdigest(), app_id
assert collections == json.loads(Path("collections.json").read_text())
print("ok   static catalog API")
PY
python3 -I - "$TMP" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
report = {
    "schema": 1, "source": "github_release_asset_download_count", "generated_at": "2026-11-19T09:00:00Z",
    "apps": [
        {"id": "primitive-notes", "downloads": 0},
        {"id": "primitive-snake", "downloads": 13},
        {"id": "old-app", "downloads": 18},
        {"id": "koreader", "downloads": 25},
    ],
}
(root / "report.json").write_text(json.dumps(report))
report["apps"][0]["downloads"] = None
report["apps"][1]["downloads"] = 21
report["generated_at"] = "2026-11-19T09:30:00Z"
(root / "partial.json").write_text(json.dumps(report))
report["apps"][1]["downloads"] = -1
(root / "invalid.json").write_text(json.dumps(report))
PY
build_counts() {
    python3 -I scripts/build-index.py --base-url https://catalog.example/v1 \
        --now 2026-11-19T10:00:00Z --out "$TMP/$1" --download-counts "$TMP/$2.json" \
        --previous-index "$TMP/counted/index.json"
}
build_counts counted report
build_counts fallback partial
build_counts invalid invalid
python3 -I scripts/build-index.py --out "$TMP/partial" --download-counts "$TMP/partial.json"
python3 -I - "$TMP" <<'PY'
import json
import sys
from pathlib import Path

def index(name):
    return json.loads((Path(sys.argv[1]) / name / "index.json").read_text())

baseline, counted, fallback, invalid, partial = map(index, ("v1", "counted", "fallback", "invalid", "partial"))
assert "downloads" not in baseline
assert counted["downloads"] == {
    "as_of": "2026-11-19T09:00:00Z",
    "by_app": {"primitive-notes": 0, "primitive-snake": 13},
}
assert baseline["apps"] == counted["apps"] == fallback["apps"] == invalid["apps"]
assert fallback["downloads"] == invalid["downloads"] == counted["downloads"]
assert partial["downloads"] == {"as_of": "2026-11-19T09:30:00Z", "by_app": {"primitive-snake": 21}}
for card in partial["apps"]:
    base = "https://primitiveos.github.io/kindle-primitive-catalog/v1"
    assert card["listing"] == f'{base}/apps/{card["id"]}.json'
    assert card["icon"] == f'{base}/icons/{card["id"]}.png'
print("ok   optional download counts and previous snapshot fallback")
PY
