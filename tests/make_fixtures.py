#!/usr/bin/env python3
"""Writes the format fixtures of tests/fixtures that are not plain UTF-8 text.

    python3 tests/make_fixtures.py

Every fixture is synthetic: invented codes on common characters, no real input scheme and
no user data. The same call always writes the same bytes; the files are committed, and
this script is how they were made.
"""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
spec = importlib.util.spec_from_file_location("generate_corpus", HERE / "parity/generate_corpus.py")
corpus = importlib.util.module_from_spec(spec)
spec.loader.exec_module(corpus)

SINGLES = [("天", "bap"), ("地", "bop"), ("玄", "dap"), ("黄", "dop"), ("宇", "gap"), ("宙", "gop"),
           ("洪", "kap"), ("荒", "kop"), ("日", "map"), ("月", "mop"), ("盈", "bat"), ("昃", "bot")]
WORDS = [("天地", "bapbop"), ("宇宙", "gapgop"), ("日月", "mapmop"), ("洪荒", "kapkop")]
ROWS = SINGLES + WORDS
TABLE = "".join(f"{text}\t{code}\n" for text, code in ROWS)
DICTIONARY = ("# Synthetic test dictionary: invented codes.\n---\nname: sample\nversion: \"1\"\nsort: original\n"
              "import_tables:\n  - sample.extra\n...\n" + TABLE)
EXTRA = "---\nname: sample.extra\nversion: \"1\"\n...\n辰\tdat\n宿\tdot\n辰宿\tdatdot\n"
SCHEMA = ("schema:\n  schema_id: sample\n  name: Sample\nengine:\n  translators:\n    - table_translator\n"
          "translator:\n  dictionary: sample\n")


def main():
    files = {
        "utf16le-bom.txt": b"\xff\xfe" + TABLE.encode("utf-16-le"),
        "utf16be-unmarked.txt": TABLE.encode("utf-16-be"),
        "gb18030.txt": ("# 测试码表\n" + TABLE).encode("gb18030"),
        # Codes the iPhone decodes differently from Python: 0x80 (euro sign) and A6 D9 (U+FE10).
        "gb18030-current-standard.txt": TABLE.encode("gb18030") + b"\x80\tkat\n\xa6\xd9\tkot\n",
        # Baidu's phone export is UTF-16 with a byte order mark.
        "phrase-baidu-mobile.ini": b"\xff\xfe" + "".join(
            f"{code}={n % 3 + 1},{text}\r\n" for n, (text, code) in enumerate(ROWS)).encode("utf-16-le"),
        "one-table.zip": corpus.Zip().add("sample/sample.schema.yaml", SCHEMA.encode()).add(
            "sample/sample.dict.yaml", DICTIONARY.encode()).add("sample/sample.extra.dict.yaml", EXTRA.encode()).add(
            "sample/setup.exe", b"MZ\x90\x00" + bytes(32)).add("sample/readme.txt", b"Read me first.\nThanks.\n").bytes(),
        "several-tables.zip": corpus.Zip().add("other.dict.yaml", ("---\nname: other\n...\n" + TABLE).encode()).add(
            "sample.dict.yaml", DICTIONARY.encode()).add("sample.schema.yaml", SCHEMA.encode()).add(
            "示例.txt".encode("gbk"), TABLE.encode("gb18030")).bytes(),
        "escaping-path.zip": corpus.Zip().add("../sample.dict.yaml", DICTIONARY.encode()).bytes(),
        "no-table.zip": corpus.Zip().add("setup.exe", b"MZ\x90\x00" + bytes(32)).add("font.ttf", b"\x00\x01\x00\x00").bytes(),
    }
    for name, data in files.items():
        (FIXTURES / name).write_bytes(data)
    print(f"{len(files)} fixtures written to {FIXTURES}")


if __name__ == "__main__":
    main()
