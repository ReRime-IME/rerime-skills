"""Tests for the two checkers. Run from the repository root:

    python3 -m unittest discover -s tests -v

Every fixture is synthetic: invented codes, no real input scheme and no user data.
"""
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "plugins/rerime-dictionary/skills/rerime-dictionary/scripts"
FIXTURES = ROOT / "tests/fixtures"

spec = importlib.util.spec_from_file_location("validate_rerime_table", SCRIPTS / "validate_rerime_table.py")
table = importlib.util.module_from_spec(spec)
spec.loader.exec_module(table)


def run(script, path):
    done = subprocess.run([sys.executable, str(SCRIPTS / script), str(path)], capture_output=True, text=True)
    return done.returncode, done.stdout


def check(text):
    """Run the table checker on `text` saved as a file; returns (exit code, output)."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "table.txt"
        path.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
        return run("validate_rerime_table.py", path)


def rows(text):
    return table.read(text.encode("utf-8"))[0]


class TableFixtures(unittest.TestCase):
    def test_by_syllable(self):
        code, output = run("validate_rerime_table.py", FIXTURES / "by-syllable.txt")
        self.assertEqual(code, 0, output)
        self.assertIn("OK 40 rows", output)
        self.assertIn("Run mode: by syllable", output)
        self.assertIn("10 of 10 multi-character rows", output)
        self.assertIn("30 syllables (at most 3,500), 90 spellings (at most 20,000)", output)
        self.assertIn("optional trailing letters: p, t, x", output)

    def test_whole_word(self):
        code, output = run("validate_rerime_table.py", FIXTURES / "whole-word.txt")
        self.assertEqual(code, 0, output)
        self.assertIn("OK 14 rows", output)
        self.assertIn("Run mode: whole word", output)
        self.assertIn("only 0 of 6 multi-character rows", output)

    def test_invalid(self):
        code, output = run("validate_rerime_table.py", FIXTURES / "invalid.txt")
        self.assertEqual(code, 1, output)
        for line, reason in [(6, "code must be letters a-z only"), (7, "no code"), (8, "expected text<TAB>code"),
                             (9, "whole-number weight"), (10, "control, format"), (11, "duplicate"),
                             (12, "command value")]:
            self.assertRegex(output, rf"SKIP line {line}: .*{reason}")
        self.assertIn("ReRime would import 5 rows and skip 7", output)


class TableRules(unittest.TestCase):
    def test_refusals(self):
        for text, reason in [
            (b"", "empty"),
            ("天\tba\n".encode("gb18030"), "not UTF-8"),
            ("天 ba\n地 bo\n", "no tab-separated rows"),
            ("天\tba\n", "at least 2"),
            ("天\tb1\n地\tb2\n玄\tda\n", "more invalid rows than valid"),
        ]:
            code, output = check(text)
            self.assertEqual(code, 1, output)
            self.assertIn("ERROR", output)
            self.assertIn(reason, output)

    def test_caps(self):
        saved = table.MAX_ROWS, table.MAX_BYTES
        try:
            table.MAX_ROWS = 3
            with self.assertRaisesRegex(table.Refusal, "4 rows; the limit is 3"):
                rows("天\tba\n地\tbo\n玄\tda\n黄\tdo\n")
            table.MAX_BYTES = 8
            with self.assertRaisesRegex(table.Refusal, "16 MiB"):
                rows("天\tba\n地\tbo\n")
        finally:
            table.MAX_ROWS, table.MAX_BYTES = saved

    def test_code_and_text_limits(self):
        self.assertEqual(table.check_code("a" * 96), ("a" * 96, None))
        self.assertIn("longer than 96", table.check_code("a" * 97)[1])
        self.assertEqual(table.check_code("Ba  bo"), ("ba bo", None))
        self.assertIsNotNone(table.check_code("ba-bo")[1])
        self.assertEqual(table.check_text("字" * 80), ("字" * 80, None))
        self.assertIn("longer than 80", table.check_text("字" * 81)[1])
        self.assertEqual(table.check_text("　a b "), ("a b", None))
        for bad in ["a b", "a‮b", "❤️", "a\x07", "e" + "́" * 5, ""]:
            self.assertIsNotNone(table.check_text(bad)[1], repr(bad))

    def test_code_first_columns_and_weights(self):
        # The code may be the first column; within one code the higher weight comes first.
        self.assertEqual(rows("ba\t天\t5\nba\t地\t9\nbo\t玄\n"), [("地", "ba", 9), ("天", "ba", 5), ("玄", "bo", -1)])

    def test_rime_dictionary(self):
        text = ("# comment\n---\nname: sample\nversion: \"1\"\nsort: original\ncolumns:\n  - code\n  - text\n...\n"
                "# a comment line\nba\t天\nbo\t地\nba bo\t天地\n")
        self.assertEqual(rows(text), [("天", "ba", -1), ("天地", "babo", -1), ("地", "bo", -1)])
        code, output = check(text)
        self.assertEqual(code, 0, output)
        self.assertIn("read as a Rime dictionary", output)
        self.assertIn("Run mode: by syllable", output)

    def test_no_words_runs_whole_word(self):
        code, output = check("α\tba\nβ\tbo\n")
        self.assertEqual(code, 0, output)
        self.assertIn("Run mode: whole word", output)
        self.assertIn("no multi-character rows", output)
        self.assertNotIn("personal dictionary import", output)

    def test_one_percent_of_other_rows_is_allowed(self):
        singles = "".join(f"{chr(0x4E00 + i)}\tb{chr(97 + i // 26)}{chr(97 + i % 26)}\n" for i in range(200))
        words = "".join(f"{chr(0x4E00 + i)}{chr(0x4E01 + i)}\tb{chr(97 + i // 26)}{chr(97 + i % 26)}"
                        f"b{chr(97 + (i + 1) // 26)}{chr(97 + (i + 1) % 26)}\n" for i in range(199))
        self.assertIn("Run mode: by syllable", check(singles + words + "一二三\tzzz\n")[1])
        self.assertIn("Run mode: whole word", check(singles + words + "一二三\tzzz\n一三\tzzy\n三一\tzzx\n")[1])

    def test_syllable_bound(self):
        # 3,501 syllables: built by syllable, but over the bound, so it runs whole word.
        letters = "abcdefghijklmnopqrstuvwxyz"
        codes = [a + b + c for a in letters for b in letters for c in letters][:3501]
        text = "".join(f"{chr(0x4E00 + i)}\t{code}\n" for i, code in enumerate(codes))
        code, output = check(text + f"{chr(0x4E00)}{chr(0x4E01)}\t{codes[0]}{codes[1]}\n")
        self.assertEqual(code, 0, output)
        self.assertIn("Run mode: whole word", output)
        self.assertIn("over a bound: 3,501 syllables", output)

    def test_head_coded_rows_and_merges(self):
        # A long entry coded by its first characters only still counts as built by syllable.
        result = table.analyze(rows("天\tba\n地\tbo\n玄\tda\n天地玄\tbabo\n天地\tbabo\n"))
        self.assertEqual((result["mode"], result["compositional"], result["multi"]), ("syllable", 2, 2))
        self.assertEqual(result["syllables"], 3)


class DictionaryChecker(unittest.TestCase):
    def test_valid(self):
        code, output = run("validate_rerimedict.py", FIXTURES / "valid.rerimedict")
        self.assertEqual(code, 0, output)
        self.assertIn("OK 2 entries", output)

    def test_a_table_is_not_a_dictionary(self):
        self.assertEqual(run("validate_rerimedict.py", FIXTURES / "by-syllable.txt")[0], 1)


if __name__ == "__main__":
    unittest.main()
