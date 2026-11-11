#!/usr/bin/env python3
"""Check a table file for ReRime's "Add Input Scheme…" before sending it to iPhone.

    validate_rerime_table.py [--table ID] [--json] FILE

Reads the file the way ReRime's importer does and reports what ReRime would do with it:
the rows it would skip and why, whether it would refuse the file, and how it would run
the table (by syllable or whole word).

What is read, recognised by content and not by the file's name:

- text in UTF-8, UTF-16 (with or without a byte order mark) or GB18030;
- a Rime dictionary (*.dict.yaml), by its header's columns;
- a plain table, tab-separated or space-separated, with the text or the code first,
  an optional weight, and "code word1 word2 …" lines in the space-separated shape;
- a Baidu or Sogou style phrase list ("code=1,phrase", "code,1=phrase", "1,code=phrase");
- a ZIP that holds any of these. Only members named *.dict.yaml, *.yaml, *.txt, *.tsv or
  *.ini are opened, nothing is extracted, and an irregular archive is refused whole.
  When a ZIP holds several tables ReRime asks which one to add; this checker lists them
  and checks the first, which is the one ReRime preselects (--table ID picks another).

Row rules: a code is letters a-z (capitals are lowercased), at most 96, one space allowed
between syllables; a text is 1-80 characters with no control, directional, invisible or
unusual space characters; a weight is 1-10 digits; a line is at most 4,096 bytes. File
rules: at most 16 MiB (a ZIP: 64 MiB, 512 members, 16 MiB per table) and 300,000 rows,
at least 2 rows, and at least as many valid rows as invalid ones.

Prints "SKIP line N" for each row ReRime would leave out and "ERROR" when ReRime would
refuse the file, then the run mode. Exits 0 only when nothing is skipped or refused.
--json prints one machine-readable report instead (used by tests/parity).

Not checked here: whether iOS can draw every character. ReRime skips rows it cannot
draw, so for text beyond ASCII and common Chinese the row count printed here is an
upper bound; a note says so. Characters newer than this Python's Unicode data are
treated as unassigned. A line that starts with "#" is a comment for ReRime: it is not
a row and not a skipped row; a note names such lines when they look like rows.
"""
import codecs
import hashlib
import json
import re
import struct
import sys
import unicodedata
import zlib
from pathlib import Path

MAX_BYTES = 16 * 1024 * 1024
MAX_ROWS = 300_000
MIN_ROWS = 2
MAX_LINE_BYTES = 4096
MAX_HEADER_BYTES = 64 * 1024
MAX_HEADER_LINES = 200
MAX_CODE_LETTERS = 96
MAX_TEXT_CHARACTERS = 80
MAX_WEIGHT_DIGITS = 10
MAX_COMBINING_MARKS = 4
MAX_NAME_CHARACTERS = 40
MAX_SCHEME_NAME = 16    # What the preview's name field holds.
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 512
MAX_MEMBER_BYTES = 16 * 1024 * 1024
MAX_IMPORT_BYTES = 32 * 1024 * 1024
# A table built by syllable runs by syllable only within both bounds.
SYLLABLE_BOUND = 3_500
SPELLING_BOUND = 20_000
# Share of multi-character rows that must be coded as their characters' codes.
SYLLABLE_SHARE_PERCENT = 99
# The personal dictionary's limits: a file within them may be offered as entries.
ENTRY_ROWS = 10_000
ENTRY_BYTES = 2 * 1024 * 1024
# Lines looked at to tell a phrase list or a configuration file from a plain table.
SAMPLE_LINES = 2_000
MAX_PRINTED = 50
SKIPPED_LINES_KEPT = 12

BLANK = b" \t\r"
SPACES = re.compile(rb"[ \t]+")
LETTERS = frozenset(b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
DIGITS = frozenset(b"0123456789")
YAML_KEY_BYTES = LETTERS | DIGITS | frozenset(b"_/@.-\"'")
BIDI = {0x061C, 0x200E, 0x200F, *range(0x202A, 0x202F), *range(0x2066, 0x206A)}
CONTROL_CATEGORIES = {"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"}
MARK_CATEGORIES = {"Mn", "Mc", "Me"}
# Printable ASCII, unified Han and Yi syllables: one character each and nothing to check.
PLAIN_TEXT = re.compile("[\x20-\x7e\u3400-\u4db5\u4e00-\u9fa5\ua000-\ua48c\U00020000-\U0002a6d6]*")
# Characters every iPhone draws: for other text the row count here is an upper bound.
DRAWN_FOR_SURE = re.compile("[\\x20-\\x7e\\u4e00-\\u9fa5]*")
# Blocks where NFC changes nothing (unified Han, Yi); other text is normalized.
NFC_INERT = [(0x4E00, 0x9FFF), (0x3400, 0x4DBF), (0xA000, 0xA4CF), (0x20000, 0x2EBEF)]

COMPILED_MAGICS = [b"Rime::", b"mschxudp", b"\x40\x15\x00\x00\x44\x43\x53\x01", b"Freeime Dictionary",
                   b"\x55\xaa\x88\x81"]
BINARY_MAGICS = [b"%PDF-", b"\x7fELF", b"\x89PNG", b"\xff\xd8\xff", b"GIF8", b"\x00\x01\x00\x00",
                 b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"7z\xbc\xaf", b"SQLite format 3"]
# Short magics that are also plausible text need a NUL nearby.
SHORT_MAGICS = [b"MZ", b"PK", b"OTTO", b"ttcf", b"wOF", b"Rar!", b"\x1f\x8b"]
COMPILED_SUFFIXES = (".bin", ".scel", ".mb", ".def", ".dat", ".lex", ".bdict", ".userdb")
TABLE_SUFFIXES = (b".dict.yaml", b".txt", b".tsv", b".ini", b".yaml")
NAME_SUFFIXES = (".dict.yaml", ".yaml", ".txt", ".tsv", ".ini", ".zip")

SKIP_REASONS = {
    "malformed": "not a row: expected text and code, with an optional whole-number weight",
    "lineTooLong": "line is longer than 4,096 bytes",
    "noCode": "no code",
    "codeNotLetters": "code must be letters a-z only",
    "codeTooLong": "code is longer than 96 letters",
    "textEmpty": "no text",
    "textTooLong": "text is longer than 80 characters",
    "textControlCharacter": "text has a control, format, private-use or unassigned character",
    "textBidiControl": "text has a directional control character",
    "textInvisibleCharacter": "text has an invisible character (such as a variation selector)",
    "textSpaceCharacter": "text has a space character other than a plain or full-width space",
    "textCombiningMarks": "text has more than 4 combining marks in a row",
    "multiLineValue": "the phrase continues on other lines; ReRime skips such phrases",
    "dynamicValue": "the phrase is a dynamic value (#…), not text",
    "specialValue": "text is a command value ($…), not text",
    "duplicate": "duplicate of an earlier row (same text and code)",
}
ARCHIVE_PROBLEMS = {
    "malformed": "it is damaged or not a regular ZIP",
    "zip64": "it uses Zip64",
    "multiDisk": "it is one part of a multi-part archive",
    "overlappingMembers": "two members share the same bytes",
    "localHeaderMismatch": "a member's own header disagrees with the directory",
    "duplicateNames": "two members have the same name, or one has no name",
    "unsafePath": "a member's path is absolute or leaves the archive (..)",
    "unsupportedMethod": "a table in it is compressed by a method other than Deflate",
    "checksumMismatch": "a member does not match its checksum",
    "sizeMismatch": "a member is not the size the archive declares",
}
REFUSALS = {
    "empty": "the file has no rows",
    "fileTooLarge": "file is {bytes:,} bytes; the limit is {limit:,}",
    "tooManyRows": "{rows:,} rows; the limit is {limit:,}",
    "unknownEncoding": "the text is not UTF-8, UTF-16 or GB18030",
    "schemeFile": "this is a scheme or configuration file, not a table (ReRime reads tables only)",
    "compiledDictionary": "this is a compiled or binary dictionary; ReRime needs the text table it was made from",
    "unsupportedFile": "this is not a text table: by its first bytes or its content it is a picture, document, "
                       "program or other binary file",
    "tooFewValidRows": "{invalid:,} rows break a rule and only {valid:,} are valid; ReRime refuses a file with "
                       "more invalid rows than valid ones",
    "tooFewRows": "{rows} valid row; a table needs at least {minimum}",
    "doesNotFitEngine": "the table does not fit ReRime's engine: its entries are too long or share too few "
                        "leading codes",
    "archiveTooLarge": "the ZIP is {bytes:,} bytes; the limit is {limit:,}",
    "archiveTooManyMembers": "the ZIP holds {count:,} files; the limit is {limit:,}",
    "archiveEncrypted": "the ZIP is password-protected",
    "archiveUnsupported": "ReRime does not read this ZIP: {problem_text}",
    "archiveNoTable": "the ZIP holds no table (ReRime opens *.dict.yaml, *.yaml, *.txt, *.tsv and *.ini in it)",
    "archiveMemberTooLarge": "a table in the ZIP is larger than {limit:,} bytes",
    "archiveImportTooLarge": "the table and the files it imports are larger than {limit:,} bytes together",
    "selectionNotFound": "the ZIP has no table with that ID",
}


class Refusal(Exception):
    """ReRime would not import the file at all. `code` is the importer's own name for it."""

    def __init__(self, code, **details):
        self.code, self.details = code, details
        super().__init__(self.sentence())

    def sentence(self):
        details = dict(self.details)
        if "problem" in details:
            details["problem_text"] = ARCHIVE_PROBLEMS[details["problem"]]
        return REFUSALS[self.code].format(**details)

    def report(self):
        return {"refusal": self.code, **self.details}


def _ranges(text):
    """Sorted (low, high) pairs from "1f-2a 30 …" in hexadecimal."""
    pairs = []
    for item in text.split():
        low, _, high = item.partition("-")
        pairs.append((int(low, 16), int(high or low, 16)))
    return pairs


def in_ranges(value, ranges):
    low, high = 0, len(ranges)
    while low < high:
        middle = (low + high) // 2
        if ranges[middle][1] < value:
            low = middle + 1
        else:
            high = middle
    return low < len(ranges) and ranges[low][0] <= value


# Default-ignorable code points and variation selectors: they draw nothing.
INVISIBLE = _ranges("ad 34f 61c 115f-1160 17b4-17b5 180b-180f 200b-200f 202a-202e 2060-206f 3164 fe00-fe0f feff "
                    "ffa0 fff0-fff8 1bca0-1bca3 1d173-1d17a e0000-e0fff")
# Unified ideographs: with U+3007, what makes a row "Chinese" for the personal dictionary.
IDEOGRAPHS = _ranges("3007 3400-4dbf 4e00-9fff fa0e-fa0f fa11 fa13-fa14 fa1f fa21 fa23-fa24 fa27-fa29 20000-2a6df "
                     "2a700-2b81d 2b820-2cead 2ceb0-2ebe0 2ebf0-2ee5d 30000-3134a 31350-33479")
# What Foundation trims as whitespace around a name or a header value.
WHITESPACE = _ranges("9 20 a0 1680 2000-200b 202f 205f 3000")

# How code points group into the characters a person sees (extended grapheme clusters), as
# Swift counts them; ReRime's 80-character limit counts these. Read from Swift's own answers
# by tests/parity. JOINS_PREVIOUS: attaches to the character before it. JOINS_NEXT: attaches
# to the one after it. A consonant, marks with a virama among them, and another consonant
# are one character in the scripts of CONJUNCT_CONSONANT.
CONJUNCT_CONSONANT = _ranges(
    "915-939 958-95f 978-97f 995-9a8 9aa-9b0 9b2 9b6-9b9 9dc-9dd 9df 9f0-9f1 a95-aa8 aaa-ab0 ab2-ab3 "
    "ab5-ab9 af9 b15-b28 b2a-b30 b32-b33 b35-b39 b5c-b5d b5f b71 c15-c28 c2a-c39 c58-c5a d15-d3a "
    "1000-102a 103f 1050-1055 105a-105d 1061 1065-1066 106e-1070 1075-1081 108e 1780-17b3 1a20-1a54 "
    "1b0b-1b0c 1b13-1b33 1b45-1b4c 1b83-1ba0 1bae-1baf 1bbb-1bbd a989-a98b a98f-a9b2 a9e0-a9e4 a9e7-a9ef "
    "a9fa-a9fe aa60-aa6f aa71-aa73 aa7a aa7e-aa7f aae0-aaea abc0-abda 10a00 10a10-10a13 10a15-10a17 "
    "10a19-10a35 11103-11126 11144 11147 11380-11389 1138b 1138e 11390-113b5 11900-11906 11909 "
    "1190c-11913 11915-11916 11918-1192f 11a00 11a0b-11a32 11a50 11a5c-11a83 11f04-11f10 11f12-11f33 ")
JOINS_PREVIOUS = _ranges(
    "300-36f 483-489 591-5bd 5bf 5c1-5c2 5c4-5c5 5c7 610-61a 64b-65f 670 6d6-6dc 6df-6e4 6e7-6e8 6ea-6ed "
    "711 730-74a 7a6-7b0 7eb-7f3 7fd 816-819 81b-823 825-827 829-82d 859-85b 897-89f 8ca-8e1 8e3-903 "
    "93a-93c 93e-94f 951-957 962-963 981-983 9bc 9be-9c4 9c7-9c8 9cb-9cd 9d7 9e2-9e3 9fe a01-a03 a3c "
    "a3e-a42 a47-a48 a4b-a4d a51 a70-a71 a75 a81-a83 abc abe-ac5 ac7-ac9 acb-acd ae2-ae3 afa-aff b01-b03 "
    "b3c b3e-b44 b47-b48 b4b-b4d b55-b57 b62-b63 b82 bbe-bc2 bc6-bc8 bca-bcd bd7 c00-c04 c3c c3e-c44 "
    "c46-c48 c4a-c4d c55-c56 c62-c63 c81-c83 cbc cbe-cc4 cc6-cc8 cca-ccd cd5-cd6 ce2-ce3 cf3 d00-d03 "
    "d3b-d3c d3e-d44 d46-d48 d4a-d4d d57 d62-d63 d81-d83 dca dcf-dd4 dd6 dd8-ddf df2-df3 e31 e33-e3a "
    "e47-e4e eb1 eb3-ebc ec8-ece f18-f19 f35 f37 f39 f3e-f3f f71-f84 f86-f87 f8d-f97 f99-fbc fc6 "
    "102d-1037 1039-103e 1056-1059 105e-1060 1071-1074 1082 1084-1086 108d 109d 135d-135f 1712-1715 "
    "1732-1734 1752-1753 1772-1773 17b4-17d3 17dd 180b-180d 180f 1885-1886 18a9 1920-192b 1930-193b "
    "1a17-1a1b 1a55-1a5e 1a60 1a62 1a65-1a7c 1a7f 1ab0-1add 1ae0-1aeb 1b00-1b04 1b34-1b44 1b6b-1b73 "
    "1b80-1b82 1ba1-1bad 1be6-1bf3 1c24-1c37 1cd0-1cd2 1cd4-1ce8 1ced 1cf4 1cf7-1cf9 1dc0-1dff 200c-200d "
    "20d0-20f0 2cef-2cf1 2d7f 2de0-2dff 302a-302f 3099-309a a66f-a672 a674-a67d a69e-a69f a6f0-a6f1 a802 "
    "a806 a80b a823-a827 a82c a880-a881 a8b4-a8c5 a8e0-a8f1 a8ff a926-a92d a947-a953 a980-a983 a9b3-a9c0 "
    "a9e5 aa29-aa36 aa43 aa4c-aa4d aa7c aab0 aab2-aab4 aab7-aab8 aabe-aabf aac1 aaeb-aaef aaf5-aaf6 "
    "abe3-abea abec-abed fb1e fe00-fe0f fe20-fe2f ff9e-ff9f 101fd 102e0 10376-1037a 10a01-10a03 "
    "10a05-10a06 10a0c-10a0f 10a38-10a3a 10a3f 10ae5-10ae6 10d24-10d27 10d69-10d6d 10eab-10eac "
    "10efa-10eff 10f46-10f50 10f82-10f85 11000-11002 11038-11046 11070 11073-11074 1107f-11082 "
    "110b0-110ba 110c2 11100-11102 11127-11134 11145-11146 11173 11180-11182 111b3-111c0 111c9-111cc "
    "111ce-111cf 1122c-11237 1123e 11241 112df-112ea 11300-11303 1133b-1133c 1133e-11344 11347-11348 "
    "1134b-1134d 11357 11362-11363 11366-1136c 11370-11374 113b8-113c0 113c2 113c5 113c7-113ca "
    "113cc-113d0 113d2 113e1-113e2 11435-11446 1145e 114b0-114c3 115af-115b5 115b8-115c0 115dc-115dd "
    "11630-11640 116ab-116b7 1171d-1171f 11722-1172b 1182c-1183a 11930-11935 11937-11938 1193b-1193e "
    "11940 11942-11943 119d1-119d7 119da-119e0 119e4 11a01-11a0a 11a33-11a39 11a3b-11a3e 11a47 "
    "11a51-11a5b 11a8a-11a99 11b60-11b67 11c2f-11c36 11c38-11c3f 11c92-11ca7 11ca9-11cb6 11d31-11d36 "
    "11d3a 11d3c-11d3d 11d3f-11d45 11d47 11d8a-11d8e 11d90-11d91 11d93-11d97 11ef3-11ef6 11f00-11f01 "
    "11f03 11f34-11f3a 11f3e-11f42 11f5a 13440 13447-13455 1611e-1612f 16af0-16af4 16b30-16b36 16f4f "
    "16f51-16f87 16f8f-16f92 16fe4 16ff0-16ff1 1bc9d-1bc9e 1cf00-1cf2d 1cf30-1cf46 1d165-1d169 "
    "1d16d-1d172 1d17b-1d182 1d185-1d18b 1d1aa-1d1ad 1d242-1d244 1da00-1da36 1da3b-1da6c 1da75 1da84 "
    "1da9b-1da9f 1daa1-1daaf 1e000-1e006 1e008-1e018 1e01b-1e021 1e023-1e024 1e026-1e02a 1e08f "
    "1e130-1e136 1e2ae 1e2ec-1e2ef 1e4ec-1e4ef 1e5ee-1e5ef 1e6e3 1e6e6 1e6ee-1e6ef 1e6f5 1e8d0-1e8d6 "
    "1e944-1e94a 1f3fb-1f3ff e0020-e007f e0100-e01ef ")
JOINS_NEXT = _ranges(
    "600-605 6dd 70f 890-891 8e2 d4e 110bd 110cd 111c2-111c3 113d1 1193f 11941 11a84-11a89 11d46 11f02 ")
CONJUNCT_EXTEND = _ranges(
    "300-36f 483-489 591-5bd 5bf 5c1-5c2 5c4-5c5 5c7 610-61a 64b-65f 670 6d6-6dc 6df-6e4 6e7-6e8 6ea-6ed "
    "711 730-74a 7a6-7b0 7eb-7f3 7fd 816-819 81b-823 825-827 829-82d 859-85b 897-89f 8ca-8e1 8e3-902 93a "
    "93c 941-948 94d 951-957 962-963 981 9bc 9be 9c1-9c4 9cd 9d7 9e2-9e3 9fe a01-a02 a3c a41-a42 a47-a48 "
    "a4b-a4d a51 a70-a71 a75 a81-a82 abc ac1-ac5 ac7-ac8 acd ae2-ae3 afa-aff b01 b3c b3e-b3f b41-b44 b4d "
    "b55-b57 b62-b63 b82 bbe bc0 bcd bd7 c00 c04 c3c c3e-c40 c46-c48 c4a-c4d c55-c56 c62-c63 c81 cbc "
    "cbf-cc0 cc2 cc6-cc8 cca-ccd cd5-cd6 ce2-ce3 d00-d01 d3b-d3c d3e d41-d44 d4d d57 d62-d63 d81 dca dcf "
    "dd2-dd4 dd6 ddf e31 e34-e3a e47-e4e eb1 eb4-ebc ec8-ece f18-f19 f35 f37 f39 f71-f7e f80-f84 f86-f87 "
    "f8d-f97 f99-fbc fc6 102d-1030 1032-1037 1039-103a 103d-103e 1058-1059 105e-1060 1071-1074 1082 "
    "1085-1086 108d 109d 135d-135f 1712-1715 1732-1734 1752-1753 1772-1773 17b4-17b5 17b7-17bd 17c6 "
    "17c9-17d3 17dd 180b-180d 180f 1885-1886 18a9 1920-1922 1927-1928 1932 1939-193b 1a17-1a18 1a1b 1a56 "
    "1a58-1a5e 1a60 1a62 1a65-1a6c 1a73-1a7c 1a7f 1ab0-1add 1ae0-1aeb 1b00-1b03 1b34-1b3d 1b42-1b44 "
    "1b6b-1b73 1b80-1b81 1ba2-1ba5 1ba8-1bad 1be6 1be8-1be9 1bed 1bef-1bf3 1c2c-1c33 1c36-1c37 1cd0-1cd2 "
    "1cd4-1ce0 1ce2-1ce8 1ced 1cf4 1cf8-1cf9 1dc0-1dff 200d 20d0-20f0 2cef-2cf1 2d7f 2de0-2dff 302a-302f "
    "3099-309a a66f-a672 a674-a67d a69e-a69f a6f0-a6f1 a802 a806 a80b a825-a826 a82c a8c4-a8c5 a8e0-a8f1 "
    "a8ff a926-a92d a947-a951 a953 a980-a982 a9b3 a9b6-a9b9 a9bc-a9bd a9c0 a9e5 aa29-aa2e aa31-aa32 "
    "aa35-aa36 aa43 aa4c aa7c aab0 aab2-aab4 aab7-aab8 aabe-aabf aac1 aaec-aaed aaf6 abe5 abe8 abed fb1e "
    "fe00-fe0f fe20-fe2f ff9e-ff9f 101fd 102e0 10376-1037a 10a01-10a03 10a05-10a06 10a0c-10a0f "
    "10a38-10a3a 10a3f 10ae5-10ae6 10d24-10d27 10d69-10d6d 10eab-10eac 10efa-10eff 10f46-10f50 "
    "10f82-10f85 11001 11038-11046 11070 11073-11074 1107f-11081 110b3-110b6 110b9-110ba 110c2 "
    "11100-11102 11127-1112b 1112d-11134 11173 11180-11181 111b6-111be 111c0 111c9-111cc 111cf "
    "1122f-11231 11234-11237 1123e 11241 112df 112e3-112ea 11300-11301 1133b-1133c 1133e 11340 1134d "
    "11357 11366-1136c 11370-11374 113b8 113bb-113c0 113c2 113c5 113c7-113c9 113ce-113d0 113d2 "
    "113e1-113e2 11438-1143f 11442-11444 11446 1145e 114b0 114b3-114b8 114ba 114bd 114bf-114c0 "
    "114c2-114c3 115af 115b2-115b5 115bc-115bd 115bf-115c0 115dc-115dd 11633-1163a 1163d 1163f-11640 "
    "116ab 116ad 116b0-116b7 1171d 1171f 11722-11725 11727-1172b 1182f-11837 11839-1183a 11930 "
    "1193b-1193e 11943 119d4-119d7 119da-119db 119e0 11a01-11a0a 11a33-11a38 11a3b-11a3e 11a47 "
    "11a51-11a56 11a59-11a5b 11a8a-11a96 11a98-11a99 11b60 11b62-11b64 11b66 11c30-11c36 11c38-11c3d "
    "11c3f 11c92-11ca7 11caa-11cb0 11cb2-11cb3 11cb5-11cb6 11d31-11d36 11d3a 11d3c-11d3d 11d3f-11d45 "
    "11d47 11d90-11d91 11d95 11d97 11ef3-11ef4 11f00-11f01 11f36-11f3a 11f40-11f42 11f5a 13440 "
    "13447-13455 1611e-16129 1612d-1612f 16af0-16af4 16b30-16b36 16f4f 16f8f-16f92 16fe4 16ff0-16ff1 "
    "1bc9d-1bc9e 1cf00-1cf2d 1cf30-1cf46 1d165-1d169 1d16d-1d172 1d17b-1d182 1d185-1d18b 1d1aa-1d1ad "
    "1d242-1d244 1da00-1da36 1da3b-1da6c 1da75 1da84 1da9b-1da9f 1daa1-1daaf 1e000-1e006 1e008-1e018 "
    "1e01b-1e021 1e023-1e024 1e026-1e02a 1e08f 1e130-1e136 1e2ae 1e2ec-1e2ef 1e4ec-1e4ef 1e5ee-1e5ef "
    "1e6e3 1e6e6 1e6ee-1e6ef 1e6f5 1e8d0-1e8d6 1e944-1e94a 1f3fb-1f3ff e0020-e007f e0100-e01ef ")
CONJUNCT_LINKERS = {0x094D, 0x09CD, 0x0ACD, 0x0B4D, 0x0C4D, 0x0D4D}


def _hangul(value):
    """L, V, T, LV or LVT for a Hangul jamo or syllable, else None."""
    if 0x1100 <= value <= 0x115F or 0xA960 <= value <= 0xA97C:
        return "L"
    if 0x1160 <= value <= 0x11A7 or 0xD7B0 <= value <= 0xD7C6:
        return "V"
    if 0x11A8 <= value <= 0x11FF or 0xD7CB <= value <= 0xD7FB:
        return "T"
    if 0xAC00 <= value <= 0xD7A3:
        return "LV" if (value - 0xAC00) % 28 == 0 else "LVT"
    return None


def count_characters(text):
    """Characters as Swift's String counts them, for text without U+200D (the zero-width
    joiner, which ReRime refuses in a text or a name before it counts)."""
    if PLAIN_TEXT.fullmatch(text):
        return len(text)
    count = 0
    previous = None
    flags = 0          # Regional indicators in a row before this one.
    conjunct = 0       # 1: after a consonant; 2: a virama has followed it.
    for character in text:
        value = ord(character)
        joined = False
        if previous is not None:
            before = _hangul(previous)
            after = _hangul(value) if before else None
            if in_ranges(value, JOINS_PREVIOUS) or in_ranges(previous, JOINS_NEXT):
                joined = True
            elif before == "L" and after in ("L", "V", "LV", "LVT"):
                joined = True
            elif before in ("LV", "V") and after in ("V", "T"):
                joined = True
            elif before in ("LVT", "T") and after == "T":
                joined = True
            elif conjunct == 2 and in_ranges(value, CONJUNCT_CONSONANT):
                joined = True
            elif 0x1F1E6 <= value <= 0x1F1FF and flags % 2 == 1:
                joined = True
        if not joined:
            count += 1
        flags = flags + 1 if 0x1F1E6 <= value <= 0x1F1FF else 0
        if in_ranges(value, CONJUNCT_CONSONANT):
            conjunct = 1
        elif conjunct and in_ranges(value, CONJUNCT_EXTEND):
            if value in CONJUNCT_LINKERS:
                conjunct = 2
        else:
            conjunct = 0
        previous = value
    return count


def is_hidden(character):
    """Control-like or invisible: not allowed in a name, replaced in a ZIP member's name."""
    return unicodedata.category(character) in CONTROL_CATEGORIES or in_ranges(ord(character), INVISIBLE)


def strip_whitespace(text):
    start, end = 0, len(text)
    while start < end and in_ranges(ord(text[start]), WHITESPACE):
        start += 1
    while end > start and in_ranges(ord(text[end - 1]), WHITESPACE):
        end -= 1
    return text[start:end]


def display_name(name):
    """The name ReRime suggests for the scheme, or None when the source's name is unusable."""
    if name is None:
        return None
    name = strip_whitespace(name)
    if not name or count_characters(name) > MAX_NAME_CHARACTERS or any(is_hidden(c) for c in name):
        return None
    return name


def base_name(path):
    """The last path component without its table extension."""
    parts = [part for part in path.split("/") if part]
    name = parts[-1] if parts else ""
    for suffix in NAME_SUFFIXES:
        if name.lower().endswith(suffix):
            return name[:len(name) - len(suffix)]
    return name


# --- Encodings ----------------------------------------------------------------------------------


def _unmarked_utf16(data):
    """True (little endian) or False (big endian) when tabs, line feeds, "=" or "," stand
    as UTF-16 code units; None when the bytes do not look like UTF-16."""
    if len(data) < 2 or len(data) % 2 or 0 not in data:
        return None
    first, second = data[0::2], data[1::2]
    little = big = 0
    for separator in b"\t\n=,":
        start = -1
        while (start := first.find(separator, start + 1)) >= 0:
            little += second[start] == 0
        start = -1
        while (start := second.find(separator, start + 1)) >= 0:
            big += first[start] == 0
    if (little == 0 and big == 0) or little == big:
        return None
    return little > big


def _utf16(data, little):
    if len(data) % 2:
        raise Refusal("unknownEncoding")
    try:
        return data.decode("utf-16-le" if little else "utf-16-be").encode("utf-8")
    except UnicodeError:
        raise Refusal("unknownEncoding") from None


# Where the iPhone's GB18030 decoder and Python's differ (found by tests/parity): it reads
# these two-byte codes as the characters of the current standard, where Python gives the
# private-use code points of the 2005 edition (and A3 A0 as a full-width space); it reads
# the byte 0x80 as the euro sign; and it refuses the four-byte code 81 35 F4 37.
_GB18030_CURRENT = {"a6d9": 0xFE10, "a6da": 0xFE12, "a6db": 0xFE11, "a6dc": 0xFE13, "a6dd": 0xFE14, "a6de": 0xFE15,
                    "a6df": 0xFE16, "a6ec": 0xFE17, "a6ed": 0xFE18, "a6f3": 0xFE19, "a8bc": 0x1E3F, "fe59": 0x9FB4,
                    "fe61": 0x9FB5, "fe66": 0x9FB6, "fe67": 0x9FB7, "fe6d": 0x9FB8, "fe7e": 0x9FB9, "fe90": 0x9FBA,
                    "fea0": 0x9FBB, "a3a0": 0x3000}
_GB18030_FIX = {ord(bytes.fromhex(code).decode("gb18030")): value for code, value in _GB18030_CURRENT.items()}
_GB18030_REFUSED = None if 0x1E3F in _GB18030_FIX else "\u1e3f"


def _gb18030_error(error):
    data, start = error.object, error.start
    if data[start] == 0x80:
        return "\u20ac", start + 1
    raise error


codecs.register_error("rerime-gb18030", _gb18030_error)


def _gb18030(data):
    try:
        text = data.decode("gb18030", "rerime-gb18030")
    except UnicodeError:
        return None
    if _GB18030_REFUSED and _GB18030_REFUSED in text:
        return None
    text = text.translate(_GB18030_FIX)
    private = beyond = 0
    for character in text:
        value = ord(character)
        if value >= 0x80:
            beyond += 1
            if value == 0xFFFD:
                return None
            if 0xE000 <= value <= 0xF8FF or value >= 0xF0000:
                private += 1
    # Text that is mostly private-use characters is another legacy encoding misread.
    return text.encode("utf-8") if private * 100 <= beyond else None


def _is_utf8(data):
    try:
        data.decode("utf-8")
        return True
    except UnicodeError:
        return False


def decode_bytes(data):
    """(UTF-8 bytes, encoding, had a byte order mark), in ReRime's detection order: byte order
    mark, UTF-16 without a mark by its separators, strict UTF-8, strict GB18030."""
    if data[:4] in (b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff"):
        raise Refusal("unknownEncoding")  # UTF-32 is not read.
    if data[:3] == b"\xef\xbb\xbf":
        if not _is_utf8(data[3:]):
            raise Refusal("unknownEncoding")
        return data[3:], "utf8", True
    if data[:2] == b"\xff\xfe":
        return _utf16(data[2:], True), "utf16LittleEndian", True
    if data[:2] == b"\xfe\xff":
        return _utf16(data[2:], False), "utf16BigEndian", True
    little = _unmarked_utf16(data)
    if little is not None:
        try:
            return _utf16(data, little), "utf16LittleEndian" if little else "utf16BigEndian", False
        except Refusal:
            pass
    if _is_utf8(data):
        return data, "utf8", False
    text = _gb18030(data)
    if text is not None:
        return text, "gb18030", False
    raise Refusal("unknownEncoding")


def _binary_refusal(file_name):
    name = (file_name or "").lower()
    return Refusal("compiledDictionary" if name.endswith(COMPILED_SUFFIXES) else "unsupportedFile")


def decode_source(data, file_name):
    """One file or ZIP member as validated UTF-8; binary files are refused by what they are."""
    if any(data.startswith(magic) for magic in COMPILED_MAGICS):
        raise Refusal("compiledDictionary")
    if any(data.startswith(magic) for magic in BINARY_MAGICS):
        raise Refusal("unsupportedFile")
    if any(data.startswith(magic) for magic in SHORT_MAGICS) and 0 in data[:512]:
        raise Refusal("unsupportedFile")
    try:
        decoded = decode_bytes(data)
    except Refusal:
        marked = data[:3] == b"\xef\xbb\xbf" or data[:2] in (b"\xff\xfe", b"\xfe\xff") or data[:4] == b"\x00\x00\xfe\xff"
        if 0 in data and not marked:
            raise _binary_refusal(file_name) from None
        raise
    if 0 in decoded[0]:
        raise _binary_refusal(file_name)
    if not decoded[0].strip(b" \t\r\n"):
        raise Refusal("empty")
    return decoded


def whole_lines(head):
    """The first bytes of a longer ZIP member, cut back to whole lines of its own encoding."""
    marked = True if head[:2] == b"\xff\xfe" else False if head[:2] == b"\xfe\xff" else None
    little = marked if marked is not None else _unmarked_utf16(head[:len(head) - len(head) % 2])
    if little is not None:
        head = head[:len(head) - len(head) % 2]
        newline = b"\n\x00" if little else b"\x00\n"
        index = len(head) - 2
        while index >= (0 if marked is None else 2):
            if head[index:index + 2] == newline:
                return head[:index + 2]
            index -= 2
        if len(head) >= 2:
            unit = int.from_bytes(head[-2:], "little" if little else "big")
            if 0xD800 <= unit <= 0xDBFF:
                head = head[:-2]
        return head
    line_end = head.rfind(b"\n")
    if line_end >= 0:
        return head[:line_end + 1]
    cut, tail = len(head), 0
    while cut > 0 and tail < 3 and head[cut - 1] & 0xC0 == 0x80:
        cut -= 1
        tail += 1
    if cut > 0 and head[cut - 1] >= 0xC0:
        needed = 3 if head[cut - 1] >= 0xF0 else 2 if head[cut - 1] >= 0xE0 else 1
        if tail < needed:
            return head[:cut - 1]
    return head


# --- Recognising what a text is -----------------------------------------------------------------


def split_lines(buffer):
    """Lines as ReRime numbers them: ended by a line feed only."""
    lines = buffer.split(b"\n")
    if lines[-1] == b"":
        lines.pop()
    return lines


def all_digits(field):
    return bool(field) and all(byte in DIGITS for byte in field)


def looks_like_code(field, spaces):
    return bool(field) and all(byte in LETTERS or (spaces and byte == 0x20) for byte in field)


def yaml_scalar(raw):
    """A plain YAML scalar on one line: quotes and a trailing " # comment" removed."""
    text = raw.strip(BLANK).decode("utf-8")
    comment = text.find(" #")
    if comment >= 0:
        text = text[:comment]
    text = strip_whitespace(text)
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1]
    return text


def flow_list(rest):
    """["a", "b"] for "[a, b]" on one line; None when the value is not such a list."""
    if len(rest) < 2 or rest[:1] != b"[" or b"]" not in rest:
        return None
    items = [yaml_scalar(item) for item in rest[1:rest.index(b"]")].split(b",")]
    return [item for item in items if item]


def rime_header(lines):
    """The header of a Rime dictionary, or None when the text is not one: a line "..."
    within the first 200 lines and 64 KiB, and a name before it. Only the column order,
    import_tables, the name and sort are taken from it."""
    header = {"name": None, "text": 0, "code": 1, "weight": 2, "imports": [], "sort_original": False, "body": 0}
    columns = list_key = None
    offset, found = 0, False
    for index, raw in enumerate(lines):
        if offset >= MAX_HEADER_BYTES or index >= MAX_HEADER_LINES:
            break
        offset += len(raw) + 1
        line = raw.rstrip(BLANK)
        if line == b"...":
            header["body"], found = index + 1, True
            break
        if not line or line[0] == 0x23:
            continue
        if line[0] in (0x20, 0x2D):  # An indented line or a block list item.
            item = line.strip(BLANK)
            if list_key and item[:2] == b"- ":
                value = yaml_scalar(item[2:])
                if list_key == b"columns":
                    columns = (columns or []) + [value]
                else:
                    header["imports"].append(value)
            continue
        list_key = None
        colon = line.find(b":")
        if colon < 0:
            continue
        key, rest = line[:colon], line[colon + 1:].strip(BLANK)
        if key == b"name":
            header["name"] = yaml_scalar(rest)
        elif key == b"sort":
            header["sort_original"] = yaml_scalar(rest) == "original"
        elif key in (b"columns", b"import_tables"):
            values = flow_list(rest)
            if not rest:
                list_key = key
            if key == b"columns":
                columns = values
            else:
                header["imports"] = values or []
    if not found or not header["name"]:
        return None
    if columns is not None:
        for name in ("text", "code", "weight"):
            header[name] = columns.index(name) if name in columns else None
    header["imports"] = [name for name in header["imports"] if name and name != header["name"]]
    return header


def scheme_main_dictionary(lines):
    """The dictionary a scheme file names: "dictionary:" inside its top-level "translator:"."""
    in_translator = False
    for raw in lines:
        line = raw.rstrip(BLANK)
        if not line or line[0] == 0x23:
            continue
        if line[0] != 0x20:
            in_translator = line == b"translator:"
            continue
        item = line.strip(BLANK)
        colon = item.find(b":")
        if in_translator and colon >= 0 and item[:colon] == b"dictionary":
            return yaml_scalar(item[colon + 1:]) or None
    return None


def phrase_grammar(line):
    """Which of the three one-line phrase grammars a line is written in, or None."""
    equals = line.find(b"=")
    if equals <= 0:
        return None
    left = line[:equals]
    comma = left.find(b",")
    if comma >= 0:
        if all_digits(left[comma + 1:]) and comma > 0:
            return "codeCommaPosition"   # code,position=phrase (Sogou)
        if all_digits(left[:comma]) and comma + 1 < equals:
            return "positionCode"        # position,code=phrase (Baidu PC)
        return None
    right = line[equals + 1:]
    comma = right.find(b",")
    if comma >= 0 and all_digits(right[:comma]):
        return "codePositionPhrase"      # code=position,phrase (Baidu mobile, QQ, iFlytek)
    return None


def looks_like_yaml(line):
    if line == b"---":
        return True
    if line[0] == 0x2D:
        return line[1:2] == b" "
    for index, byte in enumerate(line):
        if byte == 0x3A:
            return index > 0 and (index + 1 == len(line) or line[index + 1] == 0x20)
        if byte not in YAML_KEY_BYTES:
            return False
    return False


GRAMMARS = ("codePositionPhrase", "codeCommaPosition", "positionCode")


def classify(lines):
    """("rime", header), ("phrase", grammar), ("configuration", None) or ("plain", None)."""
    header = rime_header(lines)
    if header:
        return "rime", header
    data_lines = yaml_lines = tab_lines = 0
    grammar = dict.fromkeys(GRAMMARS, 0)
    for raw in lines:
        line = raw.strip(BLANK)
        if not line or line[0] in (0x23, 0x3B):          # "#" and ";" comments
            continue
        if line[0] == 0x5B and line[-1] == 0x5D:         # [group]
            continue
        data_lines += 1
        found = phrase_grammar(line)
        if found:
            grammar[found] += 1
        elif looks_like_yaml(line):
            yaml_lines += 1
        tab_lines += b"\t" in line
        if data_lines >= SAMPLE_LINES:
            break
    best = max(GRAMMARS, key=lambda name: grammar[name])
    if grammar[best] and grammar[best] * 2 >= data_lines:
        # Two grammars on exactly half of the lines each: ReRime takes either one.
        return ("phrase-tie" if list(grammar.values()).count(grammar[best]) > 1 else "phrase"), best
    if data_lines and yaml_lines * 10 >= data_lines * 6 and tab_lines * 2 < data_lines:
        return "configuration", None
    return "plain", None


# --- Rows ---------------------------------------------------------------------------------------


def check_code(field):
    """(code, None) with one space between syllables, else (None, the skip reason)."""
    if isinstance(field, str):
        field = field.encode("utf-8")
    field = field.strip(BLANK)
    if not field:
        return None, "noCode"
    if not all(byte in LETTERS or byte == 0x20 for byte in field):
        return None, "codeNotLetters"
    code = b" ".join(field.lower().split())
    if len(code) - code.count(b" ") > min(MAX_CODE_LETTERS, 128):
        return None, "codeTooLong"
    return code.decode("ascii"), None


def check_text(field):
    """(text, None) for a text ReRime keeps, else (None, the skip reason)."""
    if isinstance(field, str):
        field = field.encode("utf-8")
    field = field.strip(BLANK)
    while field[:3] == b"\xe3\x80\x80":         # U+3000 at either end is trimmed like a space.
        field = field[3:].strip(BLANK)
    while field[-3:] == b"\xe3\x80\x80":
        field = field[:-3].strip(BLANK)
    if not field:
        return None, "textEmpty"
    text = field.decode("utf-8")
    if PLAIN_TEXT.fullmatch(text):
        return (text, None) if len(text) <= MAX_TEXT_CHARACTERS else (None, "textTooLong")
    marks = 0
    normalize = False
    for character in text:
        value = ord(character)
        if value < 0x80:
            if value < 0x20 or value == 0x7F:
                return None, "textControlCharacter"
            marks = 0
            continue
        if value in BIDI:
            return None, "textBidiControl"
        category = unicodedata.category(character)
        if category in CONTROL_CATEGORIES:
            return None, "textControlCharacter"
        if category == "Zs":
            if value != 0x3000:
                return None, "textSpaceCharacter"
            marks = 0
        elif category in MARK_CATEGORIES:
            marks += 1
            if marks > MAX_COMBINING_MARKS:
                return None, "textCombiningMarks"
        else:
            marks = 0
        if in_ranges(value, INVISIBLE):
            return None, "textInvisibleCharacter"
        if not in_ranges(value, NFC_INERT):
            normalize = True
    if normalize:
        text = unicodedata.normalize("NFC", text)
    if count_characters(text) > MAX_TEXT_CHARACTERS:
        return None, "textTooLong"
    return text, None


class Collector:
    """The rows ReRime keeps and the ones it skips, with the reason for each."""

    def __init__(self):
        self.rows = []          # (code bytes, position, weight or -1, text, line)
        self.seen = set()
        self.skips = []         # (line, reason)
        self.overflow = 0
        self.han = 0
        self.long_weights = []
        self.notes = []
        self.comment_rows = []  # Lines that start with "#" and otherwise look like a row.

    def skip(self, line, reason):
        self.skips.append((line, reason))

    def accept(self, line, text_field, code_field, weight_field=None, position=0):
        code, reason = check_code(code_field)
        if reason:
            return self.skip(line, reason)
        text, reason = check_text(text_field)
        if reason:
            return self.skip(line, reason)
        weight = -1
        if weight_field is not None:
            digits = weight_field.strip(BLANK)
            if all_digits(digits):
                if len(digits) <= MAX_WEIGHT_DIGITS:
                    weight = int(digits)
                else:
                    self.long_weights.append(line)
        key = (text, code)
        if key in self.seen:
            return self.skip(line, "duplicate")
        if len(self.rows) >= MAX_ROWS:
            self.overflow += 1
        else:
            self.seen.add(key)
            self.rows.append((code, position, weight, text, line))
        if all(in_ranges(ord(character), IDEOGRAPHS) for character in text):
            self.han += 1

    def counts(self):
        duplicates = sum(reason == "duplicate" for _, reason in self.skips)
        return len(self.rows) + self.overflow + duplicates, len(self.skips) - duplicates


def read_rime_body(lines, header, collector):
    """Rows split on tabs only; "#" starts a comment until a "# no comment" line."""
    comments = True
    text_at, code_at, weight_at = header["text"], header["code"], header["weight"]
    for number, raw in enumerate(lines[header["body"]:], start=header["body"] + 1):
        line = raw.rstrip(BLANK)
        if not line:
            continue
        if comments and line[0] == 0x23:
            comments = line != b"# no comment"
            fields = line.split(b"\t")
            if (text_at is not None and code_at is not None and max(text_at, code_at) < len(fields)
                    and looks_like_code(fields[code_at].strip(BLANK), True)):
                collector.comment_rows.append(number)
            continue
        if len(line) > MAX_LINE_BYTES:
            collector.skip(number, "lineTooLong")
            continue
        fields = line.split(b"\t")
        if text_at is None or text_at >= len(fields):
            collector.skip(number, "malformed")
        elif code_at is None or code_at >= len(fields) or not fields[code_at].strip(BLANK):
            collector.skip(number, "noCode")
        else:
            weight = fields[weight_at] if weight_at is not None and weight_at < len(fields) else None
            collector.accept(number, fields[text_at], fields[code_at], weight)


def read_phrase_list(lines, grammar, collector):
    """The three one-line grammars with [group] lines and ";" comments. A phrase that
    continues on following lines, or starts with "#" (a dynamic value), is skipped."""
    pending = None          # One row is held back so a continuation line can still cancel it.
    continuing = False

    def flush():
        nonlocal pending
        if pending:
            collector.accept(*pending)
        pending = None

    for number, raw in enumerate(lines, start=1):
        line = raw.strip(BLANK)
        if not line:
            continue
        if line[0] == 0x5C:                               # "\": the row before it is multi-line.
            if pending:
                collector.skip(pending[0], "multiLineValue")
                pending = None
            continue
        if line[0] == 0x3B:
            continue
        if line[0] == 0x5B and line[-1] == 0x5D:
            flush()
            continuing = False
            continue
        if len(line) > MAX_LINE_BYTES:
            flush()
            collector.skip(number, "lineTooLong")
            continue
        if phrase_grammar(line) != grammar:
            if not continuing:
                flush()
                collector.skip(number, "malformed")
            continue
        flush()
        continuing = False
        equals = line.index(b"=")
        if grammar == "codePositionPhrase":
            comma = line.index(b",", equals + 1)
            code, position, phrase = line[:equals], line[equals + 1:comma], line[comma + 1:]
        else:
            comma = line.index(b",")
            first, second, phrase = line[:comma], line[comma + 1:equals], line[equals + 1:]
            code, position = (first, second) if grammar == "codeCommaPosition" else (second, first)
        value = phrase.strip(BLANK)
        if not value:
            collector.skip(number, "multiLineValue")
            continuing = True
        elif value[0] == 0x23:
            collector.skip(number, "dynamicValue")
        else:
            rank = int(position) if len(position) <= 9 else 2**31 - 1
            pending = (number, value, code, None, rank)
    flush()


def is_data_marker(line):
    return line == "[数据]".encode("utf-8") or (len(line) == 6 and line[0] == 0x5B and line[5] == 0x5D
                                              and bytes(byte | 0x20 for byte in line[1:5]) == b"data")


def plain_layout(lines):
    """Decided once per file: tab-separated when any data line has a tab, otherwise split on
    spaces; the column that is all letters is the code. When both columns are letters on
    every line the text is taken to come first."""
    layout = {"body": 0, "marker": False}
    for index, raw in enumerate(lines):
        if is_data_marker(raw.strip(BLANK)):
            layout["body"], layout["marker"] = index + 1, True
            break
    body = lines[layout["body"]:]
    tabs = False
    for raw in body:
        line = raw.rstrip(BLANK)
        if line and line[0] != 0x23 and b"\t" in line:
            tabs = True
            break
    code_first = text_first = 0
    for raw in body:
        line = raw.strip(BLANK)
        if not line or line[0] == 0x23:
            continue
        fields = line.split(b"\t") if tabs else SPACES.split(line)
        if len(fields) >= 2:
            left = looks_like_code(fields[0].strip(BLANK), tabs)
            right = looks_like_code(fields[1].strip(BLANK), tabs)
            code_first += left and not right
            text_first += right and not left
    layout["whitespace"] = not tabs
    layout["code_first"] = code_first > text_first
    layout["assumed"] = code_first == 0 and text_first == 0
    return layout


def read_plain_table(lines, layout, collector):
    """"text code [weight]" or "code text [weight]"; a space-separated code-first line with
    more words is one row per word. "#" starts a comment line."""
    whitespace = layout["whitespace"]

    def emit(number, text, code, weight):
        value = text.strip(BLANK)
        # Command values of other input methods ($ddcmd(…), $[…], $X…) are not text.
        if len(value) >= 2 and value[0] == 0x24 and (value[1] in LETTERS or value[1] == 0x5B):
            collector.skip(number, "specialValue")
        else:
            collector.accept(number, text, code, weight)

    for number, raw in enumerate(lines[layout["body"]:], start=layout["body"] + 1):
        line = raw.strip(BLANK)
        if not line:
            continue
        if line[0] == 0x23:
            # A comment. When it has the shape of a row, the person may have meant a word.
            fields = SPACES.split(line) if whitespace else line.split(b"\t")
            if len(fields) == 2 or (len(fields) == 3 and all_digits(fields[2].strip(BLANK))):
                if looks_like_code(fields[0 if layout["code_first"] else 1].strip(BLANK), not whitespace):
                    collector.comment_rows.append(number)
            continue
        if len(line) > MAX_LINE_BYTES:
            collector.skip(number, "lineTooLong")
            continue
        fields = SPACES.split(line) if whitespace else line.split(b"\t")
        if len(fields) < 2:
            collector.skip(number, "malformed" if whitespace else "noCode")
            continue
        has_weight = len(fields) == 3 and all_digits(fields[2].strip(BLANK))
        if not layout["code_first"]:
            if len(fields) == 2 or has_weight:
                emit(number, fields[0], fields[1], fields[2] if has_weight else None)
            else:
                collector.skip(number, "malformed")
        elif len(fields) == 2 or has_weight:
            emit(number, fields[1], fields[0], fields[2] if has_weight else None)
        elif whitespace:
            for word in fields[1:]:
                emit(number, word, fields[0], None)
        else:
            collector.skip(number, "malformed")


def read_rows(buffer, collector, reading, is_import=False):
    """Classifies and reads one decoded text. Returns the Rime header when it is one."""
    lines = split_lines(buffer)
    kind, detail = classify(lines)
    if kind == "phrase-tie":
        kind = "phrase"
        collector.notes.append("two phrase-list forms are used on half of the lines each; ReRime reads the file as "
                               "either one and skips the other half, so the result can differ from this report")
    if kind == "rime":
        if not is_import:
            reading["kind"], reading["keptFileOrder"] = "rimeDictionary", detail["sort_original"]
        read_rime_body(lines, detail, collector)
        return detail
    if kind == "configuration" or is_import:
        raise Refusal("schemeFile")
    if kind == "phrase":
        reading["kind"] = "phraseList:" + detail
        read_phrase_list(lines, detail, collector)
    else:
        layout = plain_layout(lines)
        reading.update(kind="plainTable", separator="whitespace" if layout["whitespace"] else "tab",
                       columnOrder="codeFirst" if layout["code_first"] else "textFirst",
                       columnOrderAssumed=layout["assumed"], usedDataMarker=layout["marker"])
        read_plain_table(lines, layout, collector)
    return None


def new_reading(kind, encoding, bom):
    return {"kind": kind, "encoding": encoding, "hadByteOrderMark": bom, "columnOrder": "textFirst",
            "columnOrderAssumed": False, "separator": "tab", "usedDataMarker": False, "keptFileOrder": False,
            "importedFiles": 0, "missingImports": []}


def canonical_table(rows):
    """ReRime's stored table: text, code, weight (empty when none), rows in candidate order."""
    return "".join(f"{text}\t{code}\t{weight if weight >= 0 else ''}\n" for text, code, weight in rows).encode("utf-8")


def finish(collector, reading, name, source_bytes, tables, selected):
    """The file-level rules, the candidate order and the analysis: the report for a table."""
    skips = sorted(collector.skips)
    valid, invalid = collector.counts()
    try:
        if valid + invalid == 0:
            raise Refusal("empty")
        if valid == 0 or valid < invalid:
            raise Refusal("tooFewValidRows", valid=valid, invalid=invalid)
        if collector.overflow:
            raise Refusal("tooManyRows", rows=len(collector.rows) + collector.overflow, limit=MAX_ROWS)
        # Candidate order: by code, then by position (phrase lists) or weight, highest first
        # (unless the source keeps file order), then by file order.
        if reading["keptFileOrder"]:
            ordered = sorted(collector.rows, key=lambda row: (row[0], row[1]))
        else:
            ordered = sorted(collector.rows, key=lambda row: (row[0], row[1], -row[2]))
        rows = [(text, code, weight) for code, _, weight, text, _ in ordered]
        count = len(rows)
        too_large = count > ENTRY_ROWS or source_bytes > ENTRY_BYTES
        suggests_entries = not too_large and collector.han * 2 >= count
        if count < MIN_ROWS and not suggests_entries:
            raise Refusal("tooFewRows", rows=count, minimum=MIN_ROWS)
        analysis = analyze(join_rows(rows)) if count >= MIN_ROWS else None
        can_be_table = bool(analysis and analysis["mode"])
        if not can_be_table and not suggests_entries:
            raise Refusal("doesNotFitEngine")
    except Refusal as refusal:
        refusal.skips = skips
        raise
    canonical = canonical_table(rows)
    skipped, skipped_lines = {}, {}
    for line, reason in collector.skips:
        skipped[reason] = skipped.get(reason, 0) + 1
        if len(skipped_lines.setdefault(reason, [])) < SKIPPED_LINES_KEPT:
            skipped_lines[reason].append(line)
    if can_be_table:
        door = {"route": "schemePreview"}
    else:
        door = {"route": "refuse", "refusal": "tooFewRows", "rows": count, "minimum": MIN_ROWS}
    return {
        "outcome": "table", "reading": reading, "rowCount": count, "skipped": skipped, "skippedLines": skipped_lines,
        "canonicalSHA256": hashlib.sha256(canonical).hexdigest(), "canonicalBytes": len(canonical),
        "suggestedName": display_name(name), "suggestsEntries": suggests_entries, "tooLargeForEntries": too_large,
        "canBeTable": can_be_table, "scheme": analysis["scheme"] if analysis else None,
        "schemeNeedsExactCheck": bool(analysis and analysis["budget"] == "needsExactCheck"),
        "tables": tables, "selectedTable": selected, "analysis": analysis and analysis["report"], "door": door,
        # Beyond what ReRime's preview holds: every skipped row, the rows, and notes for the person.
        "rows": rows, "skips": skips, "summary": analysis, "longWeights": collector.long_weights,
        "notes": collector.notes, "commentRows": collector.comment_rows,
    }


# --- ZIP ----------------------------------------------------------------------------------------


def _problem(name):
    return Refusal("archiveUnsupported", problem=name)


class Archive:
    """A strict reader of a ZIP's members. It reads, never extracts: members are found in the
    central directory and inflated in memory with the bytes counted while inflating. Irregular
    archives are refused whole, because ZIP readers disagree on them."""

    def __init__(self, data):
        if len(data) > MAX_ARCHIVE_BYTES:
            raise Refusal("archiveTooLarge", bytes=len(data), limit=MAX_ARCHIVE_BYTES)
        self.data = data
        self.members = self._directory()

    def _u16(self, offset):
        if offset < 0 or offset + 2 > len(self.data):
            raise _problem("malformed")
        return struct.unpack_from("<H", self.data, offset)[0]

    def _u32(self, offset):
        if offset < 0 or offset + 4 > len(self.data):
            raise _problem("malformed")
        return struct.unpack_from("<I", self.data, offset)[0]

    def _slice(self, offset, length):
        if offset < 0 or offset + length > len(self.data):
            raise _problem("malformed")
        return self.data[offset:offset + length]

    def _end_record(self):
        count = len(self.data)
        if count < 22:
            raise _problem("malformed")
        lowest = max(0, count - 22 - 0xFFFF)
        offset = count - 22
        while offset >= lowest:
            offset = self.data.rfind(b"PK\x05\x06", lowest, offset + 4)
            if offset < 0:
                break
            if self._u16(offset + 20) == count - offset - 22:
                return offset
            offset -= 1
        raise _problem("malformed")

    def _directory(self):
        end = self._end_record()
        if self._u16(end + 4) or self._u16(end + 6):
            raise _problem("multiDisk")
        total = self._u16(end + 10)
        if self._u16(end + 8) != total:
            raise _problem("multiDisk")
        size, start = self._u32(end + 12), self._u32(end + 16)
        if total == 0xFFFF or size == 0xFFFFFFFF or start == 0xFFFFFFFF:
            raise _problem("zip64")
        if end >= 20 and self._u32(end - 20) == 0x07064B50:
            raise _problem("zip64")
        if total > MAX_ARCHIVE_MEMBERS:
            raise Refusal("archiveTooManyMembers", count=total, limit=MAX_ARCHIVE_MEMBERS)
        if start + size != end:      # Nothing hides between the directory and the end record.
            raise _problem("malformed")
        members, names, offset = [], set(), start
        for index in range(total):
            if self._u32(offset) != 0x02014B50:
                raise _problem("malformed")
            flags, method = self._u16(offset + 8), self._u16(offset + 10)
            crc, packed, declared = self._u32(offset + 16), self._u32(offset + 20), self._u32(offset + 24)
            name_length, extra_length, comment_length = (self._u16(offset + 28), self._u16(offset + 30),
                                                         self._u16(offset + 32))
            if self._u16(offset + 34):
                raise _problem("multiDisk")
            local = self._u32(offset + 42)
            if 0xFFFFFFFF in (packed, declared, local):
                raise _problem("zip64")
            raw = self._slice(offset + 46, name_length)
            if not raw or raw in names:
                raise _problem("duplicateNames")
            names.add(raw)
            unicode_path = self._extra(self._slice(offset + 46 + name_length, extra_length), raw)
            name = self._name(raw, bool(flags & 0x0800), unicode_path)
            parts = name.split("/")
            if name.startswith("/") or (len(parts[0]) == 2 and parts[0].endswith(":")) or ".." in parts:
                raise _problem("unsafePath")
            data_start = self._local(local, flags, method, crc, packed, declared, raw, start)
            is_directory = raw.endswith(b"/")
            members.append({
                "index": index, "name": name, "method": method, "encrypted": bool(flags & 0x2041), "crc": crc,
                "declared": declared, "start": data_start, "end": data_start + packed,
                "candidate": not is_directory and self._looks_like_table(raw) and not self._housekeeping(name),
            })
            offset += 46 + name_length + extra_length + comment_length
        if offset != end:
            raise _problem("malformed")
        previous = 0
        for member in sorted(members, key=lambda member: member["start"]):
            if member["start"] < previous:       # Many names, one compressed body: a bomb.
                raise _problem("overlappingMembers")
            previous = max(previous, member["end"])
        return members

    @staticmethod
    def _extra(extra, raw):
        """The Unicode Path (0x7075) name when present and matching; Zip64 is refused."""
        unicode_path, offset = None, 0
        while offset + 4 <= len(extra):
            field, length = struct.unpack_from("<HH", extra, offset)
            start = offset + 4
            if start + length > len(extra):
                raise _problem("malformed")
            if field == 0x0001:
                raise _problem("zip64")
            if field == 0x7075 and length >= 5 and extra[start] == 1:
                if struct.unpack_from("<I", extra, start + 1)[0] == zlib.crc32(raw):
                    unicode_path = extra[start + 5:start + length]
            offset = start + length
        return unicode_path

    @staticmethod
    def _name(raw, flagged_utf8, unicode_path):
        """Decoded by the Unicode Path field, strict UTF-8, then GB18030. Shown only."""
        if not flagged_utf8 and unicode_path is not None and _is_utf8(unicode_path):
            name = unicode_path.decode("utf-8")
        elif _is_utf8(raw):
            name = raw.decode("utf-8")
        else:
            try:
                text, encoding, _ = decode_bytes(raw)
            except Refusal:
                text, encoding = None, None
            name = text.decode("utf-8") if encoding == "gb18030" else raw.decode("utf-8", "replace")
        return "".join("/" if c == "\\" else "\ufffd" if is_hidden(c) else c for c in name)

    def _local(self, offset, flags, method, crc, packed, declared, raw, directory):
        if self._u32(offset) != 0x04034B50:
            raise _problem("localHeaderMismatch")
        if self._u16(offset + 6) != flags or self._u16(offset + 8) != method:
            raise _problem("localHeaderMismatch")
        name_length, extra_length = self._u16(offset + 26), self._u16(offset + 28)
        if self._slice(offset + 30, name_length) != raw:
            raise _problem("localHeaderMismatch")
        if not flags & 0x0008:       # No data descriptor: the local sizes repeat the directory.
            if (self._u32(offset + 14), self._u32(offset + 18), self._u32(offset + 22)) != (crc, packed, declared):
                raise _problem("localHeaderMismatch")
        start = offset + 30 + name_length + extra_length
        if start + packed > directory:
            raise _problem("malformed")
        return start

    @staticmethod
    def _looks_like_table(raw):
        lowered = bytes(byte + 0x20 if 0x41 <= byte <= 0x5A else byte for byte in raw)
        parts = [part for part in lowered.split(b"/") if part]
        if not parts or b"__macosx" in parts or parts[-1].startswith(b"._") or parts[-1] == b".ds_store":
            return False
        return any(len(parts[-1]) > len(suffix) and parts[-1].endswith(suffix) for suffix in TABLE_SUFFIXES)

    @staticmethod
    def _housekeeping(name):
        parts = [part for part in name.lower().split("/") if part]
        return not parts or "__macosx" in parts or parts[-1].startswith("._") or parts[-1] == ".ds_store"

    def _inflate(self, member, limit, stop_after=None):
        if member["encrypted"]:
            raise Refusal("archiveEncrypted")
        packed = self.data[member["start"]:member["end"]]
        if member["method"] == 0:
            if stop_after is not None:
                return packed[:stop_after]
            if len(packed) > limit:
                raise Refusal("archiveMemberTooLarge", limit=limit)
            return packed
        if member["method"] != 8:
            raise _problem("unsupportedMethod")
        # Raw Deflate, the output counted as it is produced: declared sizes are never trusted.
        inflater = zlib.decompressobj(-zlib.MAX_WBITS)
        output = bytearray()
        while True:
            try:
                chunk = inflater.decompress(packed, 64 * 1024)
            except zlib.error:
                raise _problem("malformed") from None
            output += chunk
            if stop_after is not None and len(output) >= stop_after:
                return bytes(output[:stop_after])
            if len(output) > limit:
                raise Refusal("archiveMemberTooLarge", limit=limit)
            if inflater.eof:
                if inflater.unused_data:
                    raise _problem("malformed")
                return bytes(output)
            packed = inflater.unconsumed_tail
            if not chunk and not packed:
                raise _problem("malformed")

    def read(self, member, limit):
        """The whole member, at most `limit` bytes, with its size and CRC-32 checked."""
        output = self._inflate(member, limit)
        if len(output) != member["declared"]:
            raise _problem("sizeMismatch")
        if zlib.crc32(output) != member["crc"]:
            raise _problem("checksumMismatch")
        return output

    def read_prefix(self, member, count):
        """The first bytes of a member, for recognition."""
        return self._inflate(member, float("inf"), count)


def _head_refusal(buffer):
    """None when the head of a ZIP member reads as a table, else why it is not one: what
    makes a .txt in a scheme package a table and a read-me or a conversion list not one."""
    collector = Collector()
    try:
        read_rows(buffer, collector, new_reading("plainTable", "utf8", False))
    except Refusal as refusal:
        return refusal
    valid, invalid = collector.counts()
    if valid + invalid == 0:
        return Refusal("empty")
    return None if valid > 0 and valid >= invalid else Refusal("tooFewValidRows", valid=valid, invalid=invalid)


def _imported_member(name, owner, candidates):
    """<name>.dict.yaml beside the importing dictionary, else at the archive root."""
    folder = "/".join(owner["member"]["name"].split("/")[:-1])
    paths = [(folder + "/" if folder else "") + name + ".dict.yaml", name + ".dict.yaml"]
    for candidate in candidates:
        if (candidate["table"]["kind"] == "rimeDictionary" and candidate["member"] is not owner["member"]
                and candidate["member"]["name"] in paths):
            return candidate
    return None


def read_archive(data, choice):
    archive = Archive(data)
    candidates, main_dictionaries, not_tables = [], set(), []
    saw_encrypted = saw_unsupported = False
    looked_at = 0
    for member in archive.members:
        if not member["candidate"]:
            continue
        looked_at += 1
        if member["encrypted"]:
            saw_encrypted = True
            continue
        if member["method"] not in (0, 8):
            saw_unsupported = True
            continue
        # Recognition reads only the head of a member; the chosen one is read whole.
        head = archive.read_prefix(member, MAX_HEADER_BYTES)
        if len(head) == MAX_HEADER_BYTES:
            head = whole_lines(head)
        try:
            buffer, _, _ = decode_source(head, member["name"])
        except Refusal as refusal:
            not_tables.append(refusal)
            continue
        lines = split_lines(buffer)
        kind, detail = classify(lines)
        kind = "phrase" if kind == "phrase-tie" else kind
        imports, name = [], base_name(member["name"])
        if kind == "configuration":
            main = scheme_main_dictionary(lines)
            if main:
                main_dictionaries.add(main)
            not_tables.append(Refusal("schemeFile"))
            continue
        if kind == "rime":
            kind_label, imports = "rimeDictionary", detail["imports"]
            name = detail["name"] or name
        else:
            refusal = _head_refusal(buffer)
            if refusal:
                not_tables.append(refusal)
                continue
            kind_label = "phraseList:" + detail if kind == "phrase" else "plainTable"
        table = {"id": member["index"], "memberName": member["name"], "suggestedName": name, "kind": kind_label,
                 "declaredBytes": member["declared"], "importedFiles": 0, "isSchemeMain": False}
        candidates.append({"member": member, "table": table, "imports": imports})
    # A dictionary another one imports is a part, not a table of its own.
    parts = set()
    for candidate in candidates:
        found = [part for part in (_imported_member(name, candidate, candidates) for name in candidate["imports"])
                 if part]
        candidate["table"]["importedFiles"] = len(found)
        candidate["table"]["isSchemeMain"] = candidate["table"]["suggestedName"] in main_dictionaries
        parts.update(part["member"]["index"] for part in found)
    tables = sorted((candidate for candidate in candidates if candidate["member"]["index"] not in parts),
                    key=lambda c: (not c["table"]["isSchemeMain"], c["table"]["kind"] != "rimeDictionary",
                                   c["table"]["memberName"]))
    if not tables:
        if saw_encrypted:
            raise Refusal("archiveEncrypted")
        if saw_unsupported:
            raise _problem("unsupportedMethod")
        if looked_at == 1 and not_tables:
            raise not_tables[0]     # The only table-looking file: its own reason, not "no table".
        raise Refusal("archiveNoTable")
    listed = [candidate["table"] for candidate in tables]
    if choice is not None:
        chosen = next((candidate for candidate in tables if candidate["table"]["id"] == choice), None)
        if chosen is None:
            raise Refusal("selectionNotFound")
    elif len(tables) == 1:
        chosen = tables[0]
    else:
        return {"outcome": "choose", "tables": listed, "door": {"route": "schemePreview"}}

    remaining = MAX_IMPORT_BYTES

    def whole(member):
        nonlocal remaining
        content = archive.read(member, min(MAX_MEMBER_BYTES, remaining))
        remaining -= len(content)
        return decode_source(content, member["name"])

    collector = Collector()
    try:
        buffer, encoding, bom = whole(chosen["member"])
    except Refusal as refusal:
        if refusal.code == "archiveMemberTooLarge" and refusal.details["limit"] < MAX_MEMBER_BYTES:
            raise Refusal("archiveImportTooLarge", limit=MAX_IMPORT_BYTES) from None
        raise
    reading = new_reading(chosen["table"]["kind"], encoding, bom)
    header = read_rows(buffer, collector, reading)
    # import_tables, one level, inside the same ZIP only.
    for name in (header or {}).get("imports", []):
        part = _imported_member(name, chosen, candidates)
        if part is None:
            reading["missingImports"].append(name)
            continue
        try:
            buffer, _, _ = whole(part["member"])
        except Refusal as refusal:
            if refusal.code == "archiveMemberTooLarge":
                raise Refusal("archiveImportTooLarge", limit=MAX_IMPORT_BYTES) from None
            raise
        read_rows(buffer, collector, reading, is_import=True)
        reading["importedFiles"] += 1
    name = (header or {}).get("name") or chosen["table"]["suggestedName"]
    return finish(collector, reading, name, chosen["member"]["declared"], listed, chosen["table"]["id"])


def read_file(data, file_name=None, table=None):
    """What ReRime's importer decides about a file's bytes: a report for a table, or for a
    ZIP with several tables (outcome "choose"); raises Refusal for a file it would not import."""
    if not data:
        raise Refusal("empty")
    if data[:4] == b"PK\x03\x04":
        return read_archive(data, table)
    if len(data) > MAX_BYTES:
        raise Refusal("fileTooLarge", bytes=len(data), limit=MAX_BYTES)
    buffer, encoding, bom = decode_source(data, file_name)
    collector = Collector()
    reading = new_reading("plainTable", encoding, bom)
    header = read_rows(buffer, collector, reading)
    if header:
        reading["missingImports"] = header["imports"]
    name = header["name"] if header else base_name(file_name) if file_name is not None else None
    return finish(collector, reading, name, len(data), [], None)


PERSON_KEYS = ("rows", "skips", "summary", "longWeights", "notes", "commentRows")


def report_json(data, file_name=None, table=None):
    """The report in the shape tests/parity compares with ReRime's importer."""
    try:
        report = read_file(data, file_name, table)
    except Refusal as refusal:
        return {"outcome": "refused", **refusal.report(), "door": {"route": "refuse", **refusal.report()}}
    return {key: value for key, value in report.items() if key not in PERSON_KEYS}


def read(data):
    """Rows ReRime would keep (text, code without spaces, weight or -1) in candidate order,
    the skipped rows as (line, reason) and the report."""
    report = read_file(data)
    return join_rows(report["rows"]), report["skips"], report


# --- How ReRime runs the table ------------------------------------------------------------------


def join_rows(rows):
    """Spaces between syllables are not used to split a code; rows equal without them merge."""
    joined, seen = [], set()
    for text, code, weight in rows:
        code = code.replace(" ", "")
        if (text, code) not in seen:
            seen.add((text, code))
            joined.append((text, code, weight))
    return joined


def split_code(text, code, codes):
    """The row's code as the codes of its leading characters, or None.

    Characters without a one-character row of their own take no code. The code must be
    exactly the joined codes of the first k coded characters, k >= 1; the first cover wins.
    Returns (the cover, the codes of every coded character)."""
    coded = [codes[character] for character in text if character in codes]
    if not coded:
        return None, coded
    taken, failed = [], set()

    def walk(index, at):
        if at == len(code):
            return index >= 1
        if index == len(coded) or (index, at) in failed:
            return False
        for option in coded[index]:
            if code.startswith(option, at):
                taken.append(option)
                if walk(index + 1, at + len(option)):
                    return True
                taken.pop()
        failed.add((index, at))
        return False

    return (taken if walk(0, 0) else None), coded


def optional_finals(codes):
    """Final letters a syllable may be typed without, read from the one-character codes.

    A letter qualifies when at least 5% of the codes (and at least ten) end in it, at least
    90% of those are never the start of a code one letter longer, and for at least half of
    them the same stem also exists with another qualifying letter (as tone letters do)."""
    ending, extended = {}, set()
    for code in codes:
        if len(code) > 1:
            ending.setdefault(code[-1], []).append(code)
            extended.add(code[:-1])
    found = {letter for letter, items in ending.items()
             if len(items) >= max(10, len(codes) // 20)
             and sum(code not in extended for code in items) * 10 >= 9 * len(items)}
    while True:
        kept = {letter for letter in found
                if 2 * sum(any(code[:-1] + other in codes for other in found if other != letter)
                           for code in ending[letter]) >= len(ending[letter])}
        if kept == found:
            return "".join(sorted(found))
        found = kept


class IndexCounter:
    """Bytes of the compiled index for rows given as code units (librime's table layout)."""

    def __init__(self):
        self.ids = {}
        self.second_heads, self.second_nodes = set(), set()
        self.third_heads, self.third_nodes, self.tail_heads = set(), set(), set()
        self.long = self.short = self.extra = self.entries = 0

    def add(self, units):
        self.entries += 1
        unit = [self.ids.setdefault(name, len(self.ids)) for name in units]
        if len(unit) >= 2:
            self.second_heads.add(unit[0])
            self.second_nodes.add((unit[0], unit[1]))
        if len(unit) >= 3:
            self.third_heads.add((unit[0], unit[1]))
            self.third_nodes.add((unit[0], unit[1], unit[2]))
        if len(unit) > 3:
            self.tail_heads.add((unit[0], unit[1], unit[2]))
            self.long += 1
            self.extra += len(unit) - 3
        else:
            self.short += 1

    @property
    def bytes(self):
        count = len(self.ids)
        return (68 + 4 + 4 * count + 4 + 12 * count
                + 4 * len(self.second_heads) + 16 * len(self.second_nodes)
                + 4 * len(self.third_heads) + 16 * len(self.third_nodes)
                + 4 * len(self.tail_heads) + 16 * self.long + 4 * self.extra + 8 * self.short)


def build_budget(index_bytes, text_bytes, syllables, entries):
    """Whether the compiled table stays within the engine's own size estimate for it: "fits",
    "needsExactCheck" (ReRime measures it at import) or "doesNotFit"."""
    estimate = 4096 + 32 * syllables + 64 * entries
    bound = index_bytes + int(1.2 * text_bytes) + 4096
    state = "fits" if bound <= estimate else "needsExactCheck" if index_bytes + 4096 <= estimate else "doesNotFit"
    return {"entries": entries, "syllables": syllables, "indexBytes": index_bytes, "textBytes": text_bytes,
            "estimateBytes": estimate, "boundBytes": bound, "state": state}


def _engine_digest(lines):
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()


def analyze(rows):
    """What the rows (text, code without spaces, weight) say about how the table is coded,
    and the run mode ReRime picks."""
    codes = {}
    once, repeated = set(), set()
    for text, code, _ in rows:
        if text in once:
            repeated.add(text)
        once.add(text)
        if len(text) == 1 and code not in codes.setdefault(text, []):
            codes[text].append(code)
    multi = all_characters = leading = otherwise = longest_code = 0
    index, seen, per_code = IndexCounter(), set(), {}
    syllable_lines = []
    for text, code, weight in rows:
        per_code[code] = per_code.get(code, 0) + 1
        longest_code = max(longest_code, len(code))
        cover, coded = split_code(text, code, codes)
        if cover is None:
            units = [code]
        else:
            # A table that codes only the head of a long entry: the rest take their first code.
            units = cover + [options[0] for options in coded[len(cover):]]
        merged = False
        if text in repeated:
            key = (text, " ".join(units))
            merged = key in seen
            seen.add(key)
        if not merged:
            index.add(units)
            syllable_lines.append(f"{text}\t{' '.join(units)}\t{weight if weight >= 0 else ''}\n")
        if len(text) > 1:
            multi += 1
            if cover is None:
                otherwise += 1
            elif len(cover) == sum(character in codes for character in text):
                all_characters += 1
            else:
                leading += 1
    syllable_codes = {code for options in codes.values() for code in options}
    longest = max(map(len, syllable_codes), default=0)
    finals = optional_finals(syllable_codes)
    built = multi > 0 and (all_characters + leading) * 100 >= SYLLABLE_SHARE_PERCENT * multi
    text_bytes = sum(len(text.encode("utf-8")) + 1 for text, _, _ in rows)
    syllables = spellings = 0
    syllable_budget = None
    if built:
        syllables = len(index.ids)
        # Each syllable is spelled by itself and by every shorter prefix, up to the longest
        # one-character code; a longer unit ending in an optional letter has one more.
        spellings = sum(min(len(unit), longest) + (len(unit) > longest and unit[-1] in finals) for unit in index.ids)
        syllable_budget = build_budget(index.bytes, text_bytes + sum(len(unit) + 1 for unit in index.ids),
                                       len(index.ids), index.entries)
    distinct = len(per_code)
    whole_budget = build_budget(68 + 4 + 4 * distinct + 4 + 12 * distinct + 8 * len(rows),
                                text_bytes + sum(len(code) + 1 for code in per_code), distinct, len(rows))
    within = syllables <= SYLLABLE_BOUND and spellings <= SPELLING_BOUND
    if built and within and syllable_budget["state"] != "doesNotFit":
        mode, scheme, budget = "syllable", "rerime_user_syllable", syllable_budget["state"]
    elif whole_budget["state"] != "doesNotFit":
        mode, scheme, budget = "whole", "rerime_user_table", whole_budget["state"]
    else:
        mode, scheme, budget = None, None, "doesNotFit"
    report = {
        "rows": len(rows), "charactersWithOwnRow": len(codes),
        "charactersWithSeveralCodes": sum(len(options) > 1 for options in codes.values()),
        "multiCharacterRows": multi, "codedAsAllCharacters": all_characters, "codedAsLeadingCharacters": leading,
        "codedOtherwise": otherwise, "bySyllable": built, "longestCode": longest_code, "distinctCodes": distinct,
        "mostRowsOnOneCode": max(per_code.values(), default=0), "longestSyllableCode": longest,
        "optionalFinalLetters": finals, "spellings": spellings, "syllables": syllables,
        "bySyllableBudget": syllable_budget, "wholeWordBudget": whole_budget,
        "wholeWordRowsSHA256": _engine_digest(f"{text}\t{code}\t{weight if weight >= 0 else ''}\n"
                                              for text, code, weight in rows),
        "bySyllableRowsSHA256": _engine_digest(syllable_lines),
    }
    return {"rows": len(rows), "multi": multi, "compositional": all_characters + leading, "otherwise": otherwise,
            "built": built, "finals": finals, "syllables": syllables, "spellings": spellings, "mode": mode,
            "scheme": scheme, "budget": budget,
            "syllable_budget": syllable_budget["state"] if syllable_budget else "doesNotFit", "report": report}


def describe(result):
    """The run mode and its reasons, as lines to print."""
    multi, compositional = result["multi"], result["compositional"]
    counts = (f"{result['syllables']:,} syllables (at most {SYLLABLE_BOUND:,}), "
              f"{result['spellings']:,} spellings (at most {SPELLING_BOUND:,})")
    share = (f"{compositional:,} of {multi:,} multi-character rows are coded as the joined codes of their "
             f"characters (ReRime needs {SYLLABLE_SHARE_PERCENT}%)")
    if result["mode"] == "syllable":
        finals = ", ".join(result["finals"])
        lines = ["Run mode: by syllable", f"  {share}", f"  {counts}",
                 f"  optional trailing letters: {finals} (a syllable can be typed without them)" if finals
                 else "  optional trailing letters: none found"]
    else:
        lines = ["Run mode: whole word"]
        if multi == 0:
            lines.append("  the table has no multi-character rows, so nothing shows how words are coded")
        elif not result["built"]:
            lines.append(f"  only {share}")
        else:
            lines.append(f"  {share}, but the table is over a bound: {counts}"
                         if result["syllables"] > SYLLABLE_BOUND or result["spellings"] > SPELLING_BOUND
                         else f"  {share}, but split by syllable the table does not fit ReRime's engine")
    if result["budget"] == "needsExactCheck":
        lines.append("  NOTE the table is near the engine's size limit; ReRime measures it at import and may "
                     + ("run it whole word or refuse it" if result["mode"] == "syllable" else "refuse it"))
    return lines


# --- Command line -------------------------------------------------------------------------------

ENCODINGS = {"utf16LittleEndian": "UTF-16 (little endian)", "utf16BigEndian": "UTF-16 (big endian)",
             "gb18030": "GB18030"}
PHRASE_LISTS = {"codePositionPhrase": "code=position,phrase", "codeCommaPosition": "code,position=phrase",
                "positionCode": "position,code=phrase"}


def reading_notes(report):
    """How ReRime reads the file, as notes to pass on."""
    reading, notes = report["reading"], []
    if report["selectedTable"] is not None:
        member = next(table for table in report["tables"] if table["id"] == report["selectedTable"])
        notes.append(f"ZIP: read the table {member['memberName']}; other files in the ZIP are ignored")
    if reading["encoding"] != "utf8":
        notes.append(f"read as {ENCODINGS[reading['encoding']]}"
                     + ("" if reading["hadByteOrderMark"] else " (no byte order mark; recognised by its content)"))
    elif reading["hadByteOrderMark"]:
        notes.append("the file starts with a byte order mark; ReRime reads it, but plain UTF-8 is safer")
    kind = reading["kind"]
    if kind == "rimeDictionary":
        notes.append("read as a Rime dictionary" + ("; candidates of one code keep the file's order (sort: original)"
                                                    if reading["keptFileOrder"] else ""))
        if reading["importedFiles"]:
            notes.append(f"import_tables: {reading['importedFiles']} imported file(s) read from the same ZIP")
        if reading["missingImports"]:
            notes.append("import_tables names files that are not here, so their rows are missing: "
                         + ", ".join(reading["missingImports"])
                         + (" (import_tables is followed only inside a ZIP)" if report["selectedTable"] is None else ""))
    elif kind.startswith("phraseList"):
        notes.append(f"read as a phrase list ({PHRASE_LISTS[kind.split(':')[1]]}); within one code the phrases "
                     "keep their positions")
    else:
        if reading["usedDataMarker"]:
            notes.append("rows before the [DATA] line are not read")
        if reading["separator"] == "whitespace":
            notes.append("read as a space-separated table (no line has a tab)")
        if reading["columnOrder"] == "codeFirst":
            notes.append("read with the code in the first column")
        elif reading["columnOrderAssumed"]:
            notes.append("both columns are letters on every line, so the first column is read as the text")
    notes += report["notes"]
    for line in report["longWeights"][:5]:
        notes.append(f"line {line}: a weight of more than {MAX_WEIGHT_DIGITS} digits is ignored; the row is kept "
                     "without a weight")
    if report["commentRows"]:
        lines = ", ".join(map(str, report["commentRows"][:10])) + (", …" if len(report["commentRows"]) > 10 else "")
        notes.append(f"{len(report['commentRows'])} line(s) start with # and look like rows (line {lines}). ReRime "
                     "reads a # line as a comment: it is not imported and not counted as skipped")
    beyond = sum(1 for text, _, _ in report["rows"] if not DRAWN_FOR_SURE.fullmatch(text))
    if beyond:
        notes.append(f"{beyond:,} row(s) have characters beyond ASCII and common Chinese. ReRime also skips a row "
                     "with a character the iPhone cannot draw; that is not checked here, so the iPhone may import "
                     "fewer rows than this report says")
    if report["suggestsEntries"]:
        notes.append("this file is small and mostly Chinese, so a tap on it (AirDrop, Files) opens ReRime's "
                     "personal dictionary import; add it from Keyboard Layout → Input Scheme → Add Input Scheme…")
    return notes


def name_line(report):
    """What ReRime calls the scheme: the preview's name field starts with this."""
    name = report["suggestedName"]
    source = "the dictionary's name" if report["reading"]["kind"] == "rimeDictionary" else "the file's name"
    if name is None:
        return f"Name: none usable from {source}; type one in ReRime's preview (at most {MAX_SCHEME_NAME} characters)"
    long = count_characters(name) > MAX_SCHEME_NAME
    return (f"Name: {name} (from {source}; shown on the Space key, "
            + (f"longer than the {MAX_SCHEME_NAME} characters a name can have: shorten it" if long
               else "editable")
            + " in ReRime's preview; Replace… keeps the installed scheme's name)")


def print_skips(skips):
    for number, reason in skips[:MAX_PRINTED]:
        print(f"SKIP line {number}: {SKIP_REASONS[reason]}")
    if len(skips) > MAX_PRINTED:
        print(f"... and {len(skips) - MAX_PRINTED:,} more skipped rows")


def main(arguments):
    as_json, table, paths = False, None, []
    arguments = list(arguments)
    while arguments:
        argument = arguments.pop(0)
        if argument == "--json":
            as_json = True
        elif argument == "--table" and arguments and arguments[0].isdigit():
            table = int(arguments.pop(0))
        else:
            paths.append(argument)
    if len(paths) != 1:
        print("usage: validate_rerime_table.py [--table ID] [--json] FILE")
        return 2
    file = Path(paths[0])
    if not file.is_file():
        print(f"ERROR not a file: {paths[0]}")
        return 1
    data = file.read_bytes()
    if as_json:
        report = report_json(data, file.name, table)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0 if report["door"]["route"] == "schemePreview" and not report.get("skipped") else 1
    try:
        report = read_file(data, file.name, table)
        if report["outcome"] == "choose":
            tables = report["tables"]
            print(f"NOTE the ZIP holds {len(tables)} tables; ReRime asks which one to add. Checking the first, "
                  "which ReRime preselects (use --table ID for another):")
            for item in tables:
                print(f"  ID {item['id']}: {item['memberName']}"
                      + (" (named by the scheme file in the ZIP)" if item["isSchemeMain"] else ""))
            report = read_file(data, file.name, tables[0]["id"])
    except Refusal as refusal:
        print_skips(getattr(refusal, "skips", []))
        print("ERROR", refusal.sentence())
        return 1
    skips, count = report["skips"], report["rowCount"]
    print_skips(skips)
    for note in reading_notes(report):
        print("NOTE", note)
    if not report["canBeTable"]:
        print("ERROR", Refusal("tooFewRows", rows=count, minimum=MIN_ROWS).sentence())
        return 1
    if skips:
        print(f"ReRime would import {count:,} rows and skip {len(skips):,}")
    else:
        print(f"OK {count:,} rows, {len(data):,} bytes")
    print(name_line(report))
    for line in describe(report["summary"]):
        print(line)
    return 1 if skips else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
