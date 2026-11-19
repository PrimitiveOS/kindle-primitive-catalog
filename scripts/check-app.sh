#!/bin/sh
# Checks one app's folder the way CI does: app.json against the schema, the icon and screenshots by size and colour mode.
#
#   scripts/check-app.sh apps/<id>
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
APP=${1:?usage: check-app.sh apps/<id>}
python3 - "$ROOT" "$APP" <<'PY'
import json, os, struct, sys
from jsonschema import Draft202012Validator, FormatChecker
root, app = sys.argv[1], sys.argv[2]
folder = app if os.path.isabs(app) else os.path.join(root, app)

def png_info(path):
    with open(path, "rb") as f:
        head = f.read(26)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        raise SystemExit(f"{path}: not a PNG")
    w, h, depth, ctype = struct.unpack(">IIBB", head[16:26])
    return w, h, ctype

schema = json.load(open(os.path.join(root, "schema", "app.schema.json"), encoding="utf-8"))
listing = json.load(open(os.path.join(folder, "app.json"), encoding="utf-8"))
errors = sorted(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(listing), key=lambda e: list(e.path))
if errors:
    for e in errors[:5]:
        print("FAIL app.json", "/".join(str(p) for p in e.path), e.message[:160])
    raise SystemExit(1)
problems = []
w, h, ctype = png_info(os.path.join(folder, listing["icon"]))
if (w, h) != (256, 256):
    problems.append(f"icon is {w}x{h}, must be 256x256")
if ctype not in (0, 4):
    problems.append("icon must be grayscale")
for shot in listing.get("screenshots", []):
    w, h, ctype = png_info(os.path.join(folder, shot))
    if (w, h) != (632, 840):
        problems.append(f"{shot} is {w}x{h}, must be 632x840")
    if ctype not in (0, 4):
        problems.append(f"{shot} must be grayscale")
if problems:
    for p in problems:
        print("FAIL", p)
    raise SystemExit(1)
print(f"ok   {listing['id']}")
PY
