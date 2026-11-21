"""The schema accepts only known Kindle model names in a version's tested_on list."""
import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent


class TestedOnNames(unittest.TestCase):
    def setUp(self):
        self.validator = Draft202012Validator(json.loads((ROOT / "schema" / "app.schema.json").read_text()))
        listings = [json.loads(path.read_text()) for path in sorted((ROOT / "apps").glob("*/app.json"))]
        installable = [listing for listing in listings if listing["source"] != "link"]
        self.listing = installable[0]

    def errors_with_tested_on(self, names):
        listing = copy.deepcopy(self.listing)
        listing["versions"][0]["tested_on"] = names
        return list(self.validator.iter_errors(listing))

    def test_a_known_model_name_is_accepted(self):
        self.assertEqual(self.errors_with_tested_on(["KindleOasis3"]), [])

    def test_a_misspelt_model_name_is_rejected(self):
        self.assertTrue(self.errors_with_tested_on(["KindleOasis 3"]), "a misspelt name must not pass")

    def test_a_name_is_listed_once(self):
        self.assertTrue(self.errors_with_tested_on(["KindleOasis3", "KindleOasis3"]))


if __name__ == "__main__":
    unittest.main()
