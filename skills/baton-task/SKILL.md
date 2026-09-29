---
name: baton-task
description: Form the task before researching or acting on it. Recognise when a conversation has become a task or a decision, read back what was already done and decided, and write the goal and a checkable criterion of done into the logbook header. Use at the start of any new piece of work, when the human says "let's do X" or makes a choice between options, when a message names an existing task, and before handing a large goal to /baton-plan (/baton:baton-plan when installed as a plugin).
---

# Baton task — form it before you research it

Research answers a question. If the question was never stated, the research answers the
one the agent assumed, and the logbook records work on a task nobody defined. This skill
is the step before: four moves, in order, each one there because skipping it cost something.

Output in the human's language. The field names stay as they are.

---

## 1. Recognise — has this become a task?

A conversation turns into a task or a decision without announcing it. The signals:
a choice between options ("let's go with the first"), a priority ("give priority to 1 and 2"),
money or a deadline, "let's do it", "plan it", or a new name for a body of work.

When you see one, say so in one line and ask whether to record it — **do not record it on
your own, and do not plan it yet** unless asked.

> Paid for on 2026-09-28: a conversation opened with "we are only thinking aloud" and ended
> in a decision on which work comes first. Nobody said "this is a decision" until the agent
> did, three messages late.

## 2. Read back — what was already done and decided?

Before proposing anything:
- Is there a task folder? `ls -t` the task root; the UserPromptSubmit hook names folders a
  message touches, but it matches words, not meaning — look yourself too.
- Read the logbook **on this topic**, not the top entry. Search it for the subject.
- Read the memory entries that point at it, and any open plan (`PLAN*.md`).
- Collect: decisions already taken, claims already refuted, work already finished.

> Paid for on 2026-09-28: the agent proposed reviewing 42 candidates. They had been reviewed
> two days earlier; the review was four entries below the one it read.

**If the last entry is a week old or more and the next move is not ours** (`turn` names an
outsider, a delivery, a reply), **ask the human first: "what happened outside the logbook?"** —
then propose. A logbook records sessions; it cannot record a disk that was returned, an email
sent from a phone, or a timer switched off on another machine.

**Say the next move in words the human understands without the logbook.** Not "decide gate #4",
but what it means: "is the rule 'no selling until the article is out' still in force?"

> Measured on 2026-09-29, six tasks idle for a week or more, each resumed in a fresh session:
> 6/6 answered in under a minute, but only 1/6 was right. Three misses were events outside any
> session (a disk returned, timers switched off, an email already sent); one was the logbook's
> own shorthand, which the human no longer recognised. Speed was never the problem; stale state was.

## 3. Formulate — goal, criterion, who decides

Write, in the human's words wherever possible:

| field | what goes in |
|---|---|
| `goal` | the goal in one sentence — what is different when it is done |
| `done_when` | one sentence a person could check: a number, a page that exists, a yes from someone |
| `turn` | who holds the next move: `us`, the human, or a named outsider |
| `next` | one sentence: the next move, not a summary |
| `aliases` | the words people will use for it, **in every alphabet they write in** — the prompt hook matches on these |

And in the first logbook entry: what is known — checked against a source or on the spot — and what is not: an agent's word, or an inference.
If the criterion is not known, **ask**. The Stop hook asks once per session when a task
worked on has none; an invented criterion is worse than a missing one, because it is
then trusted.

## 4. Only then — outward

Small and clear: do it. Large, several directions, or unknown ground: `/baton-plan`
(`/baton:baton-plan` as a plugin), which
starts from the goal you have just written instead of inventing one.

---

## What this skill does not do

It does not decide priorities between tasks, and it does not change other tasks' headers.
If forming this task implies another one moves down, name it and ask.
