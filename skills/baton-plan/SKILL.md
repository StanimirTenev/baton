---
name: baton-plan
description: Start a large or multi-direction task the Baton way. Set the goal first, run up to two parallel research rounds from several angles, keep facts with sources apart from open questions, and build the plan backwards from the goal, re-planning after each round with the human at every checkpoint. Use when a new goal arrives ("we want to start selling X", "launch Y") or when asked to research and plan before acting.
---

# Baton plan — goal → research rounds → plan

A big task fails in two quiet ways. It is planned from what the agent already believes,
or it is researched with no question in mind. This skill runs a loop that avoids both:

**goal → questions → research round → verified facts → plan vN → human decides → next round**

It stops when no open question still blocks the plan, or after **2 rounds**. Two rounds
are the default because the second already changes the plan substantially and a third
returns less than it costs; run a third only if the human asks for it. What is still
unclear by then goes to the human as a decision, or into the plan as a task (a cheap
test, a question for a lawyer). After that the plan is **executed**, not researched further.

Task root and logbook name come from `~/.claude/baton/hooks/baton.local.json` (`home`,
`logbook`). The files below are written into `<task root>/<task>/`.

## Before you run this at all: is it a swarm question?

Baton has two paths, and this skill is the expensive one. Most work is not this.

**The direct path** is what the hooks already enforce and needs no skill: read the task's
logbook, do the work, write the entry. One letter, one fix, one decision, one measurement you
can take yourself. It costs what the work costs.

**The swarm** — this skill — runs 6 to 10 agents a round. Measured: a seven-agent round came to
roughly 1.3 million tokens and 30 minutes; a four-agent round, 660 thousand. That is the price,
and it should be spent deliberately rather than by habit.

Take the swarm when one of these is true:

- **there is something to measure** — a corpus, a rival tool, a number somebody else published;
- **there is a written claim to attack** — ours or theirs, that a round can confirm or refute;
- **the angles are genuinely parallel** and one agent would have to do them in series anyway.

Take the direct path when:

- **it is judgement** — a price, a name, a letter, whether to build something. A swarm returns
  opinions here, and opinions do not get better by being seven;
- **it is one thing** — a fix, a reply, a release;
- **there is nothing on disk and nothing published to check against.** A round with no source
  produces confident prose, which is worse than an honest "we do not know".

The test that has held so far: *what would the round check its answer against?* If there is no
answer to that, the round will not produce a fact — it will produce a longer file.

## 0. Formulate the goal (with the human, before any agent runs)

1. **The expected result.** Make it concrete and checkable. "First paid order, then
   recurring sales" is a goal; "a page is live" is only a step toward one. This becomes
   `kriterii_zavarshvane` in the header.
2. **Known gates and constraints.** Ask. Do not assume a gate from memory still applies.
3. **Create the task folder.**
   - `LOGBOOK` with the Baton header (`sastoyanie: aktivna`, `prioritet`, …) and a
     one-line pointer in `MEMORY.md`.
   - `PLAN.md` **v0**, drafted from what memory already says and labelled *"draft from
     memory, before research"*. It is the yardstick: did research change it?
   - `VAPROSI.md` (open questions), split into **for research** and **for the human to
     decide**. A decision is never sent to an agent.
   - `.batonignore` containing `razuznavane/*`. Raw agent output is written while a
     round runs; the round is logged when it starts and when it is consolidated.
4. **List the tasks that already exist** and serve this goal. Link them in PLAN.md as
   plain text. Do not duplicate them.

## 1. Plan shape — backwards from the goal

```
Goal
What must be true for it to happen   (branches A, B, C…)
  each item:  ✅ fact / decided   ⏳ in progress   ❓ open question   🧑 human decision
Order
Signals        (intermediate evidence the path works: visits, replies, pilots…)
Related tasks
```

Tag every item by **how long it takes to pay off**, because that sets the order:

- **Doors** (months: listings, standards, partners). Start them first and track them as
  waiting.
- **Build** (days to weeks). Done in sequence, with the human's stops along the way.
- **Recurring** (ads, outreach, posts). Starts once there is somewhere to send people.

The goal stays fixed while the path changes. A path changes only on a **new fact**, and
every change goes in the logbook as "changed X because Y". Nothing is silently rewritten.

## 2. A research round

**Angles come from the open questions in `VAPROSI.md`, not from a fixed list.** Useful
defaults for round 1:

- similar companies
- prices
- people and buyers
- regulation
- social media
- channels and partners
- risks

Every round also includes two agents:

- **Own assets** (local only): what is already decided or known, so nothing is
  researched twice, and **which older decisions in memory conflict with the new goal**.
- **Devil's advocate**: attacks the *current* plan version, not the first one.

Mechanics:

- **Round size.** 6–10 `general-purpose` agents in one message. Size the round by the
  number of questions, not by a target number. Use `general-purpose` because Explore
  cannot write files.
- **Shared context.** Write `razuznavane/kragg-N/BRIEF.md` first: the verified facts so
  far plus the rules below. Every prompt starts with "read BRIEF.md".
- **One agent, one narrow angle.** The web search budget (about 200 searches) is
  shared by the **whole session**, not given to each agent, and it does not refill
  between rounds. Plan how to spend it across rounds: keep questions narrow, prefer
  fetching known official URLs, and put the deepest questions in the first round. Once
  the budget is spent, agents can only fetch pages they already know, so say so to the
  human before launching another round. If an official site blocks bots, use its
  official mirror; for EUR-Lex that is `publications.europa.eu/resource/celex/<CELEX>`.
- **Rules for every agent:**
  - Work and write in **English**. Only the consolidated output is in the human's
    language.
  - Each agent writes `razuznavane/kragg-N/NN-<angle>.md` with a table
    `| claim | source (URL or file:line) | found/inferred | confidence |`. No source means
    "inferred", never a fact.
  - Then "Answer" (3–6 bullets) and "New questions".
  - Touch no other file, and collect no personal contact data.
- **Log the launch** in the logbook: which angles, and why.
- **Cost.** A 10-agent round is roughly 1M tokens and 5–8 minutes.

## 3. Consolidate — verify before you believe

1. **Verifier.** One independent agent checks the 5–8 claims the plan rests on against a
   **primary** source. Verdicts: CONFIRMED / PARTIAL / REFUTED / NOT VERIFIED. Check local
   claims yourself: code, file contents, memory.
2. **`FAKTI.md`.** Every fact gets a status and a source:
   - **П**: verified by the verifier
   - **В**: checked locally by you
   - **А**: an agent's claim with a source, not independently checked
   - **И**: inferred

   Append a section per round, and state corrections to earlier rounds explicitly.
3. **Conflicts** with older decisions in memory are **surfaced as decisions** for the
   human. Never smooth them over.
4. **Re-score the constraints — `OGRANICHENIYA.md`.** This is the step that stops research
   from only ever adding. A round that discovers something almost always makes an older
   rule wrong, and an older rule that nobody retires goes on steering the plan from a file
   no one re-reads. Round 2 of one project found nineteen such conflicts and retired none of
   them: it produced banners.

   Every constraint the round touched gets exactly one status:

   - **остава** (stands) — say why the new evidence does not reach it. A constraint left
     standing without that sentence has not been re-scored, only skipped.
   - **пада** (falls) — the evidence that killed it, **and every place it is still
     written**. This is the whole point: a constraint lives in files, so one corrected in
     the README and left in the other document has not fallen. One project corrected
     "only this tool reports what it did not read" in its README and left the same sentence
     in its positioning document, where the next round found it again.
   - **чака проверка** (awaits check) — the one check that would settle it, and who does it.
     A constraint cannot sit here twice: if the check was not done by the next round, it
     falls to "stands" or "falls" on the evidence there is.

   **The bar for retiring is the bar for asserting**: a source or a measurement. Not "it
   feels outdated", and not "it is inconvenient" — an inconvenient constraint is the one
   most likely to be true. A constraint the human set stays until the human is shown the
   evidence and says otherwise; the module prepares that, it does not decide it.

   Write the register so it can be checked by machine, one row per constraint:

   ```markdown
   | id | статус | файл | текст |
   |----|--------|------|-------|
   | O1 | пада   | POZICIA.md | само ние разделяме прочетох от намерих |
   | O2 | остава | MEMORY.md  | не слагай търговски продукт на сайта |
   ```

   `текст` is a phrase short enough to search for and specific enough to find. Baton reads
   this file at session start: a constraint marked **пада** whose text is **still in that
   file** is reported, because it did not fall — it was only written down as having fallen.

5. **`PLAN.md` vN.** Put it on top, starting with **"what changed since v(N−1) and why"**.
   Keep the previous version below it for comparison.
6. **Update `VAPROSI.md`**: questions answered, new questions for the next round, and
   decisions still pending.

## 4. Stop at the human (every round)

In the human's language, briefly:

- what we learned, the few things that change the plan, grouped
- what was verified and what is still an agent's claim
- the decisions needed now, numbered
- the candidates for the next round

Then wait. Record every decision in `VAPROSI.md` and the logbook. A decision that
overturns an older rule goes into memory too, marked "changed on <date>, because …",
with the old rule kept as a warning.

## 5. After the loop — lessons and the task tree

When research ends (no blocking question left, or the round cap is reached), write
`DARVO.md` (the task tree) and show it to the human. This is the hand-over from research
to execution.

1. **Lessons across all rounds.** One table: the lesson, which round produced it (and which
   round corrected it), and its status (verified / computed / an agent's claim). Add one
   line on the method: what each round changed.
2. **The tree, from the goal down to tasks.** Branches are the "what must be true" items
   from the plan. Each leaf is a task with exactly one state:
   - **✅** done
   - **▶** can be done now, by the agent, without waiting
   - **🧑** waits for a human decision (numbered as in `VAPROSI.md`)
   - **🗣** waits for an outside person
   - **⛔ ← X** blocked by X, where X is named explicitly
   - **🔁** recurring

   Put the decisions in their own branch at the top, because everything below waits on them.
3. **Priority order of the branches.** Ask the human which two or three branches unlock
   everything else, and put that order at the top of `DARVO.md`. The rest follow in order.
4. **"Can do now"** lists the ▶ tasks. **"Unlocks most"** names the one or two decisions or
   conversations that unblock the most leaves.
5. Then split into sub-tasks as the human decides. Each sub-task gets its own Baton folder,
   linked from PLAN.md and DARVO.md.

Research swarms stay for research. Judgement (price, name, letters, strategy) stays with
the human, and building goes to agents only where the success criterion can be checked by
a machine and there is a hard cap on effort.
