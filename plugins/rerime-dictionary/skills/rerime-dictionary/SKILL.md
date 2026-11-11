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
   Run the checker on the file as it is first (see "What ReRime reads as it is"):
   a file that passes needs no conversion.
2. **An export from another input method** (a custom phrase list, a CSV, a
   spreadsheet). Check it as it is first: ReRime reads Baidu and Sogou style phrase
   lists directly. Otherwise convert the layout only; the codes stay exactly as
   exported.
3. **Only a word list plus spelling rules the user owns.** Only here do you write
   codes, and only by the user's rules: ask for the rules, apply them, and list every
   word the rules do not cover instead of guessing. Build the table as described in
   "Building a table from a word list".

### What ReRime reads as it is

ReRime recognises a file by its content, not by its name, and the checker reads the
same files the same way. Give the checker the user's own file before converting
anything; when it reports no skipped rows and no error, the file can go to the
iPhone unchanged.

- **Encodings:** UTF-8, UTF-16 (with or without a byte order mark) and GB18030
  (which covers GBK and GB2312). Other encodings, UTF-32 included, are refused.
- **A Rime dictionary** (`*.dict.yaml`): the header's `columns` gives the order;
  `sort: original` keeps the file's order within a code. `import_tables` is followed
  only inside a ZIP.
- **A plain table**, tab-separated or separated by spaces, with the text or the
  code first (the column that is all letters is the code) and an optional weight.
  One tab anywhere makes the whole file tab-separated. In the space-separated shape
  a line `code word1 word2 …` is one row per word. Rows before a line `[DATA]` or
  `[数据]` are not read.
- **A phrase list** exported by another input method, in one of three forms:
  `code=1,phrase` (Baidu phone, QQ, iFlytek), `code,1=phrase` (Sogou) or
  `1,code=phrase` (Baidu PC). The number orders the phrases of one code. A phrase
  that continues on other lines, or a dynamic value that starts with `#`, is skipped.
- **A ZIP** that holds any of these. ReRime opens only members named `*.dict.yaml`,
  `*.yaml`, `*.txt`, `*.tsv` or `*.ini`, extracts nothing, and ignores scheme
  configuration, scripts, programs and fonts. It refuses a ZIP whose tables are
  password-protected, a ZIP larger than 64 MiB, one with more than 512 files or a
  table over 16 MiB, one with a path that leaves the archive, and one that is
  irregular in other ways. When a ZIP holds several tables ReRime asks which one to
  add (the one a scheme file names comes first); the checker lists them and checks
  the first, or the one given with `--table ID`.

Not accepted: scheme files, compiled or binary dictionaries (`.bin`, `.scel`, …),
and any file whose first bytes are those of a picture, document or program.

### Table format

When you write or convert a table yourself, write this one form.
`<name>.txt`: UTF-8 without a byte order mark, no header, one row per line,
tab-separated. **Name the file as the scheme should be called**: ReRime fills the
scheme's name from the file's name without its extension (from `name:` for a Rime
dictionary). The name is shown on the Space key and holds at most 16 characters;
ask the user what to call the scheme, and keep it short.

    text<TAB>code
    text<TAB>code<TAB>weight

- **text:** 1–80 characters (as a person counts them: a letter with its marks is
  one). No tabs, line breaks, control, directional or invisible
  characters (this includes the variation selector inside some emoji), no private-use
  characters, and no space other than a plain or full-width one. It must not start
  with `$` followed by a letter or `[`. ReRime also skips a row whose text the
  iPhone has no font for (rare scripts, very new characters); the checker cannot see
  that, so its row counts are an upper bound for such text and it prints a note.
- **A line that starts with `#` is a comment, not a row.** ReRime does not import
  it and does not count it as skipped, and the checker prints no `SKIP` for it: a
  word that really starts with `#` disappears without a trace. The checker prints
  a `NOTE` for `#` lines that look like rows; report those to the user as words
  ReRime cannot take.
- **code:** letters a–z only, 1–96 letters, lowercase. No digits, punctuation or
  tone marks. When the source separates the codes of a word's characters with
  spaces, one space between them is allowed; ReRime does not need it.
- **weight:** optional. Digits only, at most 10. Leave the column out when the
  source has none. A third column that is not a whole number (`1.5`, `high`) makes
  ReRime skip the row. A whole number of more than 10 digits does not: ReRime keeps
  the row and ignores the weight (the checker prints a `NOTE`). Within one code, the higher weight comes first, rows without a weight come
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
- **Whole word**, otherwise: each row is found by its own code. The beginning of a
  code already offers the rows whose codes start with it, and full codes typed one
  after another compose a word. What whole word does not have is what by syllable
  adds: typing a word by the first letters of its syllables, and leaving out
  closing letters. A table built by syllable also runs whole word when it has more
  than 3,500 syllables or more than 20,000 syllable spellings. Shape-based tables
  such as Wubi or Cangjie are whole word, and that is how they are meant to be
  typed.

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
   it is. Run the checker on the file as it is: if ReRime reads it without skipping
   anything, go to step 5 with the user's own file.
2. **Convert** to the format above when the file is not read as it is, or when the
   user wants its skipped rows fixed. Skip a row that cannot meet a rule and count it
   by reason; never repair a row by changing its code or removing characters from
   its text.
3. **Check the limits.** Over 300,000 rows or 16 MiB: stop and ask the user what to
   keep.
4. **Validate** and fix what the checker reports (for an existing table, report the
   skipped rows instead of editing codes):
   ```bash
   python3 "<this skill's directory>/scripts/validate_rerime_table.py" "<name>.txt"
   ```
   `SKIP line N` is a row ReRime would leave out, `ERROR` a file it would refuse,
   `NOTE` something to pass on (how the file was read, for example), `Name:` what
   ReRime will call the scheme. The checker reads everything listed in "What ReRime
   reads as it is", a ZIP included.
5. **Report** rows, skipped rows with reasons, up to five sample rows, the run mode
   with its reason, the scheme's name, and every `NOTE`: `#` lines that look like
   rows, ignored weights, and, when the checker says the iPhone may import fewer
   rows, that the count is an upper bound.
6. **Send to iPhone and add it.** Send the file as in "Send to iPhone" below and save
   it in Files. Then, in ReRime: Keyboard Layout → Input Scheme → Add Input Scheme…,
   pick the file, check the preview (the name can be edited there), tap Import. Add
   it from this menu rather than
   by tapping the file: when a file is small and mostly Chinese, a tap opens the
   personal dictionary import instead. When a scheme is already installed, the menu
   has no Add Input Scheme…; open the scheme's own page there and choose Replace…
   (替换…), which also removes the words learned in the old one. A replaced scheme
   keeps the installed scheme's name, whatever the new file is called; to rename
   it, edit the name in the preview or on the scheme's page.

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
