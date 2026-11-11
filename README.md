# ReRime Skills

Open skills for AI agents that work with [ReRime](https://github.com/ReRime-IME).

## rerime-dictionary — 用 AI 制作自己的词库

Give your agent the word lists you already have (Rime `.dict.yaml` / `.userdb.txt`,
CSV, TSV, TXT, spreadsheets or a ZIP). It builds a `.rerimedict` file, validates it,
and helps you AirDrop it to your iPhone. Tap the file on iPhone and ReRime shows the
import preview.

When your file is typed by codes that are not Pinyin (Wubi, Cangjie, a romanization
of another language), the same skill builds a table that ReRime adds as an input
scheme of its own: see [Codes that are not Pinyin](#codes-that-are-not-pinyin).

### Claude Code

```
/plugin marketplace add ReRime-IME/rerime-skills
/plugin install rerime-dictionary@rerime-skills
```

Then ask, for example: “把 ~/Downloads/我的词库.xlsx 做成 ReRime 词库”.

### Other agents

Copy `plugins/rerime-dictionary/skills/rerime-dictionary` into your agent's skills
folder (for example `~/.codex/skills/`). It is a plain `SKILL.md` with two checker scripts.

### File format

UTF-8, no header, `phrase<TAB>pinyin<TAB>frequency` per line, for example
`星河工作室	xinghegongzuoshi	500`. The limits are:

- a phrase is at most 80 characters, has no control characters and does not start
  with `#` (ReRime reads such lines as comments);
- pinyin is 1–96 lowercase letters;
- frequency is an integer from 1 to 1,000,000;
- a file is at most 2 MiB and 10,000 entries.

Check a file before sending it:

```bash
python3 plugins/rerime-dictionary/skills/rerime-dictionary/scripts/validate_rerimedict.py 我的词库.rerimedict
```

### Codes that are not Pinyin

A table typed by its own codes (Wubi, Cangjie, Zhengma, a romanization of another
language or script) is not a `.rerimedict`. The skill writes it as a plain text file,
`text<TAB>code` per line with an optional third column for a weight, for example
`星河	xhe`. ReRime 1.4.0 or later adds it as an input scheme beside its Pinyin schemes.
The limits are:

- a code is lowercase letters a–z, at most 96;
- a text is at most 80 characters, with no control or invisible characters;
- a weight, when present, is a whole number of at most 10 digits;
- a file is UTF-8, at most 16 MiB and 300,000 rows, and has at least 2 rows.

ReRime also reads many existing files as they are, and the checker reads them the same
way: UTF-8, UTF-16 or GB18030 text; a Rime dictionary (`*.dict.yaml`); a plain table
separated by tabs or spaces with the text or the code first; a Baidu or Sogou style
phrase list (`code=1,phrase`, `code,1=phrase`, `1,code=phrase`); and a ZIP that holds
one of these. A file that passes the checker needs no conversion. The skill keeps the
codes of an existing table exactly as they are.

ReRime decides from the table's structure how to run it. When multi-character words
are coded as the joined codes of their characters, and each character has a row of
its own, the table runs **by syllable**: words can be typed by first letters or
prefixes, and closing letters such as tone letters become optional. Otherwise, or
with more than 3,500 syllables or 20,000 syllable spellings, it runs **whole word**:
each row is found by its own code (the beginning of a code already offers matching
rows, and full codes typed in a row compose), without first-letter typing.

Check a table before sending it. The checker lists the rows ReRime would skip, says how
the file was read when that is not the plain form, and says which way the table will run
and why. For a ZIP with several tables it lists them and checks the one ReRime
preselects; `--table ID` checks another.

```bash
python3 plugins/rerime-dictionary/skills/rerime-dictionary/scripts/validate_rerime_table.py 我的方案.txt
```

```
OK 40 rows, 493 bytes
Name: 我的方案 (from the file's name; shown on the Space key, editable in ReRime's preview; Replace… keeps the installed scheme's name)
Run mode: by syllable
  10 of 10 multi-character rows are coded as the joined codes of their characters (ReRime needs 99%)
  30 syllables (at most 3,500), 90 spellings (at most 20,000)
  optional trailing letters: p, t, x (a syllable can be typed without them)
```

Name the file as the scheme should be called (at most 16 characters; it is shown on the
Space key). The checker cannot know which characters an iPhone can draw: for rare
scripts ReRime may import fewer rows than the checker reports, and the checker says so.
A line that starts with `#` is a comment: ReRime neither imports it nor counts it as
skipped.

On the iPhone, save the file in Files, then open ReRime → Keyboard Layout → Input
Scheme → Add Input Scheme… and pick it. ReRime keeps one such scheme at a time;
replacing it keeps the installed name unless you edit it in the preview.

Before you share a table that someone else made, ask its author for permission.

### Tests

```bash
python3 -m unittest discover -s tests -v
```

The fixtures in `tests/fixtures` are synthetic: invented codes, not a real input scheme.

The table checker is compared with ReRime's own importer (the App's Swift code) on a
generated corpus of 383 files; the importer's answers are kept in
`tests/parity/expected.json` and the tests require the checker to give the same.
[tests/parity/README.md](tests/parity/README.md) says what is compared and how to run
the comparison again with the App's source.

Your files stay on your devices. The skill converts only what you give it.

## License

Apache-2.0
