#!/usr/bin/env python3
"""Build the catalog's static API from apps/*/app.json.

    python3 scripts/build-index.py [--out site/v1] [--now 2026-11-19T10:00:00Z]

Writes index.json (the cards and categories), collections.json (if collections.json exists at the top), and apps/<id>.json
(each full listing), icons/<id>.png and shots/<id>-<n>.png, copied after the schema check. Refuses to write anything when a listing fails its schema.
"""
import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone

from jsonschema import Draft202012Validator, FormatChecker

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CATEGORIES = [
    ("reading", "Reading"), ("productivity", "Productivity"), ("internet", "Internet"), ("games", "Games"),
    ("audio", "Music & Audio"), ("creativity", "Drawing & Design"), ("developer", "Developer Tools"),
    ("utilities", "Utilities"), ("system", "System"),
]


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def check_listing(path, validator):
    """Returns the listing, or raises SystemExit with the errors."""
    data = load(path)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    if errors:
        lines = [f"{path}: " + "/".join(str(p) for p in e.path) + ": " + e.message[:160] for e in errors[:5]]
        raise SystemExit("\n".join(lines))
    return data


def card(listing, app_dir):
    versions = listing["versions"]
    live = [v for v in versions if not v.get("withdrawn")]
    latest = live[0]["version"] if live else None
    arch = sorted({a for v in live for a in v.get("assets", {})})
    base = f"https://doannguyentrong.github.io/kindle-primitive-catalog/v1"
    return {
        "id": listing["id"],
        "dir": listing.get("dir", listing["id"]),
        "name": listing["name"],
        "subtitle": listing["subtitle"],
        "categories": listing["categories"],
        "icon": f"{base}/icons/{listing['id']}.png",
        "source": listing["source"],
        "latest_version": latest,
        "arch": arch,
        "updated_at": max(v["date"] for v in versions),
        "listing": f"{base}/apps/{listing['id']}.json",
    }


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "site", "v1"))
    ap.add_argument("--now", default=None, help="the generated_at time (default: now, UTC)")
    args = ap.parse_args(argv)

    with open(os.path.join(ROOT, "schema", "app.schema.json"), encoding="utf-8") as f:
        validator = Draft202012Validator(json.load(f), format_checker=FormatChecker())

    listings = []
    apps_dir = os.path.join(ROOT, "apps")
    for name in sorted(os.listdir(apps_dir)):
        path = os.path.join(apps_dir, name, "app.json")
        if os.path.isfile(path):
            listings.append((name, check_listing(path, validator), os.path.join(apps_dir, name)))

    ids = [l["id"] for _, l, _ in listings]
    if len(ids) != len(set(ids)):
        raise SystemExit("two listings have the same id")
    dirs = [l.get("dir", l["id"]) for _, l, _ in listings]
    if len(dirs) != len(set(dirs)):
        raise SystemExit("two listings use the same dir")

    out = args.out
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(os.path.join(out, "apps"))
    generated = args.now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    cards = []
    os.makedirs(os.path.join(out, "icons"))
    os.makedirs(os.path.join(out, "shots"))
    for folder, listing, src in listings:
        app_id = listing["id"]
        shutil.copyfile(os.path.join(src, "app.json"), os.path.join(out, "apps", f"{app_id}.json"))
        shutil.copyfile(os.path.join(src, listing["icon"]), os.path.join(out, "icons", f"{app_id}.png"))
        # Screenshots keep their order: shots/<id>-<n>.png, n from 0, as the device names them.
        for n, shot in enumerate(listing.get("screenshots", [])):
            shutil.copyfile(os.path.join(src, shot), os.path.join(out, "shots", f"{app_id}-{n}.png"))
        cards.append(card(listing, src))
    index = {
        "schema": 1,
        "generated_at": generated,
        "categories": [{"id": i, "name": n} for i, n in CATEGORIES],
        "apps": cards,
    }
    with open(os.path.join(out, "index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)
        f.write("\n")
    collections = os.path.join(ROOT, "collections.json")
    if os.path.isfile(collections):
        shutil.copyfile(collections, os.path.join(out, "collections.json"))
    print(f"wrote {len(cards)} apps to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
