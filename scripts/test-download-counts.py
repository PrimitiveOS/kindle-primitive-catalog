"""Offline checks for package classification and catalog coverage."""

import json
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError


reporter = runpy.run_path(str(Path(__file__).with_name("download-counts.py")))
collect, report_app = reporter["collect"], reporter["report_app"]
REPO = "https://github.com/DoanNguyenTrong/kindle-primitive-2048"
LISTING = {
    "id": "primitive-tidefork",
    "name": "2048",
    "repo": REPO,
    "versions": [
        {"version": "0.1.2", "assets": {"armhf": {"url": f"{REPO}/releases/download/v0.1.2/primitive-tidefork-0.1.2-armhf.zip"}}},
        {"version": "0.1.0", "withdrawn": True, "assets": {"armhf": {"url": f"{REPO}/releases/download/v0.1.0/primitive-tidefork-0.1.0-armhf.zip"}}},
    ],
}


def release(tag, *assets, draft=False):
    return {"tag_name": tag, "assets": assets, "draft": draft}


def asset(asset_id, name, downloads=1, state="uploaded"):
    return {"id": asset_id, "name": name, "download_count": downloads, "state": state}


class DownloadCountTests(unittest.TestCase):
    def test_counts_historical_and_manual_packages_once(self):
        current = release(
            "v0.1.2",
            asset(1, "primitive-tidefork-0.1.2-armhf.zip", 20),
            asset(2, "primitive-tidefork-0.1.2-armhf.zip.sha256", 100),
            asset(7, "primitive-tidefork-0.1.2-armel.zip", 2),
        )
        archived = release(
            "v0.0.1",
            asset(3, "primitive-tidefork-0.0.1.zip", 5),
            asset(4, "source.zip", 10),
            asset(5, "primitive-tidefork-0.0.1-armhf.zip", 10, state="starter"),
        )
        draft = release("v0.1.3", asset(6, "primitive-tidefork-0.1.3-armhf.zip", 10), draft=True)
        self.assertEqual(report_app(LISTING, [current, current, draft, archived]), (27, 3))

    def test_requires_live_catalog_assets_from_their_own_release(self):
        wrong_release = release("v0.1.3", asset(1, "primitive-tidefork-0.1.2-armhf.zip"))
        with self.assertRaisesRegex(ValueError, "every active package"):
            report_app(LISTING, [wrong_release])

    def test_zero_is_a_real_count_and_missing_is_an_error(self):
        current = release("v0.1.2", asset(1, "primitive-tidefork-0.1.2-armhf.zip", 0))
        self.assertEqual(report_app(LISTING, [current]), (0, 1))
        with self.assertRaisesRegex(ValueError, "every active package"):
            report_app(LISTING, [])
        with self.assertRaisesRegex(ValueError, "Invalid GitHub download counter"):
            report_app(LISTING, [release("v0.1.2", asset(1, "primitive-tidefork-0.1.2-armhf.zip", True))])

    def test_reports_available_apps_when_another_repository_fails(self):
        notes_repo = "https://github.com/DoanNguyenTrong/kindle-primitive-notes"
        rows = [
            LISTING | {"source": "hosted"},
            {"id": "primitive-notes", "source": "hosted", "name": "Notes", "repo": notes_repo, "versions": []},
            {"id": "koreader", "source": "link", "repo": "https://github.com/koreader/koreader"},
        ]

        def fake_releases(repository, _token):
            if repository.endswith("-notes"):
                raise HTTPError(notes_repo, 503, "Unavailable", {}, None)
            return [release("v0.1.2", asset(1, "primitive-tidefork-0.1.2-armhf.zip", 2))]

        with tempfile.TemporaryDirectory() as temporary, patch.dict(collect.__globals__, releases=fake_releases):
            root = Path(temporary)
            for row in rows:
                folder = root / row["id"]
                folder.mkdir()
                (folder / "app.json").write_text(json.dumps(row))
            urls = [(row["id"], row["downloads"], row["error"]) for row in collect(root, None)]
        self.assertEqual(urls, [("primitive-tidefork", 2, None), ("primitive-notes", None, "GitHub API returned HTTP 503")])


if __name__ == "__main__":
    unittest.main()
