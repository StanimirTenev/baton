"""#10: the entry carries "Corrections" (done vs asked) and "Changed: old → new", and says
secrets become [secret removed] -- in every place an agent learns the entry's shape: the
logbook template, the rules (installer and plugin), and the README."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_every_place_that_teaches_the_entry_has_the_new_sections():
    for rel in ("templates/LOGBOOK.md", "templates/CLAUDE.md", "README.md"):
        text = (ROOT / rel).read_text("utf-8")
        assert "### Corrections" in text, rel
        assert "### Changed: old → new" in text, rel
        assert "[secret removed]" in text, rel
