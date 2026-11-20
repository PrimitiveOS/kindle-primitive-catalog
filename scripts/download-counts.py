#!/usr/bin/env python3
"""Report GitHub package downloads for the first-party apps in Store."""

import argparse
import csv
import html
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


ROOT = Path(__file__).resolve().parents[1]
OWNER = "DoanNguyenTrong"
API = "https://api.github.com"
REPOSITORY = re.compile(rf"https://github\.com/({OWNER}/[a-z0-9._-]+)", re.IGNORECASE)
PACKAGE_SUFFIX = r"-v?\d+(?:\.\d+)+(?:-p\d+)?(?:-arm(?:hf|el))?\.zip"


def github_api_url(url):
    address = urlsplit(url)
    return address.scheme == "https" and address.netloc == "api.github.com"


class ApiRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        if not github_api_url(new_url):
            raise ValueError("Unexpected GitHub API redirect")
        return super().redirect_request(request, response, code, message, headers, new_url)


def releases(repository, token):
    url = f"{API}/repos/{repository}/releases?per_page=100"
    opener = build_opener(ApiRedirects())
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "PrimitiveOS-download-report",
        "X-GitHub-Api-Version": "2026-03-10",
    }
    visited = set()
    while url:
        if url in visited or not github_api_url(url):
            raise ValueError("Unexpected GitHub API pagination")
        visited.add(url)
        auth = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            response = opener.open(Request(url, headers=headers | auth), timeout=20)
        except HTTPError as error:
            if not auth or error.code not in (401, 403, 404):
                raise
            # The Actions token may lack access to another repository. Public release metadata
            # is also available without credentials.
            error.close()
            token = None
            response = opener.open(Request(url, headers=headers), timeout=20)
        with response:
            page = json.load(response)
            if not isinstance(page, list):
                raise ValueError("Expected a list of GitHub releases")
            yield from page
            match = re.search(r'<([^>]+)>;\s*rel="next"', response.headers.get("Link", ""))
            url = match[1] if match else None


def report_app(listing, entries):
    reference_packages = {
        tuple(map(unquote, urlsplit(asset["url"]).path.rsplit("/", 2)[-2:]))
        for version in listing["versions"] if not version.get("withdrawn")
        for asset in version.get("assets", {}).values()
    }
    package_name = re.compile(re.escape(listing["id"]) + PACKAGE_SUFFIX)
    found = {}
    for release in entries:
        if release["draft"]:
            continue
        for asset in release["assets"]:
            name = asset["name"]
            release_tag = release["tag_name"]
            if asset["state"] != "uploaded" or not name.endswith(".zip"):
                continue
            if (release_tag, name) not in reference_packages and not package_name.fullmatch(name):
                continue
            downloads = asset["download_count"]
            if type(downloads) is not int or downloads < 0:
                raise ValueError("Invalid GitHub download counter")
            found[asset["id"]] = (release_tag, name, downloads)

    if not reference_packages <= {(tag, name) for tag, name, _ in found.values()}:
        raise ValueError("GitHub did not return every active package in the catalog")
    return sum(downloads for _, _, downloads in found.values()), len(found)


def collect(apps, token):
    report = []
    for path in sorted(apps.glob("*/app.json")):
        listing = json.loads(path.read_text(encoding="utf-8"))
        match = REPOSITORY.fullmatch(listing.get("repo", ""))
        if listing["source"] != "hosted" or not match:
            continue
        row = {key: listing[key] for key in ("id", "name", "repo")}
        row.update(downloads=None, packages=None, error=None)
        try:
            row["downloads"], row["packages"] = report_app(listing, releases(match[1], token))
        except HTTPError as error:
            row["error"] = f"GitHub API returned HTTP {error.code}"
            error.close()
        except (URLError, TimeoutError, OSError):
            row["error"] = "Unable to read the GitHub API"
        except (ValueError, KeyError, TypeError):
            row["error"] = "GitHub release data is incomplete or invalid"
        report.append(row)
    return sorted(report, key=lambda row: (row["downloads"] is None, -(row["downloads"] or 0), row["name"].casefold()))


def markdown(report):
    def cell(text):
        return html.escape(" ".join(text.splitlines())).replace("|", "&#124;")

    yield "# First-party app downloads"
    yield ""
    yield f'Collected {report["generated_at"]}. Available counts for {report["apps_counted"]} of {len(report["apps"])} apps.'
    yield ""
    yield "Counts come from GitHub release ZIPs across Store and direct downloads. They include repeats and automated checks."
    yield ""
    yield "| App | Package downloads | ZIPs counted | Status |"
    yield "|---|---:|---:|---|"
    for row in report["apps"]:
        downloads, packages = row["downloads"], row["packages"]
        values = f"{downloads:,} | {packages:,}" if downloads is not None else "Unavailable | —"
        yield f'| [{cell(row["name"])}]({row["repo"]}) | {values} | {cell(row["error"] or "Available")} |'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="directory for the JSON, CSV and Markdown reports")
    args = parser.parse_args()
    rows = collect(ROOT / "apps", os.environ.get("GITHUB_TOKEN"))
    if not rows:
        parser.error("no first-party apps in the catalog")
    counted = sum(row["downloads"] is not None for row in rows)
    report = {
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "github_release_asset_download_count",
        "apps_counted": counted,
        "apps": rows,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "download-counts.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.out / "download-counts.md").write_text("\n".join(markdown(report)) + "\n", encoding="utf-8")
    with (args.out / "download-counts.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            name = row["name"]
            if name.lstrip().startswith(("=", "+", "-", "@")):
                name = "'" + name
            writer.writerow(row | {"name": name})
    print(f"Collected download counts for {counted} of {len(rows)} first-party apps.")
    return 0 if counted == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
