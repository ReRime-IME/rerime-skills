#!/usr/bin/env python3
"""Validate a ReRime personal dictionary file (.rerimedict) before sending it to iPhone.

Mirrors ReRime's import rules: UTF-8, no header, phrase<TAB>pinyin<TAB>frequency,
phrase 1-80 characters, pinyin 1-96 lowercase a-z letters, frequency 1-1000000,
at most 2 MiB and 10,000 entries. Prints problems by line number and exits 1 on any.
"""
import re
import sys
from pathlib import Path

MAX_BYTES = 2 * 1024 * 1024
MAX_ENTRIES = 10_000
PINYIN = re.compile(r"[a-z]{1,96}")


def main(path: str) -> int:
    data = Path(path).read_bytes()
    problems = []
    if len(data) > MAX_BYTES:
        problems.append(f"file is {len(data)} bytes; the limit is {MAX_BYTES} (2 MiB)")
    if data.startswith(b"\xef\xbb\xbf"):
        problems.append("remove the UTF-8 byte order mark")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        print(f"ERROR not UTF-8: {error}")
        return 1
    seen, entries = set(), 0
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        columns = line.split("\t")
        if len(columns) != 3:
            problems.append(f"line {number}: expected 3 tab-separated columns, found {len(columns)}")
            continue
        phrase, pinyin, frequency = columns
        if not 1 <= len(phrase) <= 80 or phrase != phrase.strip():
            problems.append(f"line {number}: phrase must be 1-80 characters without surrounding spaces")
        if not PINYIN.fullmatch(pinyin):
            problems.append(f"line {number}: pinyin must be 1-96 lowercase letters a-z (write ü as v)")
        if not frequency.isdigit() or not 1 <= int(frequency) <= 1_000_000:
            problems.append(f"line {number}: frequency must be an integer from 1 to 1000000")
        key = (phrase, pinyin)
        if key in seen:
            problems.append(f"line {number}: duplicate of an earlier phrase and pinyin")
        seen.add(key)
        entries += 1
    if entries > MAX_ENTRIES:
        problems.append(f"{entries} entries; the limit is {MAX_ENTRIES}")
    if entries == 0:
        problems.append("no entries")
    for problem in problems[:50]:
        print("ERROR", problem)
    if len(problems) > 50:
        print(f"... and {len(problems) - 50} more")
    if problems:
        return 1
    print(f"OK {entries} entries, {len(data)} bytes")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: validate_rerimedict.py FILE.rerimedict")
    sys.exit(main(sys.argv[1]))
