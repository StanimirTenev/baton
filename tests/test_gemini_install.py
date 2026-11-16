"""The Gemini CLI extension in gemini/: one set of hooks, the same rules text.

Gemini CLI 0.68.0 reads an extension's hooks only from `<extension>/hooks/hooks.json` and fills
`${extensionPath}` in them (bundle chunk-UWDUE2FI.js, loadExtensionHooks and hydrateString). The
repository root cannot be the extension, because its hooks/hooks.json is Claude Code's, so the
extension is gemini/ and its commands reach the shared hooks at `${extensionPath}/../hooks`. That
path holds only when the folder is linked in place (`gemini extensions link`, whose
extensionPath is the source folder), not copied (`install`): gemini/README.md says so.
Gemini reads `timeout` in milliseconds (hookRunner `setTimeout(..., timeout)`): Baton's 20 and 10
seconds killed every hook at 10-20 ms in the fixture run of 16.11.2026.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXT = ROOT / "gemini"
CMD = re.compile(r'sh "\$\{extensionPath\}/\.\./hooks/run\.sh" "\$\{extensionPath\}/\.\./hooks/(\w+\.py)"')
WANT = {"SessionStart": "baton_session_start.py", "BeforeAgent": "baton_prompt.py",
        "BeforeTool": "baton_pretool.py", "AfterAgent": "baton_stop.py"}


def _hooks():
    return json.loads((EXT / "hooks" / "hooks.json").read_text("utf-8"))["hooks"]


def _claude_seconds():
    """Each script's timeout in Claude Code's hooks/hooks.json, in seconds."""
    out = {}
    for groups in json.loads((ROOT / "hooks" / "hooks.json").read_text("utf-8"))["hooks"].values():
        for g in groups:
            for h in g["hooks"]:
                out[re.search(r"(\w+\.py)\"$", h["command"]).group(1)] = h["timeout"]
    return out


def test_the_manifest_is_a_valid_extension_with_the_plugin_s_version():
    m = json.loads((EXT / "gemini-extension.json").read_text("utf-8"))
    assert re.fullmatch(r"[a-zA-Z0-9-]+", m["name"])          # validateName in the bundle
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text("utf-8"))
    assert m["version"] == plugin["version"], "bump gemini/gemini-extension.json with the plugin"


def test_no_rules_file_is_loaded_unfilled():
    """With no contextFileName, Gemini loads <extension>/GEMINI.md if it exists. The template
    there would reach the model with `$BATON_HOME (default ~/tasks)` unfilled, the v3.8.3 bug;
    the rules are installed with _install_rules.py instead (gemini/README.md, step 4)."""
    m = json.loads((EXT / "gemini-extension.json").read_text("utf-8"))
    assert "contextFileName" not in m
    assert not (EXT / "GEMINI.md").exists()


def test_the_snippet_is_the_template():
    assert (EXT / "GEMINI.md.snippet").read_bytes() == (ROOT / "templates" / "CLAUDE.md").read_bytes()


def test_the_four_gemini_events_each_start_a_shared_hook_through_run_sh():
    hooks = _hooks()
    assert set(hooks) == set(WANT), "Gemini has no PostToolBatch, StopFailure or SubagentStop"
    seconds = _claude_seconds()
    for event, script in WANT.items():
        (group,) = hooks[event]
        (handler,) = group["hooks"]
        m = CMD.fullmatch(handler["command"])
        assert m and m.group(1) == script, handler["command"]
        hydrated = handler["command"].replace("${extensionPath}", str(EXT))
        for path in re.findall(r'"([^"]+)"', hydrated):
            assert Path(path).resolve().is_file(), path
        assert handler["type"] == "command"
        assert handler["timeout"] == seconds[script] * 1000, f"{event}: milliseconds, not seconds"


def test_before_tool_matches_gemini_s_write_and_shell_tools_only():
    """Names from the bundle: WRITE_FILE_TOOL_NAME, EDIT_TOOL_NAME, SHELL_TOOL_NAME. HookPlanner
    tests the matcher as `new RegExp(matcher).test(toolName)`, so it is anchored."""
    (group,) = _hooks()["BeforeTool"]
    pat = re.compile(group["matcher"])
    for name in ("write_file", "replace", "run_shell_command"):
        assert pat.search(name), name
    for name in ("read_file", "read_many_files", "list_directory", "activate_skill",
                 "mcp_fs_write_file", "replace_all", "Write", "Bash"):
        assert not pat.search(name), name
