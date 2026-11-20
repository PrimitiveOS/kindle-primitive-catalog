#!/usr/bin/env python3
"""Validate listings and build the catalog's static API."""
import argparse
import hashlib
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, FormatChecker
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
PUBLIC_BASE = "https://primitiveos.github.io/kindle-primitive-catalog/v1"
FIRST_PARTY_REPO = re.compile(r"/(?:PrimitiveOS|DoanNguyenTrong)/kindle-primitive-[a-z0-9-]+/?", re.IGNORECASE)
CATEGORIES = [
    ("reading", "Reading"), ("productivity", "Productivity"), ("internet", "Internet"), ("games", "Games"),
    ("audio", "Music & Audio"), ("creativity", "Drawing & Design"), ("developer", "Developer Tools"),
    ("utilities", "Utilities"), ("system", "System"),
]
HOSTED_LICENCES = {
    "AGPL-3.0", "AGPL-3.0-only", "AGPL-3.0-or-later", "GPL-2.0", "GPL-2.0-only", "GPL-2.0-or-later",
    "GPL-3.0", "GPL-3.0-only", "GPL-3.0-or-later", "LGPL-2.1", "LGPL-2.1-only", "LGPL-2.1-or-later",
    "LGPL-3.0", "LGPL-3.0-only", "LGPL-3.0-or-later", "MPL-2.0", "MIT", "BSD-2-Clause", "BSD-3-Clause",
    "Apache-2.0", "ISC", "Unlicense",
}
APP_ID = re.compile(r"[a-z0-9][a-z0-9-]{1,39}")
RESERVED_DIRS = {"documents", "extensions", "system", "fonts", "screensaver", "koreader"}


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def validate(path, data, validator):
    errors = sorted(validator.iter_errors(data), key=lambda e: list(map(str, e.path)))
    if errors:
        lines = [f"{path}: " + "/".join(map(str, e.path)) + ": " + e.message[:160] for e in errors[:5]]
        raise ValueError("\n".join(lines))


def version_key(version):
    core, _, revision = version.partition("-p")
    parts = tuple(map(int, core.split(".")))
    return parts + (0,) * (3 - len(parts)) + (int(revision) if revision else 0,)


def check_png(path, size, max_bytes):
    if path.stat().st_size > max_bytes:
        raise ValueError(f"{path}: exceeds {max_bytes} bytes")
    with Image.open(path, formats=["PNG"]) as image:
        if image.size != size or image.mode not in ("1", "L", "LA", "I;16", "I"):
            raise ValueError(f"{path}: expected a {size[0]}x{size[1]} grayscale PNG")
        image.verify()


def check_listing(folder, validator):
    path = folder / "app.json"
    if path.stat().st_size > 50 * 1024:
        raise ValueError(f"{path}: exceeds 50 KiB")
    listing = load(path)
    validate(path, listing, validator)
    app_id = listing["id"]
    if app_id != folder.name:
        raise ValueError(f"{path}: id must match its folder")
    if listing["source"] != "link" and listing.get("dir", app_id) in RESERVED_DIRS:
        raise ValueError(f"{path}: app installations cannot use a reserved folder")
    if listing["source"] == "hosted":
        repo = urlsplit(listing["repo"])
        primitive = (
            listing["developer"]["name"] == "Primitive AI"
            and repo.scheme == "https" and repo.netloc == "github.com"
            and FIRST_PARTY_REPO.fullmatch(repo.path)
        )
        licence = listing["licence"]
        if licence not in HOSTED_LICENCES and not (primitive and licence == "PolyForm-Noncommercial-1.0.0"):
            raise ValueError(f"{path}: licence is ineligible for a hosted app")
    versions = listing["versions"]
    keys = [version_key(v["version"]) for v in versions]
    if keys != sorted(set(keys), reverse=True):
        raise ValueError(f"{path}: versions must be unique and newest first")
    if listing["source"] != "link" and any(not v["assets"] for v in versions):
        raise ValueError(f"{path}: every package version needs an asset")
    for version in versions:
        if "armel" in version.get("assets", {}) and not version.get("withdrawn"):
            raise ValueError(f"{path}: active listings must use armhf until soft-float device testing is complete")
    check_png(folder / listing["icon"], (256, 256), 20 * 1024)
    screenshots = listing.get("screenshots", [])
    if len(screenshots) != len(set(screenshots)):
        raise ValueError(f"{path}: screenshot paths must be unique")
    for shot in screenshots:
        check_png(folder / shot, (632, 840), 128 * 1024)
    return listing


def card(folder, listing, base):
    app_id = listing["id"]
    versions = listing["versions"]
    live = [v for v in versions if not v.get("withdrawn")]
    return {
        "id": app_id,
        "dir": listing.get("dir", app_id),
        "name": listing["name"],
        "subtitle": listing["subtitle"],
        "categories": listing["categories"],
        "icon": f"{base}/icons/{app_id}.png",
        "source": listing["source"],
        "latest_version": live[0]["version"] if live else None,
        "arch": sorted({arch for v in live for arch in v.get("assets", {})}),
        "updated_at": max(v["date"] for v in versions),
        "listing": f"{base}/apps/{app_id}.json",
        "revision": app_revision(folder, listing),
    }


def app_revision(folder, listing):
    # The Kindle caches the listing, icon, and first two screenshots in this order.
    digest = hashlib.sha256()
    for path in ["app.json", listing["icon"], *listing.get("screenshots", [])[:2]]:
        payload = (folder / path).read_bytes()
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def collections(path, published_ids):
    if path.stat().st_size > 10 * 1024:
        raise ValueError(f"{path}: exceeds 10 KiB")
    data = load(path)
    if not isinstance(data, dict) or data.keys() != {"schema", "collections"} or data["schema"] != 1:
        raise ValueError(f"{path}: expected a schema 1 collections document")
    seen = set()
    if not isinstance(data["collections"], list):
        raise ValueError(f"{path}: collections must be a list")
    for collection in data["collections"]:
        if not isinstance(collection, dict) or collection.keys() != {"id", "title", "description", "apps"}:
            raise ValueError(f"{path}: each collection needs id, title, description and apps")
        ident = collection["id"]
        apps = collection["apps"]
        if not isinstance(ident, str) or not APP_ID.fullmatch(ident) or ident in seen:
            raise ValueError(f"{path}: collection ids must be unique and use lower-case letters, digits or hyphens")
        seen.add(ident)
        for field, maximum in (("title", 40), ("description", 120)):
            text = collection[field]
            if not isinstance(text, str) or not text.strip() or len(text) > maximum:
                raise ValueError(f"{path}: collection {field} must contain 1 to {maximum} characters")
        if (not isinstance(apps, list) or not apps or not all(isinstance(app, str) for app in apps)
                or len(apps) != len(set(apps)) or not set(apps) <= published_ids):
            raise ValueError(f"{path}: {ident} must reference unique published apps")
    return data


def validate_download_snapshot(path, snapshot, validator):
    validate(path, snapshot, validator)
    # JSON Schema accepts an integer-valued float. The Kindle expects an integer token.
    if any(type(count) is not int for count in snapshot["by_app"].values()):
        raise ValueError(f"{path}: download counts must use integer tokens")


def download_snapshot(report_path, previous_index, hosted_ids, validator):
    fresh = None
    if report_path and report_path.is_file():
        try:
            report = load(report_path)
            if report["schema"] != 1 or report["source"] != "github_release_asset_download_count":
                raise ValueError("unsupported download report")
            rows = {row["id"]: row["downloads"] for row in report["apps"] if row["id"] in hosted_ids}
            counted = {app_id: count for app_id, count in rows.items() if count is not None}
            if counted:
                snapshot = {"as_of": report["generated_at"], "by_app": counted}
                validate_download_snapshot(report_path, snapshot, validator)
                fresh = snapshot
                if len(counted) == len(rows):
                    return fresh
        except (KeyError, OSError, TypeError, ValueError) as error:
            print(f"unable to use download report: {error}", file=sys.stderr)

    if previous_index and previous_index.is_file():
        try:
            previous = load(previous_index).get("downloads")
            if previous is not None:
                validate_download_snapshot(previous_index, previous, validator)
                by_app = {app_id: count for app_id, count in previous["by_app"].items() if app_id in hosted_ids}
                if by_app:
                    return {"as_of": previous["as_of"], "by_app": by_app}
        except (AttributeError, KeyError, OSError, TypeError, ValueError) as error:
            print(f"unable to use previous download counts: {error}", file=sys.stderr)

    return fresh


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "site" / "v1")
    parser.add_argument("--now", help="generated_at time (default: now, UTC)")
    parser.add_argument("--base-url", default=PUBLIC_BASE, help="catalog URL written into each card")
    parser.add_argument("--check-app", type=Path, help="validate one app folder without building the site")
    parser.add_argument("--download-counts", type=Path, help="JSON snapshot from download-counts.py")
    parser.add_argument("--previous-index", type=Path, help="published index used if download counts are incomplete")
    args = parser.parse_args()
    formats = FormatChecker()
    validator = Draft202012Validator(load(ROOT / "schema" / "app.schema.json"), format_checker=formats)
    try:
        if args.check_app:
            folder = args.check_app
            if not folder.is_dir() and not folder.is_absolute():
                folder = ROOT / folder
            print(f"ok   {check_listing(folder, validator)['id']}")
            return

        apps = ROOT / "apps"
        sources = [(folder, check_listing(folder, validator)) for folder in sorted(apps.iterdir())
                   if folder.is_dir()]
        ids = {listing["id"] for _, listing in sources}
        dirs = {listing.get("dir", listing["id"]) for _, listing in sources}
        if len(dirs) != len(sources):
            raise ValueError("two listings use the same dir")
        selected = collections(ROOT / "collections.json", ids)
        index = {
            "schema": 1,
            "generated_at": args.now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "categories": [{"id": slug, "name": name} for slug, name in CATEGORIES],
            "apps": [card(folder, listing, args.base_url.rstrip("/")) for folder, listing in sources],
        }
        out = args.out
        index_schema = load(ROOT / "schema" / "index.schema.json")
        index_validator = Draft202012Validator(index_schema, format_checker=formats)
        hosted_ids = {listing["id"] for _, listing in sources if listing["source"] == "hosted"}
        download_validator = index_validator.evolve(schema=index_schema["properties"]["downloads"])
        snapshot = download_snapshot(args.download_counts, args.previous_index, hosted_ids, download_validator)
        if snapshot is not None:
            index["downloads"] = snapshot
        validate(out / "index.json", index, index_validator)
        expected = {"apps", "icons", "shots", "index.json", "collections.json"}
        if out.is_dir():
            if out.is_symlink() or any(path.name not in expected for path in out.iterdir()):
                raise ValueError(f"{out}: output directory contains files outside the catalog layout")
            shutil.rmtree(out)
        for name in ("apps", "icons", "shots"):
            (out / name).mkdir(parents=True)
        for folder, listing in sources:
            app_id = listing["id"]
            shutil.copyfile(folder / "app.json", out / "apps" / f"{app_id}.json")
            shutil.copyfile(folder / listing["icon"], out / "icons" / f"{app_id}.png")
            for i, shot in enumerate(listing.get("screenshots", [])):
                shutil.copyfile(folder / shot, out / "shots" / f"{app_id}-{i}.png")
        dump(out / "index.json", index)
        dump(out / "collections.json", selected)
        print(f"wrote {len(sources)} apps and {len(selected['collections'])} collections to {out}")
    except (OSError, ValueError) as error:
        raise SystemExit(str(error)) from None


if __name__ == "__main__":
    main()
