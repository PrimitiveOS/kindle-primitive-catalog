#!/usr/bin/env python3
"""Stage Primitive Store listings using downloaded GitHub ARMHF releases."""

import argparse
import hashlib
import json
import re
import runpy
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from datetime import date
from pathlib import Path

from jsonschema import Draft202012Validator
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OWNER = "DoanNguyenTrong"
ARCH = "armhf"
SCREENSHOT_SIZE = (632, 840)
SYSTEM_SCREENSHOTS = {"primitive-browser", "primitive-launcher", "primitive-store"}
CHECKSUM_BYTES = 4096
READ_TIMEOUT = 30
DOWNLOAD_SECONDS = 180


def release_arg(value):
    match = re.fullmatch(r"(primitive-[a-z0-9-]+)=([0-9]+\.[0-9]+\.[0-9]+)", value)
    if not match:
        raise argparse.ArgumentTypeError("expected an app and release such as primitive-notes=0.1.0")
    return match.groups()


def screenshot_arg(value):
    app_id, equals, path = value.partition("=")
    if not equals or not re.fullmatch(r"primitive-[a-z0-9-]+", app_id) or not path:
        raise argparse.ArgumentTypeError("expected an app and PNG path such as primitive-browser=reader.png")
    return app_id, Path(path)


def release_notes(checkout, app_id, version, review, previous):
    path = checkout / ("docs/CHANGELOG.md" if app_id in ("primitive-launcher", "primitive-browser") else "CHANGELOG.md")
    text = path.read_text(encoding="utf-8")
    heading = re.search(rf"^## \[?{re.escape(version)}\]?(?=[ \t]|$).*$", text, re.M)
    lines = []
    if heading:
        section = re.split(r"^## ", text[heading.end():], maxsplit=1, flags=re.M)[0]
        lines = re.findall(r"^- (.+(?:\n  [^\n]+)*)", section, re.M)
    elif review["version"] == version:
        lines = review["notes"].splitlines()
    local_notes = {
        "Initial local build.", "Local build for package and desktop review.",
        "Add desktop simulation and a Store-ready package.",
    }
    notes = "\n".join(" ".join(line.split()) for line in lines[:5] if line.strip() not in local_notes)
    fallback = "Updated Kindle ARMHF package." if previous else "First Primitive Store release."
    return notes[:500].rstrip() or fallback


def released_asset(opener, checks, url, archive_name, destination):
    sidecar_url = url + ".sha256"
    checks["check_url"](sidecar_url)
    with opener.open(sidecar_url, timeout=READ_TIMEOUT) as response:
        sidecar = response.read(CHECKSUM_BYTES + 1)
    fields = sidecar.decode("ascii").split()
    if (len(sidecar) > CHECKSUM_BYTES or len(fields) != 2 or fields[1] != archive_name
            or not re.fullmatch(r"[0-9a-f]{64}", fields[0])):
        raise ValueError(f"{sidecar_url}: invalid release checksum sidecar")

    digest = hashlib.sha256()
    size = 0
    deadline = time.monotonic() + DOWNLOAD_SECONDS
    checks["check_url"](url)
    with opener.open(url, timeout=READ_TIMEOUT) as response:
        while chunk := response.read(64 * 1024):
            size += len(chunk)
            if size > checks["MAX_BYTES"] or time.monotonic() > deadline:
                raise ValueError(f"{url}: download exceeded the catalog's size or time limit")
            digest.update(chunk)
            destination.write(chunk)
    if size == 0 or digest.hexdigest() != fields[0]:
        raise ValueError(f"{url}: downloaded archive disagrees with the published checksum")
    return {"url": url, "sha256": digest.hexdigest(), "size": size}


def read_release_metadata(archive, top, checkout, max_manifest):
    with zipfile.ZipFile(archive) as zipped:
        for filename in ("LICENSE", "LICENSE-DOCS"):
            local = (checkout / filename).read_bytes()
            member = zipped.getinfo(f"{top}/{filename}")
            if member.file_size != len(local) or zipped.read(member) != local:
                raise ValueError(f"{top}: {filename} differs from {checkout.name}/{filename}")
        member = zipped.getinfo(f"{top}/manifest.json")
        if member.file_size > max_manifest:
            raise ValueError(f"{top}: manifest exceeds the catalog limit")
        return json.loads(zipped.read(member))


def replace_screenshots(folder, listing, captures):
    shots = folder / "shots"
    if shots.exists():
        shutil.rmtree(shots)
    shots.mkdir()
    listing["screenshots"] = []
    width, height = SCREENSHOT_SIZE
    for number, source in enumerate(captures, 1):
        destination = f"shots/{number}.png"
        with Image.open(source, formats=["PNG"]) as image:
            if image.width * height != image.height * width:
                raise ValueError(f"{source}: expected the Kindle portrait aspect ratio ({width}×{height})")
            background = Image.new("RGBA", image.size, "white")
            background.alpha_composite(image.convert("RGBA"))
            gray = background.convert("L").resize(SCREENSHOT_SIZE, Image.Resampling.LANCZOS)
            gray.save(folder / destination, optimize=True)
        listing["screenshots"].append(destination)


def stage_app(staging, review, app_id, version, release_date, checks, index, manifest_validator, opener, captures):
    repository = "app-template" if app_id == "primitive-hello" else app_id.removeprefix("primitive-")
    checkout = ROOT.parent / f"doannt-kindle-{repository}"
    source_folder = review / "apps" / app_id
    candidate = index["load"](source_folder / "app.json")
    canonical_repo = f"https://github.com/{OWNER}/kindle-primitive-{repository}"
    if candidate["id"] != app_id or candidate["repo"] != canonical_repo or candidate["source"] != "hosted":
        raise ValueError(f"{app_id}: reviewed listing does not match its canonical GitHub repository")
    local_draft = checkout / "app.json"
    if app_id == "primitive-store":
        expected_name = "Store"
    elif local_draft.is_file():
        expected_name = index["load"](local_draft)["name"]
    else:
        expected_name = None
    if expected_name is not None and candidate["name"] != expected_name:
        raise ValueError(f"{app_id}: regenerate the review listing and screenshots with the app's current display name")
    previous_folder = staging / "apps" / app_id
    previous = index["load"](previous_folder / "app.json")["versions"] if previous_folder.exists() else []
    key = index["version_key"]
    if previous and key(version) <= key(previous[0]["version"]):
        raise ValueError(f"{app_id} {version}: the staged release must be newer than its public listing")
    top = f"{app_id}-{version}"
    filename = f"{top}-{ARCH}.zip"
    url = f"{canonical_repo}/releases/download/v{version}/{filename}"
    baseline = candidate["versions"][0]
    with tempfile.TemporaryFile() as archive:
        asset = released_asset(opener, checks, url, filename, archive)
        manifest = read_release_metadata(archive, top, checkout, checks["MAX_MANIFEST"])
        release = {
            "version": version,
            "date": release_date.isoformat(),
            "notes": release_notes(checkout, app_id, version, baseline, previous),
            "firmware": manifest["firmware"],
            "requires": manifest.get("requires", {}),
            "tested_on": [],
            "assets": {ARCH: asset},
        }
        checks["validate_package"](archive, candidate, release, ARCH, manifest_validator)

    candidate["versions"] = [release, *previous]
    if previous_folder.exists():
        shutil.rmtree(previous_folder)
    shutil.copytree(source_folder, previous_folder)
    if captures:
        replace_screenshots(previous_folder, candidate, captures)
    index["dump"](previous_folder / "app.json", candidate)
    print(f"ok   {app_id} {version} {ARCH} {asset['size']} {asset['sha256']}", flush=True)


def stage(args):
    releases = dict(args.release)
    if len(releases) != len(args.release):
        raise ValueError("select each app release once")
    captures_by_app = {}
    for app_id, capture in args.screenshot:
        if app_id not in releases:
            raise ValueError(f"{app_id}: screenshots must accompany a selected release")
        captures_by_app.setdefault(app_id, []).append(capture.resolve(strict=True))
    for app_id, captures in captures_by_app.items():
        if len(captures) != len(set(captures)) or len(captures) > 5:
            raise ValueError(f"{app_id}: supply one to five distinct screenshots")
    missing_captures = SYSTEM_SCREENSHOTS.intersection(releases).difference(captures_by_app)
    if missing_captures:
        raise ValueError(f"Supply first-party --screenshot files for {', '.join(sorted(missing_captures))}")
    output = args.out.resolve()
    live_apps = ROOT / "apps"
    if output.exists() or output.is_relative_to(live_apps):
        raise ValueError(f"{output}: supply a new output directory outside the live apps folder")

    checks = runpy.run_path(str(ROOT / "scripts/check-assets.py"))
    index = runpy.run_path(str(ROOT / "scripts/build-index.py"))
    validator = Draft202012Validator(index["load"](ROOT / "schema/manifest.schema.json"))
    opener = urllib.request.build_opener(checks["Redirects"]())
    review = args.review.resolve(strict=True)

    with tempfile.TemporaryDirectory(prefix=".primitive-release-", dir=output.parent) as temp:
        staging = Path(temp) / "catalog"
        shutil.copytree(live_apps, staging / "apps")
        for app_id, version in sorted(releases.items()):
            stage_app(staging, review, app_id, version, args.date, checks, index, validator, opener,
                      captures_by_app.get(app_id, []))

        collections = index["load"](ROOT / "collections.json")
        ids = {path.name for path in (staging / "apps").iterdir() if path.is_dir()}
        for collection in collections["collections"]:
            if collection["id"] == "start-here":
                order = ("primitive-launcher", "primitive-store", "primitive-browser", "koreader")
                collection["apps"] = [app_id for app_id in order if app_id in ids]
            if collection["id"] == "made-by-primitive":
                collection["apps"] = sorted(app_id for app_id in ids if app_id.startswith("primitive-"))
        index["dump"](staging / "collections.json", collections)

        shutil.copytree(ROOT / "schema", staging / "schema")
        builder = staging / "scripts/build-index.py"
        builder.parent.mkdir()
        shutil.copyfile(ROOT / "scripts/build-index.py", builder)
        subprocess.run([
            sys.executable, "-I", str(builder), "--now", f"{args.date.isoformat()}T00:00:00Z",
        ], check=True)
        shutil.rmtree(builder.parent)
        shutil.rmtree(staging / "schema")
        staging.rename(output)
    print(f"Staged release listings and site in {output}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", type=Path, required=True, help="approved source art and listing copy from catalog-review")
    parser.add_argument("--out", type=Path, required=True, help="new output directory, with an existing parent")
    parser.add_argument("--date", type=date.fromisoformat, required=True, help="UTC release date (YYYY-MM-DD)")
    parser.add_argument("--release", type=release_arg, action="append", required=True, help="APP=VERSION, repeat for each release")
    parser.add_argument("--screenshot", type=screenshot_arg, action="append", default=[],
                        help="APP=PNG, repeat in display order to replace screenshots from the review")
    args = parser.parse_args()
    try:
        stage(args)
    except (LookupError, OSError, ValueError, zipfile.BadZipFile, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error)) from None


if __name__ == "__main__":
    main()
