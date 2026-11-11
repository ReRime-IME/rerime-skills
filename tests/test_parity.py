"""The table checker against the answers of ReRime's own importer.

tests/parity/expected.json holds what the importer (the Swift code of the ReRime App,
compiled on a Mac) decides about every case of tests/parity/generate_corpus.py. This test
writes the same corpus and requires the checker to decide the same, without the App
repository. tests/parity/README.md says how the expected answers are refreshed.

The cases that cross ReRime's real caps (300,000 rows, 16 MiB, 64 MiB) need a few hundred
megabytes of disk: set RERIME_PARITY_LARGE=1 to run them too.
"""
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

PARITY = Path(__file__).resolve().parent / "parity"
spec = importlib.util.spec_from_file_location("parity_compare", PARITY / "compare.py")
compare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compare)


class ImporterParity(unittest.TestCase):
    def test_checker_decides_what_the_importer_decided(self):
        expected = json.loads((PARITY / "expected.json").read_text(encoding="utf-8"))
        large = os.environ.get("RERIME_PARITY_LARGE") == "1"
        with tempfile.TemporaryDirectory() as folder:
            cases = compare.corpus.write(folder, large)
            self.assertEqual({case["name"] for case in cases},
                             {name for name in expected if large or not name.startswith("large-")})
            for case in cases:
                with self.subTest(case=case["name"]):
                    found = compare.differences(compare.checker_report(case), expected[case["name"]])
                    self.assertEqual(found, [])

    def test_expected_answers_cover_every_rule(self):
        expected = json.loads((PARITY / "expected.json").read_text(encoding="utf-8")).values()
        refusals = {report.get("refusal") for report in expected} - {None}
        # doesNotFitEngine cannot be reached: a whole-word table of two rows or more always
        # passes the exact test (see tests/parity/README.md).
        self.assertEqual(refusals, set(compare.checker.REFUSALS) - {"doesNotFitEngine"})
        skipped = {reason for report in expected for reason in report.get("skipped", {})}
        self.assertEqual(skipped, set(compare.checker.SKIP_REASONS))
        problems = {report["problem"] for report in expected if report.get("refusal") == "archiveUnsupported"}
        self.assertEqual(problems, set(compare.checker.ARCHIVE_PROBLEMS))
        tables = [report for report in expected if report["outcome"] == "table" and report["analysis"]]
        states = {(report["scheme"], report["schemeNeedsExactCheck"]) for report in tables}
        self.assertEqual(states, {("rerime_user_syllable", False), ("rerime_user_syllable", True),
                                  ("rerime_user_table", False), ("rerime_user_table", True)})
        self.assertIn("doesNotFit", {(report["analysis"]["bySyllableBudget"] or {}).get("state") for report in tables})


if __name__ == "__main__":
    unittest.main()
