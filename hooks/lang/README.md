# Languages

Baton itself is in English. You work in your own language: the agent translates what the
hooks say, and the words the hooks recognise in your logbooks and messages come from these
files. One file per language, named by its code: `en.json`, `bg.json`. **A new language is a
new file here; no code changes.**

The folder sits next to the hooks, so the plugin ships it and `install.sh` / `install.ps1`
copy it beside the installed hooks. Where it can compare (a plugin, or `source` set), the
session-start drift check names a file that is missing or differs.

## Adding a language

1. Copy `en.json` to `<code>.json` (for example `de.json`).
2. Translate the values of `board`. Leave the keys in English: they are what the board looks
   up. A key you leave out is shown in English.
3. Replace each list under `words` with the words of your language. Drop a slot you do not
   need; the other languages still cover it.
4. Run `python3 -m pytest -q tests/test_lang.py`.

With `board_language` set to your code in `baton.local.json` (or `--lang <code>`), the HTML
board uses your file. Every installed language is recognised at once.

## The sections

`board`: the HTML board's own words (`tools/baton_board.py`), English text -> translation.

`words`: what the hooks recognise. Each entry is a Python regular-expression fragment, matched
without regard to case. The fragments of all languages are joined with `|`, `en` first, then
the others by code, each file's order kept: the first fragment that matches wins, so put a
longer form before a shorter one that starts it.

| slot | where | it recognises |
|---|---|---|
| `changed` | Stop | a line of an entry that says a file was changed (wrote, fixed, added...) |
| `gone` | Stop | a line that says a file was deleted, moved or renamed |
| `visible` | Stop | a word saying something is public or private |
| `key` | Stop | "public key" / "private key": the cryptographic sense, not visibility |
| `claims_heading` | Stop | the heading of the claims section, after `### ` |
| `refuted` | Stop | the word that marks a claim as refuted, before `:` |
| `tests_pass` | Stop | a sentence claiming tests pass |
| `task_word` | prompt | the word for "task" before a task number (`task 12`) |

Rules for fragments:

- No capturing groups: write `(?:...)`. The hooks number their own groups.
- No named groups: `en.json` already uses `n` in `tests_pass`, and a second one with the
  same name breaks the whole pattern.
- Word boundaries are yours to add where your language needs them (`en` wraps its verbs in
  `\b...\b`; `bg` matches stems).
- A fragment that does not compile is skipped, and so is a file that is not valid JSON.

## Not in these files yet

The prompt hook's stemming of task names (`_VOWELS`, `_ENDINGS`, `_SHORT_ENDINGS` in
`baton_prompt.py`) is still in the code: it treats every Latin word as English and every
other word by Bulgarian endings, so it is a rule, not a word list. The logbook header's
Bulgarian names for states and priorities are still in `baton_session_start.py`.
