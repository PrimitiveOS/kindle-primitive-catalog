#!/bin/sh
# Check a listing and its images using the same rules as the catalog build.
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
APP=${1:?usage: check-app.sh apps/<id>}
python3 -I "$ROOT/scripts/build-index.py" --check-app "$APP"
