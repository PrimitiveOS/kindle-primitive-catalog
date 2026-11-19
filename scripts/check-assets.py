#!/usr/bin/env python3
"""Download each published asset of hosted and upstream listings and check its size and SHA-256 against the listing.

    python3 scripts/check-assets.py            # all apps in apps/
    python3 scripts/check-assets.py apps/X     # one app

Link listings have no assets and are skipped. Exit status 1 when any asset does not match or cannot be fetched.
"""
import hashlib
import json
import os
import sys
import tempfile
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def check_asset(url, sha256, size, timeout=60):
    """Returns None when the URL serves a file with this size and hash, else a short reason."""
    digest = hashlib.sha256()
    total = 0
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            while True:
                chunk = r.read(64 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                total += len(chunk)
    except Exception as e:  # network errors are reported, not hidden
        return f"cannot fetch: {e}"
    if total != size:
        return f"size is {total}, the listing says {size}"
    if digest.hexdigest() != sha256.lower():
        return "sha256 does not match the listing"
    return None


def apps(paths):
    if paths:
        return [os.path.join(p, "app.json") if os.path.isdir(p) else p for p in paths]
    base = os.path.join(ROOT, "apps")
    return [os.path.join(base, d, "app.json") for d in sorted(os.listdir(base))
            if os.path.isfile(os.path.join(base, d, "app.json"))]


def main(argv):
    failed = 0
    for path in apps(argv):
        listing = json.load(open(path, encoding="utf-8"))
        if listing["source"] == "link":
            print(f"skip {listing['id']} (link)")
            continue
        for v in listing["versions"]:
            if v.get("withdrawn"):
                continue
            for arch, asset in v.get("assets", {}).items():
                reason = check_asset(asset["url"], asset["sha256"], asset["size"])
                label = f"{listing['id']} {v['version']} {arch}"
                if reason:
                    failed += 1
                    print(f"FAIL {label}: {reason}")
                else:
                    print(f"ok   {label}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
