#!/usr/bin/env python3
"""Compares validate_rerime_table.py with ReRime's own importer on the synthetic corpus.

    python3 tests/parity/compare.py HARNESS [--large] [--sweeps] [--update] [--keep DIRECTORY]

HARNESS is the tool built by build_harness.sh from the ReRime App repository. For every
case of generate_corpus.py both sides report what they decide (accepted or refused and why,
how the file was read, rows kept and skipped by reason with line numbers, the canonical
table, the analysis and the run mode) and the reports must be equal; kept rows are compared
row by row. --sweeps also compares the character data the checker carries, every Unicode
scalar as a row's text, GB18030 byte sequences, and character counts of random strings. --update writes the importer's answers
to expected.json, which tests/test_parity.py checks without the App repository.
"""
import importlib.util
import json
import random
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
CHECKER = ROOT / "plugins/rerime-dictionary/skills/rerime-dictionary/scripts/validate_rerime_table.py"
EXPECTED = HERE / "expected.json"
LIMITS = {"maximumFileBytes": "MAX_BYTES", "maximumRows": "MAX_ROWS", "maximumArchiveBytes": "MAX_ARCHIVE_BYTES",
          "maximumArchiveMembers": "MAX_ARCHIVE_MEMBERS", "maximumMemberBytes": "MAX_MEMBER_BYTES",
          "maximumImportBytes": "MAX_IMPORT_BYTES", "maximumLineBytes": "MAX_LINE_BYTES",
          "maximumHeaderBytes": "MAX_HEADER_BYTES", "maximumHeaderLines": "MAX_HEADER_LINES",
          "personalEntryRows": "ENTRY_ROWS", "personalEntryBytes": "ENTRY_BYTES"}


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = load(CHECKER, "validate_rerime_table")
corpus = load(HERE / "generate_corpus.py", "generate_corpus")


def checker_report(case, data=None, with_rows=False):
    """The checker's report for one case, under the case's limits."""
    saved = {name: getattr(checker, name) for name in LIMITS.values()}
    try:
        for key, value in (case.get("limits") or {}).items():
            setattr(checker, LIMITS[key], value)
        data = Path(case["path"]).read_bytes() if data is None else data
        if with_rows:
            try:
                return checker.report_json(data, case.get("fileName"), case.get("table")), \
                    checker.read_file(data, case.get("fileName"), case.get("table")).get("rows")
            except checker.Refusal:
                return checker.report_json(data, case.get("fileName"), case.get("table")), None
        return checker.report_json(data, case.get("fileName"), case.get("table"))
    finally:
        for name, value in saved.items():
            setattr(checker, name, value)


def differences(ours, theirs, path=""):
    """Paths at which two JSON values differ."""
    if isinstance(ours, dict) and isinstance(theirs, dict):
        found = []
        for key in sorted(set(ours) | set(theirs)):
            found += differences(ours.get(key, "<absent>"), theirs.get(key, "<absent>"), f"{path}.{key}" if path else key)
        return found
    if ours != theirs:
        return [f"{path}: checker {json.dumps(ours, ensure_ascii=False)[:200]} | importer {json.dumps(theirs, ensure_ascii=False)[:200]}"]
    return []


def compare_cases(harness, folder, large):
    cases = corpus.write(folder / "corpus", large)
    out = folder / "canonical"
    done = subprocess.run([harness, "cases", str(folder / "corpus/cases.json"), str(out)], capture_output=True, check=True)
    theirs = {}
    for line in done.stdout.decode("utf-8").splitlines():
        report = json.loads(line)
        theirs[report.pop("name")] = report
    failed = rows_compared = 0
    for case in cases:
        name = case["name"]
        ours, rows = checker_report(case, with_rows=True)
        found = differences(ours, theirs[name])
        table = out / f"{name}.tsv"
        if rows is not None and table.exists():
            kept = table.read_bytes().decode("utf-8").split("\n")[:-1]
            mine = checker.canonical_table(rows).decode("utf-8").split("\n")[:-1]
            rows_compared += len(kept)
            for index in range(max(len(kept), len(mine))):
                left = mine[index] if index < len(mine) else "<none>"
                right = kept[index] if index < len(kept) else "<none>"
                if left != right:
                    found.append(f"row {index + 1}: checker {left!r} | importer {right!r}")
                    break
        if found:
            failed += 1
            print(f"DIFFERENT {name}")
            for line in found[:8]:
                print("   ", line)
    print(f"cases: {len(cases)} compared, {failed} different, {rows_compared:,} kept rows compared row by row")
    return cases, theirs, failed


# --- Sweeps -------------------------------------------------------------------------------------


def probe(file, probe_text):
    """The same verdict string as the harness's `probe`."""
    try:
        report = checker.read_file(file, "probe.txt")
    except checker.Refusal as refusal:
        return "R" + refusal.code
    kept = ["=" if text.encode("utf-8") == probe_text else "K" + text.encode("utf-8").hex()
            for text, code, _ in report["rows"] if code == "zz"]
    skipped = sorted(f"{reason}@{','.join(map(str, lines))}" for reason, lines in report["skippedLines"].items())
    rows = report["rowCount"] - len(kept)
    return " ".join(kept + skipped) + ("" if rows == 2 else f" rows={rows}")


def sweep(harness, mode, ours):
    theirs = subprocess.run([harness, mode], capture_output=True, check=True).stdout.decode("utf-8").splitlines()
    different = [(mine, other) for mine, other in zip(ours, theirs) if mine != other]
    different += [("<count>", f"{len(ours)} lines | {len(theirs)} lines")] * (len(ours) != len(theirs))
    print(f"sweep {mode}: {len(theirs):,} probes, {len(different)} different")
    for mine, other in different[:40]:
        print(f"    checker {mine!r} | importer {other!r}")
    return len(different)


def scalar_lines():
    head = "天\taa\n地\tab\n".encode("utf-8")
    for value in range(0x110000):
        if 0xD800 <= value <= 0xDFFF:
            continue
        alone = chr(value).encode("utf-8")
        inside = "中".encode("utf-8") + alone + "中".encode("utf-8")
        first, second = probe(head + alone + b"\tzz\n", alone), probe(head + inside + b"\tzz\n", inside)
        yield f"{value:x}\t{first}\t{second}"


def gb18030_lines(step=97):
    head = b"\xcc\xec\taa\n\xb5\xd8\tab\n"

    def line(sequence):
        verdict = probe(head + sequence + b"\tzz\n", b"")
        return f"{sequence.hex()}\t{verdict}"

    for byte in range(0x80, 0x100):
        yield line(bytes([byte]))
    for lead in range(0x81, 0x100):
        for trail in range(0x30, 0x100):
            yield line(bytes([lead, trail]))
    index = 0
    for b1 in range(0x81, 0xFF):
        for b2 in range(0x30, 0x3A):
            for b3 in range(0x81, 0xFF):
                for b4 in range(0x30, 0x3A):
                    if b1 <= 0x84 or index % step == 0:
                        yield line(bytes([b1, b2, b3, b4]))
                    index += 1


def grapheme_strings(count=200_000):
    """Random strings over the scalars that group into characters in special ways."""
    rng = random.Random(11)
    pools = [checker.JOINS_PREVIOUS, checker.JOINS_NEXT, checker.CONJUNCT_CONSONANT, checker.CONJUNCT_EXTEND,
             [(0x1100, 0x11FF)], [(0xA960, 0xA97C)], [(0xD7B0, 0xD7FB)], [(0xAC00, 0xD7A3)], [(0x1F1E6, 0x1F1FF)],
             [(0x94D, 0x94D)], [(0x61, 0x7A)], [(0x4E00, 0x4E20)], [(0x1F300, 0x1F5FF)], [(0x900, 0xD7F)],
             [(0x3000, 0x3000)], [(0x20, 0x20)]]
    for _ in range(count):
        scalars = []
        for _ in range(rng.randint(1, 8)):
            low, high = rng.choice(rng.choice(pools))
            value = rng.randint(low, high)
            # U+200D joins emoji into one character; ReRime refuses it in a text or a name
            # before anything is counted, and count_characters does not model it.
            scalars.append(value if value != 0x200D else 0x61)
        yield scalars


def compare_graphemes(harness):
    strings = list(grapheme_strings())
    stdin = "".join(" ".join(f"{value:x}" for value in scalars) + "\n" for scalars in strings)
    theirs = subprocess.run([harness, "graphemes"], input=stdin.encode(), capture_output=True, check=True).stdout.split()
    different = [(scalars, int(count)) for scalars, count in zip(strings, theirs)
                 if checker.count_characters("".join(map(chr, scalars))) != int(count)]
    print(f"sweep graphemes: {len(strings):,} strings, {len(different)} different")
    for scalars, count in different[:20]:
        print("    ", " ".join(f"{value:04x}" for value in scalars), "checker",
              checker.count_characters("".join(map(chr, scalars))), "| Swift", count)
    return len(different)


def compare_tables(harness):
    """The character data the checker carries against this host's Swift and Foundation."""
    different = 0
    for line in subprocess.run([harness, "tables"], capture_output=True, check=True).stdout.decode().splitlines():
        name, _, ranges = line.partition(" ")
        if getattr(checker, name) != checker._ranges(ranges):
            different += 1
            print(f"    table {name} differs; this host's Swift gives: {ranges}")
    print(f"character tables: {different} different")
    return different


def main():
    arguments = sys.argv[1:]
    flags = {name for name in ("--large", "--sweeps", "--update") if name in arguments}
    keep = arguments[arguments.index("--keep") + 1] if "--keep" in arguments else None
    paths = [argument for argument in arguments if argument not in flags and argument not in ("--keep", keep)]
    if len(paths) != 1:
        sys.exit(__doc__)
    harness = paths[0]
    with tempfile.TemporaryDirectory() as temporary:
        folder = Path(keep or temporary)
        cases, theirs, failed = compare_cases(harness, folder, "--large" in flags)
        if "--sweeps" in flags:
            failed += compare_tables(harness)
            failed += compare_graphemes(harness)
            failed += sweep(harness, "gb18030", list(gb18030_lines()))
            failed += sweep(harness, "scalars", list(scalar_lines()))
        if "--update" in flags:
            if "--large" not in flags:
                kept = json.loads(EXPECTED.read_text(encoding="utf-8")) if EXPECTED.exists() else {}
                theirs.update({name: report for name, report in kept.items() if name.startswith("large-")})
            EXPECTED.write_text(json.dumps(theirs, ensure_ascii=False, sort_keys=True, indent=0) + "\n", encoding="utf-8")
            print(f"wrote {EXPECTED.relative_to(ROOT)} ({len(theirs)} cases)")
    print("EQUAL" if not failed else "DIFFERENT")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
