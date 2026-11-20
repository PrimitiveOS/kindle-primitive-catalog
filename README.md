# PrimitiveOS app catalog

Store reads the public PrimitiveOS app catalog from GitHub Pages. This repository publishes `index.json` for app cards,
`collections.json` for Today groups, `apps/<id>.json` for individual listings, and the icons and screenshots.
[Store source](https://github.com/DoanNguyenTrong/kindle-primitive-store)

No binaries are kept here. A listing points at a release asset, and the store checks its size and SHA-256 before it
installs anything.

## Add or update an app

Read [docs/store-submit-app.md](https://github.com/DoanNguyenTrong/kindle-primitive/blob/main/docs/store-submit-app.md) in the
PrimitiveOS umbrella repo. Add `apps/<id>/app.json`, `icon.png` and `shots/`, run `sh scripts/test.sh`, and open a pull request.
The catalog tools require Python 3 with `jsonschema` and `Pillow`. CI verifies live package downloads, manifests and
archive contents. A scheduled check monitors published asset sizes and hashes.

## App downloads

[App download counts](https://github.com/DoanNguyenTrong/kindle-primitive-catalog/actions/workflows/download-counts.yml)
runs daily and on demand. Each run shows the latest per-app totals and saves a JSON and CSV snapshot in the
`app-download-counts` artifact. The report uses GitHub's public release metadata and needs no Kindle telemetry.
[GitHub release counters](https://docs.github.com/en/rest/releases/releases?apiVersion=2026-03-10#list-releases)

Totals include GitHub downloads of package ZIPs across releases and architectures, including manual-install ZIPs,
updates, repeat downloads, and automated checks. They measure package downloads across all channels. A linked
third-party app such as KOReader is outside the report. If GitHub cannot supply a count, the report marks the app
unavailable and flags the run. Removing a release asset removes that asset's counter from future snapshots.

To create a snapshot locally, run `python3 -I scripts/download-counts.py --out /tmp/primitive-download-counts`.

## Layout

| Path | What |
|---|---|
| `apps/<id>/` | A published app: `app.json`, `icon.png`, `shots/`. |
| `collections.json` | Ordered Today collections and their published app IDs. |
| `drafts/` | Listings that are not published yet (see `drafts/README.md`). |
| `schema/` | Copies of the JSON schemas in the PrimitiveOS umbrella repository. CI checks they match. |
| `scripts/check-app.sh` | Checks one app: schema, icon and screenshot sizes and colour. |
| `scripts/check-assets.py` | Checks live asset sizes and hashes. Pass `--deep` to also validate ZIP contents. |
| `scripts/download-counts.py` | Summarizes GitHub's download counters for first-party package assets. |
| `scripts/build-index.py` | Builds `site/v1/` (the index and the listings). |
| `scripts/test.sh` | What CI runs before anything is published. |

## Licence

The first-party software in `scripts/` and the build workflows in `.github/workflows/` use the
[PolyForm Noncommercial License 1.0.0](LICENSE). The shared JSON schemas use the same software licence.

Doan Nguyen's listings, icons, and grayscale screenshots are under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/).
Each listing names the app's own licence. KOReader's stock icon (`apps/koreader/icon.png`) comes from the KOReader
project and is under AGPL-3.0.
