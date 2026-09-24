#!/usr/bin/env python3
"""Validate a ReRime personal dictionary file (.rerimedict) before sending it to iPhone.

Mirrors ReRime's import rules, a little stricter: UTF-8 without a byte order mark,
no header, phrase<TAB>pinyin<TAB>frequency, phrase 1-80 characters without control
or format characters and not starting with "#" (ReRime skips those lines as
comments), pinyin 1-96 lowercase a-z letters, frequency 1-1000000, at most 2 MiB
and 10,000 entries. Prints problems by line number and exits 1 on any.
"""
import re
import sys
import unicodedata
from pathlib import Path

MAX_BYTES = 2 * 1024 * 1024
MAX_ENTRIES = 10_000
MAX_LINES = MAX_ENTRIES + 500
PINYIN = re.compile(r"[a-z]{1,96}")
FREQUENCY = re.compile(r"[0-9]{1,7}")
# Cc and Cf match what ReRime rejects; Zl and Zp are line breaks inside a phrase.
FORBIDDEN_CATEGORIES = {"Cc", "Cf", "Zl", "Zp"}


def main(path: str) -> int:
    file = Path(path)
    if not file.is_file():
        print(f"ERROR not a file: {path}")
        return 1
    data = file.read_bytes()
    problems = []
    if len(data) > MAX_BYTES:
        problems.append(f"file is {len(data)} bytes; the limit is {MAX_BYTES} (2 MiB)")
    if data.startswith(b"\xef\xbb\xbf"):
        problems.append("remove the UTF-8 byte order mark")
        data = data[3:]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        print(f"ERROR not UTF-8: {error}")
        return 1
    # ReRime splits on CR, LF and CRLF only.
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if len(lines) > MAX_LINES:
        problems.append(f"{len(lines)} lines; ReRime reads at most {MAX_LINES}")
    seen, entries = set(), 0
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        columns = line.split("\t")
        if len(columns) != 3:
            problems.append(f"line {number}: expected 3 tab-separated columns, found {len(columns)}")
            continue
        phrase, pinyin, frequency = columns
        if not 1 <= len(phrase) <= 80 or phrase != phrase.strip():
            problems.append(f"line {number}: phrase must be 1-80 characters without surrounding spaces")
        elif phrase.startswith("#"):
            problems.append(f"line {number}: phrase must not start with # (ReRime reads the line as a comment)")
        elif any(unicodedata.category(c) in FORBIDDEN_CATEGORIES for c in phrase):
            problems.append(f"line {number}: phrase contains a control, format or line-break character")
        if not PINYIN.fullmatch(pinyin):
            problems.append(f"line {number}: pinyin must be 1-96 lowercase letters a-z (write ü as v)")
        if not FREQUENCY.fullmatch(frequency) or not 1 <= int(frequency) <= 1_000_000:
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
