"""Review of 3.41.0 (19.11.2026): a CHANGELOG.md that is not valid UTF-8 raised UnicodeDecodeError
out of release_leads, and that session got no board. It now falls back to no leads."""
import importlib.util
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_release_leads_survive_a_changelog_that_is_not_utf8(tmp_path):
    (tmp_path / "hooks").mkdir()
    shutil.copy(ROOT / "hooks" / "baton_session_start.py", tmp_path / "hooks")
    for f in (ROOT / "hooks").glob("*.py"):
        shutil.copy(f, tmp_path / "hooks")
    (tmp_path / "CHANGELOG.md").write_bytes(b"\xff\xfe\x00**v3.41.0** \x80\x81")
    spec = importlib.util.spec_from_file_location("ss_copy", tmp_path / "hooks" / "baton_session_start.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.release_leads("3.41.0") == []
