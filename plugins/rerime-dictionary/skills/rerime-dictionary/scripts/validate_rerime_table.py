#!/usr/bin/env python3
"""Check a table file for ReRime's "Add Input Scheme…" before sending it to iPhone.

Reads a tab-separated text table (text<TAB>code, optionally <TAB>weight; either of the
first two columns may be the code) or a Rime dictionary (*.dict.yaml), applies the row
rules of ReRime's importer, and predicts how ReRime will run the table: by syllable or
whole word.

Row rules: code is letters a-z (capitals are lowercased), at most 96, one space allowed
between syllables; text is 1-80 characters with no control, directional, invisible or
unusual space characters; a weight is 1-10 digits; a line is at most 4,096 bytes. File
rules: UTF-8, at most 16 MiB and 300,000 rows, at least 2 rows, and at least as many
valid rows as invalid ones.

Prints "SKIP line N" for each row ReRime would leave out and "ERROR" when ReRime would
refuse the file, then the run mode. Exits 0 only when nothing is skipped or refused.

Not checked here: whether iOS can draw every character (ReRime skips rows it cannot),
other encodings ReRime reads (UTF-16, GB18030), space-separated tables, phrase lists and
ZIP files. Text length is counted in code points, which is a little stricter than ReRime.
"""
import re
import sys
import unicodedata
from pathlib import Path

MAX_BYTES = 16 * 1024 * 1024
MAX_ROWS = 300_000
MIN_ROWS = 2
MAX_LINE_BYTES = 4096
MAX_CODE_LETTERS = 96
MAX_TEXT_CHARACTERS = 80
MAX_WEIGHT_DIGITS = 10
MAX_COMBINING_MARKS = 4
HEADER_LINES = 200
# A table built by syllable runs by syllable only within both bounds.
SYLLABLE_BOUND = 3_500
SPELLING_BOUND = 20_000
# Share of multi-character rows that must be coded as their characters' codes.
SYLLABLE_SHARE_PERCENT = 99
# The personal dictionary's limits: a file within them may be offered as entries.
ENTRY_ROWS = 10_000
ENTRY_BYTES = 2 * 1024 * 1024
MAX_PRINTED = 50

CODE = re.compile(r"[A-Za-z]+(?: +[A-Za-z]+)*")
DIGITS = re.compile(r"[0-9]+")
BIDI = {0x061C, 0x200E, 0x200F, *range(0x202A, 0x202F), *range(0x2066, 0x206A)}
CONTROL_CATEGORIES = {"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"}
MARK_CATEGORIES = {"Mn", "Mc", "Me"}
# Default-ignorable code points and variation selectors outside the categories above.
INVISIBLE = [(0x034F, 0x034F), (0x115F, 0x1160), (0x17B4, 0x17B5), (0x180B, 0x180F),
             (0x3164, 0x3164), (0xFE00, 0xFE0F), (0xFFA0, 0xFFA0), (0xE0000, 0xE0FFF)]
IDEOGRAPHS = [(0x3007, 0x3007), (0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0x20000, 0x2A6DF),
              (0x2A700, 0x2EE5F), (0x30000, 0x323AF)]


class Refusal(Exception):
    """ReRime would not import the file at all."""


def in_ranges(value, ranges):
    return any(low <= value <= high for low, high in ranges)


def check_text(field):
    """(text, None) for a text ReRime keeps, else (None, why it skips the row)."""
    text = field.strip(" \t\r　")
    if not text:
        return None, "no text"
    marks = 0
    for character in text:
        value = ord(character)
        if value < 0x80:
            if value < 0x20 or value == 0x7F:
                return None, "text has a control character"
            marks = 0
            continue
        if value in BIDI:
            return None, "text has a directional control character"
        category = unicodedata.category(character)
        if category in CONTROL_CATEGORIES:
            return None, "text has a control, format, private-use or unassigned character"
        if category == "Zs" and value != 0x3000:
            return None, "text has a space character other than a plain or full-width space"
        if category in MARK_CATEGORIES:
            marks += 1
            if marks > MAX_COMBINING_MARKS:
                return None, f"text has more than {MAX_COMBINING_MARKS} combining marks in a row"
        else:
            marks = 0
        if in_ranges(value, INVISIBLE):
            return None, "text has an invisible character (such as a variation selector)"
    text = unicodedata.normalize("NFC", text)
    if len(text) > MAX_TEXT_CHARACTERS:
        return None, f"text is longer than {MAX_TEXT_CHARACTERS} characters"
    return text, None


def check_code(field):
    """(code, None) with one space between syllables, else (None, why)."""
    code = field.strip(" \t\r")
    if not code:
        return None, "no code"
    if not CODE.fullmatch(code):
        return None, "code must be letters a-z only"
    code = " ".join(code.lower().split())
    if len(code.replace(" ", "")) > MAX_CODE_LETTERS:
        return None, f"code is longer than {MAX_CODE_LETTERS} letters"
    return code, None


def rime_header(lines):
    """The column order of a Rime dictionary, or None when the file is not one.

    A Rime dictionary has a line "..." within its first lines and a name before it."""
    end = next((i for i, line in enumerate(lines[:HEADER_LINES]) if line == "..."), None)
    if end is None:
        return None
    header = {"body": end + 1, "columns": None, "name": "", "sort_original": False, "imports": False}
    list_key = None
    for line in lines[:end]:
        if not line or line.startswith("#"):
            continue
        if line[0] in " -":
            item = line.strip()
            if list_key == "columns" and item.startswith("- "):
                header["columns"] = (header["columns"] or []) + [scalar(item[2:])]
            continue
        list_key = None
        key, colon, rest = line.partition(":")
        if not colon:
            continue
        rest = rest.strip()
        if key == "name":
            header["name"] = scalar(rest)
        elif key == "sort":
            header["sort_original"] = scalar(rest) == "original"
        elif key == "import_tables":
            header["imports"] = True
        elif key == "columns":
            if rest.startswith("[") and "]" in rest:
                items = rest[1:rest.index("]")].split(",")
                header["columns"] = [scalar(item) for item in items if scalar(item)]
            elif not rest:
                list_key = "columns"
    if not header["name"]:
        return None
    columns = header["columns"] or ["text", "code", "weight"]
    header["order"] = [columns.index(name) if name in columns else None for name in ("text", "code", "weight")]
    return header


def scalar(value):
    value = value.split(" #")[0].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return value


def read(data):
    """Rows ReRime would keep, in its candidate order, and what it would skip.

    Returns (rows, skips, notes): rows are (text, code without spaces, weight or -1),
    skips are (line number, reason)."""
    if not data:
        raise Refusal("the file is empty")
    if len(data) > MAX_BYTES:
        raise Refusal(f"file is {len(data):,} bytes; the limit is {MAX_BYTES:,} (16 MiB)")
    notes = []
    body = data
    if body.startswith(b"\xef\xbb\xbf"):
        body = body[3:]
        notes.append("the file starts with a byte order mark; ReRime reads it, but plain UTF-8 is safer")
    try:
        content = body.decode("utf-8")
    except UnicodeDecodeError:
        raise Refusal("not UTF-8 (ReRime also reads UTF-16 and GB18030, but this checker "
                      "does not: save the file as UTF-8)")
    if "\x00" in content:
        raise Refusal("the file is not text")
    # ReRime ends a line at a line feed only and drops trailing spaces, tabs and returns.
    lines = [line.rstrip(" \t\r") for line in content.split("\n")]
    header = rime_header(lines)
    skips, candidates = [], []  # candidates: (line number, text field, code field, weight field)

    def too_long(number, line):
        if len(line) > MAX_LINE_BYTES // 4 and len(line.encode("utf-8")) > MAX_LINE_BYTES:
            skips.append((number, f"line is longer than {MAX_LINE_BYTES:,} bytes"))
            return True
        return False

    if header:
        notes.append("read as a Rime dictionary" + ("; candidates of one code keep the file's order (sort: original)"
                                                    if header["sort_original"] else ""))
        if header["imports"]:
            notes.append("import_tables is followed only inside a ZIP; from a single file those rows are missing")
        text_at, code_at, weight_at = header["order"]
        comments = True
        for number, line in enumerate(lines[header["body"]:], start=header["body"] + 1):
            if not line:
                continue
            if comments and line.startswith("#"):
                comments = line != "# no comment"
                continue
            if too_long(number, line):
                continue
            fields = line.split("\t")
            if text_at is None or text_at >= len(fields):
                skips.append((number, "no text column"))
            elif code_at is None or code_at >= len(fields) or not fields[code_at].strip(" \t\r"):
                skips.append((number, "no code"))
            else:
                weight = fields[weight_at] if weight_at is not None and weight_at < len(fields) else ""
                candidates.append((number, fields[text_at], fields[code_at], weight))
    else:
        data_lines = [(number, line.strip(" \t\r")) for number, line in enumerate(lines, start=1)]
        data_lines = [(number, line) for number, line in data_lines if line and not line.startswith("#")]
        if not any("\t" in line for _, line in data_lines):
            raise Refusal("no tab-separated rows (write text<TAB>code on each line)" if data_lines
                          else "the file has no rows")
        # The column that is all letters is the code; when both are, text comes first.
        code_first = text_first = 0
        for _, line in data_lines:
            fields = line.split("\t")
            if len(fields) >= 2:
                left, right = (bool(CODE.fullmatch(field.strip(" \t\r"))) for field in fields[:2])
                code_first += left and not right
                text_first += right and not left
        swapped = code_first > text_first
        if swapped:
            notes.append("read with the code in the first column")
        for number, line in data_lines:
            if too_long(number, line):
                continue
            fields = line.split("\t")
            has_weight = len(fields) == 3 and bool(DIGITS.fullmatch(fields[2].strip(" \t\r")))
            if len(fields) == 1:
                skips.append((number, "no code (the line has one column)"))
            elif len(fields) > 3 or (len(fields) == 3 and not has_weight):
                skips.append((number, "expected text<TAB>code or text<TAB>code<TAB>weight with a whole-number weight"))
            else:
                text, code = (fields[1], fields[0]) if swapped else (fields[0], fields[1])
                value = text.strip(" \t\r")
                if len(value) >= 2 and value[0] == "$" and (value[1].isascii() and value[1].isalpha() or value[1] == "["):
                    skips.append((number, "text is a command value ($…), not text"))
                else:
                    candidates.append((number, text, code, fields[2] if has_weight else ""))

    kept, seen, duplicates, capitals = [], set(), 0, 0
    for number, text_field, code_field, weight_field in candidates:
        code, problem = check_code(code_field)
        text = None
        if not problem:
            text, problem = check_text(text_field)
        if problem:
            skips.append((number, problem))
            continue
        capitals += code_field.strip(" \t\r") != code_field.strip(" \t\r").lower()
        weight_field = weight_field.strip(" \t\r")
        weight = -1
        if DIGITS.fullmatch(weight_field) and len(weight_field) <= MAX_WEIGHT_DIGITS:
            weight = int(weight_field)
        elif weight_field and not header:
            notes.append(f"line {number}: a weight of more than {MAX_WEIGHT_DIGITS} digits is ignored")
        if (text, code) in seen:
            duplicates += 1
            skips.append((number, "duplicate of an earlier row (same text and code)"))
            continue
        seen.add((text, code))
        kept.append((text, code, weight, len(kept)))
    if capitals:
        notes.append(f"{capitals:,} codes have capital letters; ReRime lowercases them")

    invalid = len(skips) - duplicates
    valid = len(kept) + duplicates
    skips.sort()
    if valid + invalid == 0:
        raise Refusal("the file has no rows")
    if valid < invalid:
        raise RefusalWithSkips(f"{invalid:,} rows break a rule and only {valid:,} are valid; "
                               "ReRime refuses a file with more invalid rows than valid ones", skips)
    if len(kept) > MAX_ROWS:
        raise RefusalWithSkips(f"{len(kept):,} rows; the limit is {MAX_ROWS:,}", skips)
    if len(kept) < MIN_ROWS:
        raise RefusalWithSkips(f"{len(kept)} valid row; a table needs at least {MIN_ROWS}", skips)

    # ReRime's candidate order: by code, then weight (highest first), then file order.
    if header and header["sort_original"]:
        kept.sort(key=lambda row: (row[1], row[3]))
    else:
        kept.sort(key=lambda row: (row[1], -row[2], row[3]))
    # Spaces between syllables are not used to split a code; rows equal without them merge.
    rows, joined = [], set()
    for text, code, weight, _ in kept:
        code = code.replace(" ", "")
        if (text, code) not in joined:
            joined.add((text, code))
            rows.append((text, code, weight))

    han = sum(all(in_ranges(ord(character), IDEOGRAPHS) for character in text) for text, _, _ in rows)
    if len(rows) <= ENTRY_ROWS and len(data) <= ENTRY_BYTES and han * 2 >= len(rows):
        notes.append("this file is small and mostly Chinese, so a tap on it (AirDrop, Files) opens ReRime's "
                     "personal dictionary import; add it from Keyboard Layout → Input Scheme → Add Input Scheme…")
    return rows, skips, notes


class RefusalWithSkips(Refusal):
    def __init__(self, message, skips):
        super().__init__(message)
        self.skips = skips


# --- How ReRime runs the table ----------------------------------------------------------------


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


def budget_state(index_bytes, text_bytes, syllables, entries):
    """Whether the compiled table stays within the engine's own size estimate for it:
    "fits", "exact" (ReRime measures it at import) or "no"."""
    estimate = 4096 + 32 * syllables + 64 * entries
    if index_bytes + int(1.2 * text_bytes) + 4096 <= estimate:
        return "fits"
    return "exact" if index_bytes + 4096 <= estimate else "no"


def analyze(rows):
    """What the rows say about how the table is coded, and the run mode ReRime picks."""
    codes = {}
    once, repeated = set(), set()
    for text, code, _ in rows:
        if text in once:
            repeated.add(text)
        once.add(text)
        if len(text) == 1 and code not in codes.setdefault(text, []):
            codes[text].append(code)
    multi = all_characters = leading = otherwise = 0
    index, seen, distinct = IndexCounter(), set(), set()
    for text, code, _ in rows:
        distinct.add(code)
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
        if len(text) > 1:
            multi += 1
            if cover is None:
                otherwise += 1
            elif len(cover) == len(coded):
                all_characters += 1
            else:
                leading += 1
    syllable_codes = {code for options in codes.values() for code in options}
    longest = max(map(len, syllable_codes), default=0)
    finals = optional_finals(syllable_codes)
    built = multi > 0 and (all_characters + leading) * 100 >= SYLLABLE_SHARE_PERCENT * multi
    text_bytes = sum(len(text.encode("utf-8")) + 1 for text, _, _ in rows)
    result = {"rows": len(rows), "multi": multi, "compositional": all_characters + leading,
              "otherwise": otherwise, "built": built, "finals": finals, "syllables": 0, "spellings": 0}
    syllable_budget = "no"
    if built:
        result["syllables"] = len(index.ids)
        # Each syllable is spelled by itself and by every shorter prefix, up to the longest
        # one-character code; a longer unit ending in an optional letter has one more.
        result["spellings"] = sum(min(len(unit), longest) + (len(unit) > longest and unit[-1] in finals)
                                  for unit in index.ids)
        syllable_budget = budget_state(index.bytes, text_bytes + sum(len(unit) + 1 for unit in index.ids),
                                       len(index.ids), index.entries)
    whole_index = 68 + 4 + 4 * len(distinct) + 4 + 12 * len(distinct) + 8 * len(rows)
    whole_budget = budget_state(whole_index, text_bytes + sum(len(code) + 1 for code in distinct),
                                len(distinct), len(rows))
    within = result["syllables"] <= SYLLABLE_BOUND and result["spellings"] <= SPELLING_BOUND
    if built and within and syllable_budget != "no":
        result["mode"], result["budget"] = "syllable", syllable_budget
    elif whole_budget != "no":
        result["mode"], result["budget"] = "whole", whole_budget
    else:
        result["mode"], result["budget"] = None, "no"
    result["syllable_budget"] = syllable_budget
    return result


def describe(result):
    """The run mode and its reasons, as lines to print."""
    multi, compositional = result["multi"], result["compositional"]
    counts = (f"{result['syllables']:,} syllables (at most {SYLLABLE_BOUND:,}), "
              f"{result['spellings']:,} spellings (at most {SPELLING_BOUND:,})")
    share = (f"{compositional:,} of {multi:,} multi-character rows are coded as the joined codes of their "
             f"characters (ReRime needs {SYLLABLE_SHARE_PERCENT}%)")
    if result["mode"] is None:
        return ["ERROR the table does not fit ReRime's engine: its entries are too long or share too few "
                "leading codes"]
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
    if result["budget"] == "exact":
        lines.append("  NOTE the table is near the engine's size limit; ReRime measures it at import and may "
                     + ("run it whole word or refuse it" if result["mode"] == "syllable" else "refuse it"))
    return lines


def main(path):
    file = Path(path)
    if not file.is_file():
        print(f"ERROR not a file: {path}")
        return 1
    data = file.read_bytes()
    try:
        rows, skips, notes = read(data)
    except Refusal as refusal:
        print_skips(getattr(refusal, "skips", []))
        print("ERROR", refusal)
        return 1
    result = analyze(rows)
    print_skips(skips)
    for note in notes:
        print("NOTE", note)
    if skips:
        print(f"ReRime would import {len(rows):,} rows and skip {len(skips):,}")
    else:
        print(f"OK {len(rows):,} rows, {len(data):,} bytes")
    for line in describe(result):
        print(line)
    return 1 if skips or result["mode"] is None else 0


def print_skips(skips):
    for number, reason in skips[:MAX_PRINTED]:
        print(f"SKIP line {number}: {reason}")
    if len(skips) > MAX_PRINTED:
        print(f"... and {len(skips) - MAX_PRINTED:,} more skipped rows")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: validate_rerime_table.py FILE")
    sys.exit(main(sys.argv[1]))
