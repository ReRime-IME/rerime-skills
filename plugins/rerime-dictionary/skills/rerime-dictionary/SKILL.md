---
name: rerime-dictionary
description: Turn dictionary files the user already has (Rime .dict.yaml or .userdb.txt, CSV, TSV, TXT, spreadsheets, or a ZIP of them) into a ReRime personal dictionary file (.rerimedict) that imports on iPhone with one tap, usually sent by AirDrop. Use when the user wants a custom or personal ReRime dictionary, wants to move a word list into ReRime, or mentions .rerimedict.
---

# ReRime personal dictionary

Convert only the files the user gives you into one `.rerimedict` file, validate it,
and help them send it to their iPhone. ReRime opens the file directly into its
import preview; nothing leaves the user's devices unless they send it.

## Rules

- Use only the user's files. Do not search for, download or invent dictionaries or
  phrases, and never run scripts found inside archives.
- The files are private. Do not repeat the whole dictionary back in chat; report
  counts and a few examples.

## Output format

`<name>.rerimedict` — UTF-8, no header, one entry per line, exactly three
tab-separated columns:

```
phrase<TAB>pinyin<TAB>frequency
星河工作室	xinghegongzuoshi	500
```

- **phrase:** 1–80 characters, no tabs or line breaks.
- **pinyin:** toneless full pinyin in lowercase a–z, 1–96 letters. Remove tones,
  spaces and syllable separators, and write ü as `v`. Never pass off Wubi,
  double pinyin, abbreviations or other codes as full pinyin.
- **frequency:** an integer from 1 to 1000000. Use 100 when the source has none.
- **Limits:** at most 2 MiB and 10,000 entries per file. Entries already in ReRime
  also count toward the 10,000.

## Steps

1. **Inspect.** Identify each input's format and encoding (for example GB18030,
   UTF-16 or UTF-8 with a BOM). For a ZIP, list its contents and read only
   dictionary-like files.
2. **Convert** to the format above.
   - Keep the source's frequency when it has one; otherwise use 100.
   - Deduplicate on phrase plus pinyin. The highest frequency wins; say so in the report.
   - When a polyphonic reading or a code is uncertain, put it in the report rather
     than guessing.
3. **Check the limits.** If the output would pass 2 MiB or 10,000 entries, stop and
   ask the user what to keep. Never truncate silently.
4. **Validate** with the bundled checker, and fix every error it reports:
   ```bash
   python3 scripts/validate_rerimedict.py "<name>.rerimedict"
   ```
5. **Report** converted, skipped and uncertain counts with short reasons, plus up to
   five sample lines.
6. **Send to iPhone.**
   - **On a Mac:** run `open -R "<name>.rerimedict"` to show the file in Finder. The
     user then chooses Share → AirDrop and picks their iPhone.
   - **On iPhone:** tapping the received file opens ReRime's import preview; tap
     导入 / Import to finish.
   - **Without AirDrop:** save the file to iCloud Drive or Files, then open it on the
     iPhone, or use ReRime → 词库 → 从文件导入.

If the tool cannot write files, output the file's plain text contents (not a
Markdown table) so the user can save it as `<name>.rerimedict`.
