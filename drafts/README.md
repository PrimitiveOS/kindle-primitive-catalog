# Drafts

Listings that are not published yet. The index builder reads only `apps/`, so a draft is never offered to a Kindle.

- `primitive-launcher/` and `primitive-browser/` wait for the packages of implementation plan B2: their asset URLs and
  sha256 values must come from real release files. The launcher's current sha256 is from its old 0.3.20 zip, and the
  browser's is a placeholder; neither may be published as it is.

To publish a draft: fill in its `assets` from the release file (sha256 and size), check it with `scripts/check-app.sh`,
then move the folder to `apps/`.
