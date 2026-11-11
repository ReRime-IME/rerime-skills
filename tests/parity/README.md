# Checker against ReRime's importer

`validate_rerime_table.py` says what ReRime would do with a table file. This folder
checks that claim against ReRime's own importer: the Swift code of the App, compiled on a
Mac and run on the same files.

The App's source is not in this repository and must not be copied into it. What is here:

| File | What it is |
| --- | --- |
| `generate_corpus.py` | Writes the synthetic corpus: invented codes on common characters, no real input scheme and no user data. The same call always writes the same bytes. |
| `expected.json` | What the importer decided about every corpus case. `tests/test_parity.py` requires the checker to decide the same, without the App repository. |
| `main.swift` | A small program around the importer: reads a file, prints as JSON what the importer decides. It holds no App source. |
| `build_harness.sh` | Compiles `main.swift` with the importer sources of an App checkout. |
| `compare.py` | Runs both sides on the corpus and compares them; refreshes `expected.json`. |

## Without the App repository

```bash
python3 -m unittest discover -s tests -v
```

`tests/test_parity.py` writes the corpus into a temporary folder and compares the checker's
report for every case with `expected.json`. `RERIME_PARITY_LARGE=1` adds the eleven cases
that cross ReRime's real caps (300,000 rows, 16 MiB per file or member, 64 MiB and 512
files per ZIP); they need about 400 MB of disk for a moment.

## With the App repository (a Mac with Xcode's `swiftc`)

```bash
bash tests/parity/build_harness.sh /path/to/re_rime /tmp/importer-report
```

```bash
python3 tests/parity/compare.py /tmp/importer-report --large --sweeps
```

`compare.py` prints every difference and ends with `EQUAL` or `DIFFERENT`. Add `--update`
to write the importer's answers to `expected.json` (do this after the importer changed, then
fix the checker until the tests pass). Options:

- `--large`: the eleven real-cap cases too.
- `--sweeps`: beyond the corpus, compare
  - the character data the checker carries (`JOINS_PREVIOUS`, `IDEOGRAPHS`, … in the
    checker) with what this Mac's Swift and Foundation answer;
  - every Unicode scalar as the text of a row, alone and between two other characters
    (1,112,064 scalars, two probes each);
  - GB18030: every single byte from 0x80, every two-byte sequence, every four-byte
    sequence of the BMP range and a sample of the rest (92,792 probes; `gb18030_lines(step=1)`
    covers all 1,614,144);
  - the character count of 200,000 random strings over the code points that group in
    special ways (marks, Hangul jamo, flags, Indic conjuncts).
- `--keep DIRECTORY`: keep the corpus and the importer's canonical tables there.

What is compared for a case: accepted, refused (which refusal, with its numbers) or "choose
a table"; how the file was read (kind, encoding, byte order mark, separator, column order,
data marker, kept file order, imported and missing files); the kept rows, row by row, as
ReRime's canonical table; the skipped rows by reason, with the line numbers the importer
keeps (the first twelve per reason); the suggested name; whether the file would be offered
as personal entries; the tables of a ZIP in the order ReRime lists them; the analysis
(structure counts, syllables, spellings, optional trailing letters, both size budgets, the
engine rows of both run modes by digest); the run mode; and what the Add Input Scheme…
door answers.

## What is compiled, and what is not

`build_harness.sh` compiles these files of the App's `ios/ReRime/ReRime/UserTable/` folder
as they are: `UserTableImportTypes`, `UserTableImporter`, `UserTableSourceRecognizer`,
`UserTableRowReaders`, `UserTableRowCollector`, `UserTableTextDecoder`, `UserTableZipReader`,
`UserTableAnalysis`, `UserTableCanonicalWriter`, and `Shared/UserTableScheme.swift`.

- `UserTableDoors.swift` is compiled only up to its door rules (`UserTableDoors.route` and
  the types it uses). Its last type, `UserTableAttention`, needs the App's install state
  (`UserTableState`, `UserTableBuildStamp`) and has nothing to do with reading a file; the
  script cuts the file before it, into a temporary folder.
- The rendered-text check (`IOSRenderedTextPolicy`: can this iPhone draw the character) is
  not compiled. The harness answers "yes" for every character, as the checker must: a Mac
  cannot say what an iPhone's fonts hold. Rows ReRime skips for that reason
  (`textNotRenderable`) are therefore not compared.
- The App's Pinyin syllable list is not compiled; a few syllables stand in for it. It
  decides nothing the checker reports: whether a file is offered as personal entries
  depends on its size and its share of Chinese rows either way.
- The exact size check of a table near the engine's limit happens in the App's pipeline
  with the engine itself, after the importer. The checker reports that state as a note.

## Known limits of the comparison

- `doesNotFitEngine` cannot be reached with ReRime's limits: a table needs two rows, and for
  two rows or more the whole-word index always passes the importer's exact test
  (`76 + 16·codes + 8·rows ≤ 32·codes + 64·rows`). The by-syllable "does not fit" branch is
  reached (`budget-syllable-does-not-fit`); such a table runs whole word.
- When two phrase-list forms each cover exactly half of a file's lines, the importer picks
  either one, differently from run to run (it takes the larger count from an unordered
  dictionary). The checker picks the first and prints a note. No corpus case has such a tie.
- Characters are judged with this Python's Unicode data and the importer's with the
  iPhone's. A character newer than the Python's data is reported as unassigned. The corpus
  uses only characters of Unicode 11 or earlier so that its results do not depend on that.
