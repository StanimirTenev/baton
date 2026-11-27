# AGENTS.md — working in the Baton repository

For a coding agent (Codex, Claude Code, Cursor, any other) changing Baton's own code. Baton's
rules for *using* it are elsewhere: `templates/CLAUDE.md`, and the README.

## The hooks run from copies

What runs on a user's machine is never this checkout. As a plugin, Claude Code runs the copy in
its plugin cache (`~/.claude/plugins/cache/baton/baton/<version>/`); with the install script, the
copy in `~/.claude/baton/hooks/`; under Codex or Gemini, the copy their setup made. Editing a
file here changes nothing that runs until it is released and installed. Never edit an installed
copy to test a fix: SessionStart compares the running hooks with their source and reports a
difference, and a fix that lives only in a cache is lost at the next update.

## Do not touch without being asked

- `templates/CLAUDE.md` -- it is put into every session of every user (appended to `CLAUDE.md`
  by the installer, injected by the plugin). `codex/AGENTS.md.snippet` and
  `gemini/GEMINI.md.snippet` are byte-for-byte copies of it, held so by a test.
- The header parser (`parse_frontmatter` in `hooks/baton_session_start.py`) and its synonym maps.
  Every hook and tool reads the header through it; a second reader is a defect. The Bulgarian
  field names are read forever: never remove one.
- Anything that makes a hook touch the network. The hooks make no network request; only tools a
  person runs by hand do, and the README's network section says which.
- Dependencies. Baton is the Python standard library only, Python 3.8 or later
  (`tests/test_python_floor.py`).
- An existing logbook entry: entries are a record and are not edited. The ledger reports an edit.

## Before a pull request

```bash
python3 -m pytest tests/ -q          # the whole suite, about five minutes; all green
```

- A changed behaviour comes with a test that fails without the change. Revert the change and see
  the test fail before you rely on it.
- Run the hook the way the harness does (a subprocess fed JSON on stdin, as the tests do), not
  only the function.
- A new header field a hook reads must be described in the README or `docs/`:
  `tests/test_documented.py` fails otherwise. A changelog line is not documentation.
- A release bumps `.claude-plugin/plugin.json`, `gemini/gemini-extension.json`, `BATON_VERSION`
  in `hooks/baton_session_start.py` and the top of `CHANGELOG.md` together; tests hold them to
  each other and to the README's News list.
- Code, comments and the board are in English; a user's language is the agent's job, not the hook's.
