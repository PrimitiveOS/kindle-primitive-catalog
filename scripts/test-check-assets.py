"""Offline checks for the library entry rules in the deep package check."""

import io
import json
import runpy
import unittest
import zipfile
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parent.parent
checks = runpy.run_path(str(Path(__file__).with_name("check-assets.py")))
validate_package = checks["validate_package"]
VALIDATOR = Draft202012Validator(json.loads((ROOT / "schema" / "manifest.schema.json").read_text(encoding="utf-8")))
VERSION = {"version": "0.1.0", "firmware": {"min": "5.16.3"}}
NATIVE = "#!/bin/sh\n# Name: Sample\n# Author: Primitive AI\n# DontUseFBInk\n"
LAUNCH = "exec /mnt/us/sample/bin/sample-kindle\n"


def listing(app_id):
    return {"id": app_id, "dir": "sample", "changes": {"hooks": False}}


def package(app_id, entry):
    top = f"{app_id}-{VERSION['version']}"
    files = {"documents/Sample.sh": entry, "sample/bin/sample-kindle": "binary"}
    manifest = {"schema": 1, "id": app_id, "dir": "sample", "version": VERSION["version"], "arch": "armhf",
                "firmware": VERSION["firmware"], "files": sorted(files)}
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr(f"{top}/manifest.json", json.dumps(manifest))
        archive.writestr(f"{top}/LICENSE", "licence")
        archive.writestr(f"{top}/INSTALL.md", "install")
        for path, contents in files.items():
            archive.writestr(f"{top}/{path}", contents)
    data.seek(0)
    return data


def check(app_id, entry):
    warnings = []
    validate_package(package(app_id, entry), listing(app_id), VERSION, "armhf", VALIDATOR, warnings.append)
    return warnings


class WakeRedraw(unittest.TestCase):
    def test_a_new_native_app_must_declare_wake_redraw(self):
        with self.assertRaisesRegex(ValueError, "documents/Sample.sh: a native app entry must declare '# Wake: redraw'"):
            check("primitive-sample", NATIVE + LAUNCH)
        self.assertEqual(check("primitive-sample", NATIVE + "# Wake: redraw\n" + LAUNCH), [])

    def test_an_app_listed_before_the_rule_gets_a_warning(self):
        warnings = check("primitive-snake", NATIVE + LAUNCH)
        self.assertEqual(len(warnings), 1)
        self.assertIn("'# Wake: redraw'", warnings[0])
        self.assertEqual(check("primitive-snake", NATIVE + "# Wake: redraw\n" + LAUNCH), [])

    def test_the_line_is_matched_as_the_supervisor_matches_it(self):
        # `head -n 10 | grep -Fx '# Wake: redraw'`: an exact line in the first ten, after a command line too.
        late = NATIVE + "#\n" * 6 + "# Wake: redraw\n" + LAUNCH
        with self.assertRaises(ValueError, msg="the eleventh line"):
            check("primitive-sample", late)
        for wrong in ("# Wake: redraw \n", "# Wake: redraw\r\n", "#Wake: redraw\n", "# wake: redraw\n"):
            with self.assertRaises(ValueError, msg=repr(wrong)):
                check("primitive-sample", NATIVE + wrong + LAUNCH)
        self.assertEqual(check("primitive-sample", NATIVE + "set -eu\n# Wake: redraw\n" + LAUNCH), [])

    def test_only_native_app_entries_are_checked(self):
        launcher = "#!/bin/sh\n# Name: Launcher\n# DontUseFBInk\n# PrimitiveLauncherEntry\n" + LAUNCH
        self.assertEqual(check("primitive-sample", launcher), [], "the launcher is the system layer")
        stock = "#!/bin/sh\n# Name: Sample\n# Author: Someone\n" + LAUNCH
        self.assertEqual(check("primitive-sample", stock), [], "an entry drawn by FBInk is not a native app")
        after_header = "#!/bin/sh\n# Name: Sample\nset -eu\n# DontUseFBInk\n" + LAUNCH
        self.assertEqual(check("primitive-sample", after_header), [], "the marker counts only in the header")


if __name__ == "__main__":
    unittest.main(verbosity=2)
