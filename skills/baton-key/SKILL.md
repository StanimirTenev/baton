---
name: baton-key
description: Walk the human through getting an OpenRouter key and storing it for Baton's review tools (baton_review, baton_sift, baton_corpus), without the key ever entering the conversation. Use when a review tool says "NO key", when the human asks how to set up the key, or before a first review run.
---

# Baton key — the human gets it, the agent never sees it

Only the review tools need a key. The hooks never do, and nothing else in Baton calls out.
Say that first: a human who only wants the logbooks can stop here.

Output in the human's language. Commands stay as they are.

## The one rule

**The key is never typed into this conversation, and never into a command you run.** Anything
in the chat, or in the output of a command run from it, stays in the transcript. If the human
pastes a key anyway: tell them to delete that key on openrouter.ai and create a new one. Do not
use the pasted one.

## Steps — give them one at a time, and wait for "done" after each

1. **Account.** Open https://openrouter.ai and sign in (Google, GitHub or e-mail).
2. **Credit.** Account menu → *Credits* → add a small amount. For scale, measured by the
   author: one review of an index costs about **$0.0013**; labelling 185 repositories cost
   **$3.39**. A few dollars last a long time.
3. **Key.** Account menu → *Keys* → *Create Key*. Give it a name (e.g. `baton`) and **a credit
   limit** — the most it may ever spend. Copy the key; OpenRouter shows it only once.
4. **Store it — in their own terminal, not here.** The repository path is `repo` in
   `~/.claude/baton/hooks/baton.local.json` (the installer writes it). If that folder is gone,
   they download Baton again from https://github.com/StanimirTenev/baton. Give them:

   ```
   python3 <repo>/tools/baton_key.py
   ```

   (`python` instead of `python3` on Windows.) It asks for the key without showing it, checks
   it with OpenRouter, and stores it in `~/.config/baton/env`, readable only by them. A refused
   key is not stored.
5. **Check — you run this one.** `python3 <repo>/tools/baton_key.py --check` prints the limit
   and what has been spent, and never the key. Report both. If the limit says `none`, suggest
   setting one on the *Keys* page.

## If something goes wrong

- *"Run this in your own terminal"* — the command was run where it cannot ask privately
  (through the agent, or with piped input). Step 4 again, in a real terminal window.
- *"OpenRouter refused the key (HTTP 401)"* — copied incompletely, or deleted. Create a new one.
- *"could not reach OpenRouter"* — network or proxy; nothing was stored. Try again later.
- A key in `OPENROUTER_API_KEY` in the environment takes precedence over the stored one.
