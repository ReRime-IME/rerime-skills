# ReRime Skills

Open skills for AI agents that work with [ReRime](https://github.com/ReRime-IME).

## rerime-dictionary — 用 AI 制作自己的词库

Give your agent the word lists you already have (Rime `.dict.yaml` / `.userdb.txt`,
CSV, TSV, TXT, spreadsheets or a ZIP). It builds a `.rerimedict` file, validates it,
and helps you AirDrop it to your iPhone. Tap the file on iPhone and ReRime shows the
import preview.

### Claude Code

```
/plugin marketplace add ReRime-IME/rerime-skills
/plugin install rerime-dictionary@rerime-skills
```

Then ask, for example: “把 ~/Downloads/我的词库.xlsx 做成 ReRime 词库”.

### Other agents

Copy `plugins/rerime-dictionary/skills/rerime-dictionary` into your agent's skills
folder (for example `~/.codex/skills/`). It is a plain `SKILL.md` with one checker script.

### File format

UTF-8, no header, `phrase<TAB>pinyin<TAB>frequency` per line, for example
`星河工作室	xinghegongzuoshi	500`. The limits are:

- a phrase is at most 80 characters;
- pinyin is 1–96 lowercase letters;
- frequency is an integer from 1 to 1,000,000;
- a file is at most 2 MiB and 10,000 entries.

Your files stay on your devices. The skill converts only what you give it.
