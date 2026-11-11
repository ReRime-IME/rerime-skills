"""Tests for the two checkers. Run from the repository root:

    python3 -m unittest discover -s tests -v

Every fixture is synthetic: invented codes, no real input scheme and no user data.
tests/test_parity.py holds the comparison with ReRime's own importer.
"""
import importlib.util
import random
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


def run(script, path, *options):
    done = subprocess.run([sys.executable, str(SCRIPTS / script), *options, str(path)], capture_output=True, text=True)
    return done.returncode, done.stdout


def check(text, name="table.txt"):
    """Run the table checker on `text` saved as a file; returns (exit code, output)."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / name
        path.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
        return run("validate_rerime_table.py", path)


def rows(text):
    return table.read(text if isinstance(text, bytes) else text.encode("utf-8"))[0]


def fixture(name, **arguments):
    return table.read_file((FIXTURES / name).read_bytes(), name, **arguments)


def kept(report):
    """(text, code) of every kept row, in candidate order."""
    return [(text, code) for text, code, _ in report["rows"]]


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
        for line, reason in [(6, "code must be letters a-z only"), (7, "no code"), (8, "not a row"),
                             (9, "whole-number weight"), (10, "control, format"), (11, "duplicate"),
                             (12, "command value")]:
            self.assertRegex(output, rf"SKIP line {line}: .*{reason}")
        self.assertIn("ReRime would import 5 rows and skip 7", output)


class TableRules(unittest.TestCase):
    def test_refusals(self):
        for text, reason in [
            (b"", "no rows"),
            ("天\tba\n".encode("gb18030") + b"\xff\n", "not UTF-8, UTF-16 or GB18030"),
            ("天\tba\n", "at least 2"),
            ("天\tb1\n地\tb2\n玄\tda\n", "more invalid rows than valid"),
            ("schema:\n  schema_id: sample\nengine:\n  processors:\n    - speller\n", "scheme or configuration file"),
            (b"Rime::Table/4.0\x00\x00", "compiled or binary dictionary"),
            (b"%PDF-1.7\nabc", "not a text table"),
        ]:
            code, output = check(text)
            self.assertEqual(code, 1, output)
            self.assertIn("ERROR", output)
            self.assertIn(reason, output)

    def test_binary_content_is_named_by_its_extension(self):
        self.assertIn("compiled or binary dictionary", check(b"\x00\x01\x02\xff" * 9, "words.scel")[1])
        self.assertIn("not a text table", check(b"\x01\x00\x02\xff" * 9, "words.pdf")[1])

    def test_caps(self):
        saved = table.MAX_ROWS, table.MAX_BYTES
        try:
            table.MAX_ROWS = 3
            with self.assertRaisesRegex(table.Refusal, "4 rows; the limit is 3"):
                rows("天\tba\n地\tbo\n玄\tda\n黄\tdo\n")
            table.MAX_BYTES = 8
            with self.assertRaisesRegex(table.Refusal, "the limit is 8"):
                rows("天\tba\n地\tbo\n")
        finally:
            table.MAX_ROWS, table.MAX_BYTES = saved

    def test_code_and_text_limits(self):
        self.assertEqual(table.check_code("a" * 96), ("a" * 96, None))
        self.assertEqual(table.check_code("a" * 97)[1], "codeTooLong")
        self.assertEqual(table.check_code("Ba  bo"), ("ba bo", None))
        self.assertEqual(table.check_code("ba-bo")[1], "codeNotLetters")
        self.assertEqual(table.check_text("字" * 80), ("字" * 80, None))
        self.assertEqual(table.check_text("字" * 81)[1], "textTooLong")
        self.assertEqual(table.check_text("\u3000a b "), ("a b", None))
        for bad in ["a\u00a0b", "a\u202eb", "\u2764\ufe0f", "a\x07", "e" + "\u0301" * 5, ""]:
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

    def test_engine_budget(self):
        # Long entries that share no leading codes do not fit ReRime's engine by syllable:
        # the table runs whole word. Long texts need ReRime's exact measurement at import.
        singles = [(chr(0x4E00 + n), "b" + chr(97 + n // 26) + chr(97 + n % 26)) for n in range(200)]
        rng = random.Random(5)
        picks = [[rng.choice(singles) for _ in range(9)] for _ in range(1500)]
        long_words = [("".join(text for text, _ in pick), "".join(code for _, code in pick)) for pick in picks]
        text = "".join(f"{text}\t{code}\n" for text, code in singles + long_words)
        result = table.analyze(rows(text))
        self.assertTrue(result["built"])
        self.assertEqual((result["mode"], result["syllable_budget"]), ("whole", "doesNotFit"))
        self.assertIn("split by syllable the table does not fit", "\n".join(table.describe(result)))
        wide = "".join(f"{chr(0x4E00 + n) * 60}\tzz{chr(97 + n // 26)}{chr(97 + n % 26)}\n" for n in range(300))
        result = table.analyze(rows(wide))
        self.assertEqual((result["mode"], result["budget"]), ("whole", "needsExactCheck"))
        self.assertIn("near the engine's size limit", "\n".join(table.describe(result)))


class ImporterDifferences(unittest.TestCase):
    """What the comparison with ReRime's importer found wrong in the first checker: one
    regression test for each difference."""

    def test_rows_before_a_data_marker_are_not_read(self):
        report = fixture("data-marker.txt")
        self.assertEqual(kept(report), [("天", "bap"), ("天地", "bapbop"), ("地", "bop")])
        self.assertEqual(report["skips"], [])
        self.assertTrue(report["reading"]["usedDataMarker"])
        with self.assertRaisesRegex(table.Refusal, "no rows"):
            rows("天\tba\n地\tbo\n[DATA]\n")

    def test_phrase_lines_on_half_of_the_lines_make_a_phrase_list(self):
        report = table.read_file("ba=1,天\nbo=1,地\n玄\tda\n黄\tdo\n".encode())
        self.assertEqual(report["reading"]["kind"], "phraseList:codePositionPhrase")
        self.assertEqual(kept(report), [("天", "ba"), ("地", "bo")])
        self.assertEqual(report["skips"], [(3, "malformed"), (4, "malformed")])
        self.assertEqual(table.read_file("ba=1,天\nbo=1,地\n玄\tda\n黄\tdo\n宇\tga\n".encode())["reading"]["kind"], "plainTable")

    def test_an_empty_columns_key_resets_the_columns(self):
        report = fixture("rime-columns-reset.dict.yaml")
        self.assertEqual(kept(report), [("天", "bap"), ("地", "bop")])

    def test_rime_header_must_end_within_64_kib(self):
        body = "\n...\nα\tba\nβ\tbo\n"
        inside = table.read_file(("---\nname: sample\n# " + "x" * 65515 + body).encode())
        self.assertEqual(inside["reading"]["kind"], "rimeDictionary")
        with self.assertRaisesRegex(table.Refusal, "more invalid rows than valid"):
            table.read_file(("---\nname: sample\n# " + "x" * 65516 + body).encode())

    def test_text_length_counts_characters_not_code_points(self):
        report = fixture("eighty-characters.txt")
        self.assertEqual(report["skips"], [(3, "textTooLong")])
        self.assertIn(("क्ष" * 80, "bap"), kept(report))
        for text, count in [("क्ष", 1), ("🇨🇳🇨", 2), ("각", 1), ("e\u0301\u0302x", 2), ("👍🏽", 1), ("ൎക", 1),
                            ("क्ःक", 2), ("天地", 2)]:
            self.assertEqual(table.count_characters(text), count, text)

    def test_text_that_starts_like_a_binary_file_is_refused(self):
        with self.assertRaisesRegex(table.Refusal, "not a text table"):
            fixture("signature-prefix.txt")
        with self.assertRaisesRegex(table.Refusal, "compiled or binary dictionary"):
            rows("Rime::a\tba\n天\tbo\n")
        self.assertEqual(len(rows("PKU\tba\nMZT\tbo\n")), 2)   # Short signatures need a NUL nearby.

    def test_chinese_rows_are_counted_as_the_importer_counts_them(self):
        # Compatibility ideographs count as Chinese, and rows are counted before codes are joined.
        self.assertTrue(table.read_file("﨎\tba\n﨏\tbo\n﨑\tda\nα\tdo\nβ\tga\n".encode())["suggestsEntries"])
        self.assertTrue(table.read_file("你好\tni hao\n你好\tnihao\nα\tba\nβ\tbo\n".encode())["suggestsEntries"])
        self.assertFalse(table.read_file("天\tba\nα\tbo\nβ\tda\n".encode())["suggestsEntries"])

    def test_gb18030_follows_the_iphone_decoder(self):
        report = fixture("gb18030-current-standard.txt")
        self.assertEqual(report["reading"]["encoding"], "gb18030")
        self.assertIn(("€", "kat"), kept(report))
        self.assertIn(("︐", "kot"), kept(report))
        self.assertEqual(report["skips"], [])
        with self.assertRaisesRegex(table.Refusal, "not UTF-8, UTF-16 or GB18030"):
            table.read_file("天\tba\n地\tbo\n".encode("gb18030") + b"\x81\x35\xf4\x37\tda\n")


class Formats(unittest.TestCase):
    ROWS = 16

    def test_utf16_and_gb18030(self):
        for name, encoding, mark in [("utf16le-bom.txt", "utf16LittleEndian", True),
                                     ("utf16be-unmarked.txt", "utf16BigEndian", False), ("gb18030.txt", "gb18030", False)]:
            report = fixture(name)
            self.assertEqual((report["reading"]["encoding"], report["reading"]["hadByteOrderMark"]), (encoding, mark))
            self.assertEqual((report["rowCount"], report["skips"], report["summary"]["mode"]), (self.ROWS, [], "syllable"))
        code, output = run("validate_rerime_table.py", FIXTURES / "gb18030.txt")
        self.assertEqual(code, 0, output)
        self.assertIn("NOTE read as GB18030", output)

    def test_encodings_that_are_refused(self):
        for data in [b"\xff\xfe\x00\x00" + "天\tba\n".encode("utf-32-le"), b"\xff\xfe" + "天\tba\n".encode("utf-16-le") + b"\n",
                     b"\xff\xfe\x00\xd8\t\x00a\x00\n\x00", b"\xef\xbb\xbf\xff\tba\n", b"\xaa\xa1\tba\n\xaa\xa2\tbo\n"]:
            with self.assertRaisesRegex(table.Refusal, "not UTF-8, UTF-16 or GB18030"):
                table.read_file(data)

    def test_space_separated(self):
        report = fixture("space-separated.txt")
        self.assertEqual((report["reading"]["separator"], report["reading"]["columnOrder"]), ("whitespace", "textFirst"))
        self.assertEqual((report["rowCount"], report["skips"], report["summary"]["mode"]), (9, [], "syllable"))
        self.assertIn(("玄黄", "dapdop", 7), report["rows"])
        code, output = run("validate_rerime_table.py", FIXTURES / "space-separated.txt")
        self.assertEqual(code, 0, output)
        self.assertIn("space-separated table", output)

    def test_space_separated_code_with_several_words(self):
        report = fixture("space-code-words.txt")
        self.assertEqual(report["reading"]["columnOrder"], "codeFirst")
        self.assertEqual(report["rows"], [("天", "bap", -1), ("填", "bap", -1), ("地", "bop", -1), ("玄", "dap", -1),
                                          ("旋", "dap", -1), ("悬", "dap", -1), ("黄", "dop", 8)])
        # One tab anywhere makes the file tab-separated: the space-separated lines have one column.
        self.assertEqual(table.read_file("天 ba\n地\tbo\n玄\tda\n".encode())["skips"], [(1, "noCode")])

    def test_phrase_lists(self):
        mobile = fixture("phrase-baidu-mobile.ini")
        self.assertEqual(mobile["reading"]["kind"], "phraseList:codePositionPhrase")
        self.assertEqual((mobile["reading"]["encoding"], mobile["rowCount"], mobile["skips"]), ("utf16LittleEndian", self.ROWS, []))
        sogou = fixture("phrase-sogou.ini")
        self.assertEqual(sogou["reading"]["kind"], "phraseList:codeCommaPosition")
        # Within one code the position orders the phrases; multi-line and dynamic phrases are skipped.
        self.assertEqual(kept(sogou), [("填", "bap"), ("天", "bap"), ("地", "bop"), ("宇", "gap")])
        self.assertEqual(sogou["skips"], [(6, "multiLineValue"), (9, "dynamicValue")])
        pc = fixture("phrase-baidu-pc.ini")
        self.assertEqual(pc["reading"]["kind"], "phraseList:positionCode")
        self.assertEqual(kept(pc), [("天", "bap"), ("填", "bap"), ("地", "bop"), ("黄", "dop")])
        self.assertEqual(pc["skips"], [(4, "multiLineValue")])
        code, output = run("validate_rerime_table.py", FIXTURES / "phrase-sogou.ini")
        self.assertEqual(code, 1, output)
        self.assertIn("read as a phrase list (code,position=phrase)", output)
        self.assertIn("SKIP line 6: the phrase continues on other lines", output)

    def test_zip_with_one_table(self):
        report = fixture("one-table.zip")
        self.assertEqual([item["memberName"] for item in report["tables"]], ["sample/sample.dict.yaml"])
        self.assertEqual((report["reading"]["kind"], report["reading"]["importedFiles"]), ("rimeDictionary", 1))
        self.assertEqual((report["rowCount"], report["skips"], report["suggestedName"]), (self.ROWS + 3, [], "sample"))
        code, output = run("validate_rerime_table.py", FIXTURES / "one-table.zip")
        self.assertEqual(code, 0, output)
        self.assertIn("ZIP: read the table sample/sample.dict.yaml", output)
        self.assertIn("1 imported file(s)", output)

    def test_zip_with_several_tables(self):
        report = fixture("several-tables.zip")
        self.assertEqual(report["outcome"], "choose")
        # The dictionary the scheme file names comes first; GBK member names are decoded.
        self.assertEqual([(item["id"], item["memberName"], item["isSchemeMain"]) for item in report["tables"]],
                         [(1, "sample.dict.yaml", True), (0, "other.dict.yaml", False), (3, "示例.txt", False)])
        chosen = fixture("several-tables.zip", table=3)
        self.assertEqual((chosen["reading"]["kind"], chosen["reading"]["encoding"], chosen["rowCount"]),
                         ("plainTable", "gb18030", self.ROWS))
        code, output = run("validate_rerime_table.py", FIXTURES / "several-tables.zip")
        self.assertEqual(code, 0, output)
        self.assertIn("the ZIP holds 3 tables", output)
        self.assertIn("ZIP: read the table sample.dict.yaml", output)
        self.assertIn("names files that are not here", output)
        code, output = run("validate_rerime_table.py", FIXTURES / "several-tables.zip", "--table", "0")
        self.assertIn("ZIP: read the table other.dict.yaml", output)
        with self.assertRaisesRegex(table.Refusal, "no table with that ID"):
            fixture("several-tables.zip", table=2)

    def test_zip_refusals(self):
        with self.assertRaisesRegex(table.Refusal, "leaves the archive"):
            fixture("escaping-path.zip")
        with self.assertRaisesRegex(table.Refusal, "holds no table"):
            fixture("no-table.zip")

    def test_zip_member_bounds(self):
        data = (FIXTURES / "one-table.zip").read_bytes()
        saved = table.MAX_MEMBER_BYTES, table.MAX_ARCHIVE_BYTES, table.MAX_ARCHIVE_MEMBERS, table.MAX_IMPORT_BYTES
        try:
            table.MAX_MEMBER_BYTES = 100
            with self.assertRaisesRegex(table.Refusal, "larger than 100 bytes"):
                table.read_file(data)
            table.MAX_MEMBER_BYTES, table.MAX_IMPORT_BYTES = saved[0], 300
            with self.assertRaisesRegex(table.Refusal, "larger than 300 bytes together"):
                table.read_file(data)
            table.MAX_IMPORT_BYTES, table.MAX_ARCHIVE_MEMBERS = saved[3], 4
            with self.assertRaisesRegex(table.Refusal, "holds 5 files; the limit is 4"):
                table.read_file(data)
            table.MAX_ARCHIVE_MEMBERS, table.MAX_ARCHIVE_BYTES = saved[2], len(data) - 1
            with self.assertRaisesRegex(table.Refusal, "the ZIP is 1,020 bytes"):
                table.read_file(data)
        finally:
            table.MAX_MEMBER_BYTES, table.MAX_ARCHIVE_BYTES, table.MAX_ARCHIVE_MEMBERS, table.MAX_IMPORT_BYTES = saved

    def test_json_report(self):
        code, output = run("validate_rerime_table.py", FIXTURES / "by-syllable.txt", "--json")
        self.assertEqual(code, 0, output)
        self.assertIn('"scheme": "rerime_user_syllable"', output)


class DictionaryChecker(unittest.TestCase):
    def test_valid(self):
        code, output = run("validate_rerimedict.py", FIXTURES / "valid.rerimedict")
        self.assertEqual(code, 0, output)
        self.assertIn("OK 2 entries", output)

    def test_a_table_is_not_a_dictionary(self):
        self.assertEqual(run("validate_rerimedict.py", FIXTURES / "by-syllable.txt")[0], 1)


if __name__ == "__main__":
    unittest.main()
