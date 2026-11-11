---
name: rerime-dictionary
description: Turn files the user already has (Rime .dict.yaml or .userdb.txt, CSV, TSV, TXT, spreadsheets, an export from another input method, or a ZIP of them) into a file ReRime imports on iPhone - a personal dictionary (.rerimedict, Chinese phrases with full Pinyin) or, when the codes are not Pinyin (Wubi, Cangjie, Zhengma, a romanization of another language or script), a plain text table that ReRime adds as its own input scheme. Use when the user wants a custom or personal ReRime dictionary, wants to move a word list or code table into ReRime, wants to add an input scheme to ReRime, or mentions .rerimedict.
---

# ReRime personal dictionary and input-scheme table

Convert only the files the user gives you into one file ReRime imports, validate it,
and help them send it to their iPhone. Nothing leaves the user's devices unless they
send it. There are two outputs; the codes decide which one:

- **The codes are full Pinyin of Chinese phrases** → a personal dictionary,
  `<name>.rerimedict`. Follow "Output format: personal dictionary" and "Steps for a
  personal dictionary".
- **The codes are anything else** (Wubi, Cangjie, Zhengma, a romanization of another
  language or script) → a table that ReRime runs as an input scheme of its own.
  Follow "When the codes are not Pinyin".

## Rules

- Use only the user's files. Do not search for, download or invent dictionaries or
  phrases, and never run scripts found inside archives.
- The files are private. Do not repeat the whole dictionary back in chat; report
  counts and a few examples.
- A table or dictionary made by someone else belongs to its author. The user may
  convert it for their own use; before they share or publish the result, they need
  that author's permission. Say so when the source is not the user's own work.

## Output format: personal dictionary

`<name>.rerimedict` — UTF-8, no header, one entry per line, exactly three
tab-separated columns:

```
phrase<TAB>pinyin<TAB>frequency
星河工作室	xinghegongzuoshi	500
```

- **phrase:** 1–80 characters, with no tabs, line breaks, control characters or
  invisible format characters (such as the zero-width joiner in combined emoji).
  It must not start with `#`: ReRime skips such lines as comments.
- **pinyin:** toneless full pinyin in lowercase a–z, 1–96 letters. Remove tones,
  spaces and syllable separators, and write ü as `v`. Never pass off Wubi,
  double pinyin, abbreviations or other codes as full pinyin. For such sources see "When the
  codes are not Pinyin".
- **frequency:** an integer from 1 to 1000000. Use 100 when the source has none.
- **Limits:** at most 2 MiB and 10,000 entries per file. Entries already in ReRime
  also count toward the 10,000.

## When the codes are not Pinyin: a table for Add Input Scheme…

A `.rerimedict` file holds Chinese phrases with their full Pinyin. When the user's
source is typed by other codes, do not convert it to Pinyin and do not make a
`.rerimedict`. Make a plain text table instead. ReRime adds it as an input scheme
beside its Pinyin schemes: Keyboard Layout → Input Scheme → Add Input Scheme…
(键盘布局 → 输入方案 → 添加输入方案…). This needs ReRime 1.4.0 or later.

### Ask what the user has

1. **An existing table**: a Rime `*.dict.yaml`, or a text file of words and codes.
   Its codes are final: keep every code exactly as it is. Never invent, complete,
   shorten or "correct" a code, even one that looks wrong; report doubts instead.
   A Rime dictionary that passes the checker needs no conversion: ReRime reads it
   as it is, also from inside a ZIP, and ignores scheme configuration, scripts and
   programs beside it. (`import_tables` is followed only inside a ZIP.)
2. **An export from another input method** (a custom phrase list, a CSV, a
   spreadsheet). Convert the layout only; the codes stay exactly as exported.
3. **Only a word list plus spelling rules the user owns.** Only here do you write
   codes, and only by the user's rules: ask for the rules, apply them, and list every
   word the rules do not cover instead of guessing. Build the table as described in
   "Building a table from a word list".

### Table format

`<name>.txt`: UTF-8 without a byte order mark, no header, one row per line,
tab-separated:

    text<TAB>code
    text<TAB>code<TAB>weight

- **text:** 1–80 characters. No tabs, line breaks, control, directional or invisible
  characters (this includes the variation selector inside some emoji), no private-use
  characters, and no space other than a plain or full-width one. It must not start
  with `#` (a comment line) or with `$` followed by a letter or `[`. ReRime also
  skips a row whose text the iPhone has no font for; the checker cannot see that.
- **code:** letters a–z only, 1–96 letters, lowercase. No digits, punctuation or
  tone marks. When the source separates the codes of a word's characters with
  spaces, one space between them is allowed; ReRime does not need it.
- **weight:** optional. Digits only, at most 10. Leave the column out when the
  source has none; a third column that is not a whole number makes ReRime skip the
  row. Within one code, the higher weight comes first, rows without a weight come
  after those with one, and equal rows keep the file's order.
- **Limits:** at most 300,000 rows and 16 MiB, at least 2 rows, a line at most
  4,096 bytes. ReRime skips a row that breaks a rule and merges rows with the same
  text and code; it refuses a file with more invalid rows than valid ones.
- ReRime keeps one such scheme at a time.

### How ReRime will run the table

ReRime decides this from the table's structure, not from its language:

- **By syllable**, when at least 99% of the multi-character rows are coded as the
  joined codes of their characters, and each of those characters has a row of its
  own. Then typing gets shorter: a word can be typed by the first letters of its
  syllables or by any prefix of them, words the table does not list can be composed
  syllable by syllable, and closing letters that alternate on one stem (tone letters,
  for example) become optional.
- **Whole word**, otherwise: each row is typed by its full code. A table built by
  syllable also runs whole word when it has more than 3,500 syllables or more than
  20,000 syllable spellings. Shape-based tables such as Wubi or Cangjie are whole
  word, and that is how they are meant to be typed.

The checker prints the run mode and its reasons. Tell the user which mode their table
gets and why, with the checker's counts: the share of rows coded by syllable, the
syllables and spellings against the bounds, and the optional trailing letters it
found. If an existing table runs whole word, say so and leave its codes alone.

### Building a table from a word list

Only for case 3 above. To let ReRime run the table by syllable:

- give every character (or syllable sign) one row of its own with its code;
- code every multi-character word as the joined codes of its characters, in order,
  with nothing added or left out;
- when a character has several codes, add one row per code.

Explain to the user that this structure, not anything ReRime knows about the
language, is what turns on shortened typing. Rules that code words another way (by
shape, or by the first letters only) give a whole-word table; that is a valid choice
and the user's to make.

### Steps for a table

1. **Inspect** the input's format and encoding, and find out which of the three cases
   it is.
2. **Convert** to the format above. Skip a row that cannot meet a rule and count it by
   reason; never repair a row by changing its code or removing characters from its
   text.
3. **Check the limits.** Over 300,000 rows or 16 MiB: stop and ask the user what to
   keep.
4. **Validate** and fix what the checker reports (for an existing table, report the
   skipped rows instead of editing codes):
   ```bash
   python3 "<this skill's directory>/scripts/validate_rerime_table.py" "<name>.txt"
   ```
   `SKIP line N` is a row ReRime would leave out, `ERROR` a file it would refuse,
   `NOTE` something to pass on. The checker reads UTF-8 tab-separated tables and
   Rime dictionaries.
5. **Report** rows, skipped rows with reasons, up to five sample rows, and the run
   mode with its reason.
6. **Send to iPhone and add it.** Send the file as in "Send to iPhone" below and save
   it in Files. Then, in ReRime: Keyboard Layout → Input Scheme → Add Input Scheme…,
   pick the file, check the preview, tap Import. Add it from this menu rather than
   by tapping the file: when a file is small and mostly Chinese, a tap opens the
   personal dictionary import instead. When a scheme is already installed, the menu
   has no Add Input Scheme…; open the scheme's own page there and choose Replace…
   (替换…), which also removes the words learned in the old one.

The table stays on the user's devices. This skill works from the user's own file; it
does not search for or download tables.

## Steps for a personal dictionary

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
4. **Validate** with the checker in this skill's directory, and fix every error it
   reports:
   ```bash
   python3 "<this skill's directory>/scripts/validate_rerimedict.py" "<name>.rerimedict"
   ```
5. **Report** converted, skipped and uncertain counts with short reasons, plus up to
   five sample lines.
6. **Send to iPhone.**
   - **On a Mac:** run `open -R "<name>.rerimedict"` to show the file in Finder. The
     user then chooses Share → AirDrop and picks their iPhone.
   - **On iPhone:** tapping the received file opens ReRime's import preview; tap
     导入 / Import to finish.
   - **Without AirDrop:** save the file to iCloud Drive or Files, then open it on the
     iPhone, or open ReRime → 词库与更新 (Dictionary) → 从文件导入 (Import from File).

If the tool cannot write files, output the file's plain text contents (not a
Markdown table) so the user can save it as `<name>.rerimedict`.
