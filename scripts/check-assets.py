#!/usr/bin/env python3
"""Check every live asset, or selected listings. Pass --deep to verify the packaged manifest and every ZIP entry."""
import argparse
import hashlib
import html
import json
import os
import stat
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
MAX_BYTES = 200 * 1024 * 1024
MAX_MANIFEST = 256 * 1024
MAX_FILES = 5000
HOSTS = {
    "github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com",
    "raw.githubusercontent.com", "primitiveos.github.io",
}
RESERVED = {"documents", "extensions", "system", "fonts", "screensaver", "koreader"}
HOOKS = {"hooks/post-install.sh", "hooks/pre-uninstall.sh"}
MAX_HOOK_BYTES = 64 * 1024


def check_url(url):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in HOSTS or parsed.port not in (None, 443)
            or parsed.username is not None or parsed.password is not None):
        raise ValueError("URL or redirect is outside the Store's allowed HTTPS hosts")


class Redirects(urllib.request.HTTPRedirectHandler):
    max_redirections = 5

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(asset, destination):
    url, size, expected = asset["url"], asset["size"], asset["sha256"]
    if not 0 < size <= MAX_BYTES:
        raise ValueError(f"asset must be 1 to {MAX_BYTES} bytes")
    check_url(url)
    digest = hashlib.sha256()
    total = 0
    deadline = time.monotonic() + 180
    with urllib.request.build_opener(Redirects()).open(url, timeout=30) as response:
        while chunk := response.read(64 * 1024):
            total += len(chunk)
            if total > size:
                raise ValueError(f"download exceeds the listed size of {size} bytes")
            if time.monotonic() > deadline:
                raise ValueError("download timed out")
            digest.update(chunk)
            if destination is not None:
                destination.write(chunk)
    if total != size:
        raise ValueError(f"size is {total}, the listing says {size}")
    if digest.hexdigest() != expected.lower():
        raise ValueError("SHA-256 does not match the listing")


def safe_parts(name):
    if "\\" in name or "\0" in name or any(part in ("", ".", "..") for part in name.split("/")):
        raise ValueError("unsafe ZIP entry path")
    return name.split("/")


def installed_path(path, app_dir):
    parts = safe_parts(path)
    return (
        len(parts) >= 2 and parts[0] == "documents"
        or len(parts) >= 3 and parts[:2] == ["extensions", app_dir]
        or len(parts) >= 2 and parts[0] == app_dir and app_dir not in RESERVED
    )


def validate_package(source, listing, version, arch, validator):
    app_id = listing["id"]
    app_dir = listing.get("dir", app_id)
    top = f"{app_id}-{version['version']}"
    required = {"manifest.json", "LICENSE", "INSTALL.md"}
    with zipfile.ZipFile(source) as archive:
        entries = archive.infolist()
        if not entries or len(entries) > MAX_FILES:
            raise ValueError(f"ZIP must contain 1 to {MAX_FILES} entries")
        if sum(entry.file_size for entry in entries) > MAX_BYTES:
            raise ValueError(f"ZIP exceeds {MAX_BYTES} bytes when unpacked")
        seen = set()
        files = set()
        for entry in entries:
            name = entry.orig_filename.removesuffix("/") if entry.is_dir() else entry.orig_filename
            parts = safe_parts(name)
            if parts[0] != top or (len(parts) == 1 and not entry.is_dir()):
                raise ValueError(f"ZIP must have one top directory named {top}")
            if name in seen:
                raise ValueError("ZIP contains a duplicate entry")
            seen.add(name)
            kind = stat.S_IFMT(entry.external_attr >> 16) if entry.create_system == 3 else 0
            if kind not in (0, stat.S_IFDIR if entry.is_dir() else stat.S_IFREG):
                raise ValueError("ZIP contains a symbolic link or special file")
            if entry.flag_bits & 1 or entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                raise ValueError("ZIP contains an encrypted entry or an unsupported compression method")
            if not entry.is_dir():
                files.add("/".join(parts[1:]))
        missing = required - files
        if missing:
            raise ValueError(f"ZIP is missing {', '.join(sorted(missing))}")
        for path in files:
            parts = path.split("/")
            if any("/".join(parts[:i]) in files for i in range(1, len(parts))):
                raise ValueError("a ZIP path is both an installed file and a parent directory")
        member = archive.getinfo(f"{top}/manifest.json")
        if member.file_size > MAX_MANIFEST:
            raise ValueError(f"manifest is larger than {MAX_MANIFEST} bytes")
        manifest = json.loads(archive.read(member))
        errors = list(validator.iter_errors(manifest))
        if errors:
            raise ValueError(f"invalid manifest: {errors[0].message}")
        for key, expected in (
            ("id", app_id), ("dir", app_dir), ("version", version["version"]),
            ("arch", arch), ("requires", version.get("requires", {})),
        ):
            actual = manifest.get(key, {} if key == "requires" else None)
            if actual != expected:
                raise ValueError(f"manifest {key} disagrees with the listing")
        actual, expected = manifest["firmware"], version["firmware"]
        if actual["min"] != expected["min"] or actual.get("max") != expected.get("max"):
            raise ValueError("manifest firmware disagrees with the listing")
        hooks = set(manifest.get("hooks", []))
        if hooks != files.intersection(HOOKS) or bool(hooks) != listing["changes"]["hooks"]:
            raise ValueError("ZIP, manifest and listing must agree on hooks")
        for path in sorted(hooks):
            with archive.open(f"{top}/{path}") as script:
                contents = script.read(MAX_HOOK_BYTES + 1)
            if not 0 < len(contents) <= MAX_HOOK_BYTES or b"\0" in contents:
                raise ValueError(f"{path}: expected a nonempty shell script of at most {MAX_HOOK_BYTES} bytes")
        installed = files - required - hooks - {"LICENSE-DOCS"}
        if installed != set(manifest["files"]):
            raise ValueError("ZIP contents disagree with the manifest file list")
        if not all(installed_path(path, app_dir) for path in installed):
            raise ValueError("ZIP contains a file outside the app's allowed folders")
        if archive.testzip() is not None:
            raise ValueError("ZIP contains a damaged file")
    return sorted(hooks)


def listing_paths(paths):
    if paths:
        return [path / "app.json" if path.is_dir() else path for path in paths]
    return sorted((ROOT / "apps").glob("*/app.json"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deep", action="store_true")
    parser.add_argument("apps", nargs="*", type=Path)
    args = parser.parse_args()
    if args.deep:
        from jsonschema import Draft202012Validator
        schema = json.loads((ROOT / "schema" / "manifest.schema.json").read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema)
    failed = False
    reports = []
    for path in listing_paths(args.apps):
        listing = json.loads(path.read_text(encoding="utf-8"))
        flags = [name.replace("_", " ") for name, enabled in listing["changes"].items()
                 if name != "notes" and enabled]
        if listing["source"] == "link":
            print(f"skip {listing['id']} (link)")
            continue
        for version in listing["versions"]:
            if version.get("withdrawn"):
                continue
            for arch, asset in version["assets"].items():
                label = f"{listing['id']} {version['version']} {arch}"
                try:
                    hooks = []
                    if args.deep:
                        with tempfile.TemporaryFile() as source:
                            download(asset, source)
                            source.seek(0)
                            hooks = validate_package(source, listing, version, arch, validator)
                    else:
                        download(asset, None)
                    print(f"ok   {label}")
                    notes = ", ".join(flags + hooks) or "none"
                    reports.append((label, f"{asset['size']:,} bytes, changes: {notes}"))
                except (OSError, ValueError, RuntimeError, NotImplementedError, zipfile.BadZipFile) as error:
                    failed = True
                    print(f"FAIL {label}: {error}")
                    reports.append((label, "failed; see the validation log"))
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as output:
            output.write("## Catalog assets\n\n")
            for label, notes in reports:
                output.write(f"- {html.escape(label)} — {html.escape(notes)}\n")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
