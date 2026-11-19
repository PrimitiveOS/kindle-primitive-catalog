# Primitive Store catalog

The public list of apps for Primitive Store. The store on a Kindle reads the static files published here
(GitHub Pages): `index.json` (the cards), `collections.json` (the Today groups), `apps/<id>.json` (each listing),
and the icons and screenshots.

No binaries are kept here. A listing points at a release asset, and the store checks its size and SHA-256 before it
installs anything.

## Add or update an app

Read [docs/store-submit-app.md](https://github.com/DoanNguyenTrong/kindle-primitive/blob/main/docs/store-submit-app.md) in the
umbrella repo. Add `apps/<id>/app.json`, `icon.png` and `shots/`, run `sh scripts/test.sh`, and open a pull request.
The catalog tools require Python 3 with `jsonschema` and `Pillow`. CI verifies live package downloads, manifests and
archive contents. A scheduled check monitors published asset sizes and hashes.

## Layout

| Path | What |
|---|---|
| `apps/<id>/` | A published app: `app.json`, `icon.png`, `shots/`. |
| `collections.json` | Ordered Today collections and their published app IDs. |
| `drafts/` | Listings that are not published yet (see `drafts/README.md`). |
| `schema/` | The JSON schemas, copies of the umbrella repo's (CI checks they match). |
| `scripts/check-app.sh` | Checks one app: schema, icon and screenshot sizes and colour. |
| `scripts/check-assets.py` | Checks live asset sizes and hashes. Pass `--deep` to also validate ZIP contents. |
| `scripts/build-index.py` | Builds `site/v1/` (the index and the listings). |
| `scripts/test.sh` | What CI runs before anything is published. |

## Licence

The listings, and our icons and screenshots, are under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/).
Each app's own files are under that app's licence, named in its listing. An app's icon is that app's own artwork, with
credit to its authors: the KOReader icon (`apps/koreader/icon.png`) is KOReader's stock icon from its repository, under
AGPL-3.0.
