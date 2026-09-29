#!/usr/bin/env python3
"""Store the OpenRouter key the review needs, without it ever entering a conversation.

    python3 tools/baton_key.py          # asks for the key (not echoed), checks it, stores it
    python3 tools/baton_key.py --check  # checks the stored key: label, limit, spent -- never the key

Run the first form in your own terminal, not through the agent. A key typed into a chat, or
into a command whose output lands in one, is in the transcript from then on. The agent runs
`--check` afterwards; it prints nothing it could leak.

The key goes to ~/.config/baton/env (mode 600), which `baton_review` reads. Only the review
tools use it; the hooks never do.
"""
import argparse
import getpass
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ENV = Path.home() / ".config/baton/env"
KEY_INFO = "https://openrouter.ai/api/v1/key"


def stored() -> str:
    if ENV.is_file():
        for line in ENV.read_text(encoding="utf-8").splitlines():
            if line.startswith("OPENROUTER_API_KEY="):
                return line.split("=", 1)[1].strip()
    return ""


def info(key: str) -> dict:
    """OpenRouter's own description of the key. Raises with a reason, never with the key."""
    req = urllib.request.Request(KEY_INFO, headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.load(resp)["data"]
    except urllib.error.HTTPError as err:
        raise RuntimeError(f"OpenRouter refused the key (HTTP {err.code})") from None
    except (urllib.error.URLError, OSError, ValueError, KeyError) as err:
        raise RuntimeError(f"could not reach OpenRouter ({type(err).__name__})") from None


def describe(data: dict) -> str:
    # Not the `label`: for a key without a name OpenRouter's label is the key's own first
    # characters (`sk-or-v1-...`), and printing it was the first real run of this tool.
    limit = data.get("limit")
    return ("key OK — "
            f"limit {'none (set one on openrouter.ai)' if limit is None else f'${limit:.2f}'}, "
            f"spent ${data.get('usage', 0):.4f}")


def store(key: str) -> None:
    ENV.parent.mkdir(parents=True, exist_ok=True)
    kept = [l for l in ENV.read_text(encoding="utf-8").splitlines()
            if not l.startswith("OPENROUTER_API_KEY=")] if ENV.is_file() else []
    tmp = ENV.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("\n".join(kept + [f"OPENROUTER_API_KEY={key}"]) + "\n")
    os.replace(tmp, ENV)
    os.chmod(ENV, 0o600)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="check the stored key; prints no key")
    args = parser.parse_args(argv)

    if args.check:
        key = stored()
        if not key:
            print(f"no key stored in {ENV}")
            return 1
        try:
            print(describe(info(key)))
        except RuntimeError as err:
            print(err)
            return 1
        return 0

    if not sys.stdin.isatty():
        print("Run this in your own terminal: it asks for the key without showing it.")
        return 1
    key = getpass.getpass("OpenRouter key (not shown): ").strip()
    if not key:
        print("nothing entered, nothing stored")
        return 1
    try:
        data = info(key)
    except RuntimeError as err:
        print(f"{err} — nothing stored")
        return 1
    store(key)
    print(f"{describe(data)}\nstored in {ENV} (mode 600)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
