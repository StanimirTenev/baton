---
name: baton-plan
description: Start a large or multi-direction task the Baton way. Set the goal first, run parallel research rounds from several angles, keep facts with sources apart from open questions, and build the plan backwards from the goal, re-planning after each round with the human at every checkpoint. Use when a new goal arrives ("we want to start selling X", "launch Y") or when asked to research and plan before acting.
---

# Baton plan — goal → research rounds → plan

A big task fails in two quiet ways. It is planned from what the agent already believes,
or it is researched with no question in mind. This skill runs a loop that avoids both:

**goal → questions → research round → verified facts → plan vN → human decides → next round**

It stops when no open question still blocks the plan, or after **3 rounds**. What is
still unclear by then goes to the human as a decision.

Task root and logbook name come from `~/.claude/baton/hooks/baton.local.json` (`home`,
`logbook`). The files below are written into `<task root>/<task>/`.

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
- **One agent, one narrow angle.** The web search budget per agent is limited (about 200
  searches). Keep questions narrow, prefer fetching known official URLs, and split any
  deep question into two agents. If an official site blocks bots, use its official
  mirror; for EUR-Lex that is `publications.europa.eu/resource/celex/<CELEX>`.
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
4. **`PLAN.md` vN.** Put it on top, starting with **"what changed since v(N−1) and why"**.
   Keep the previous version below it for comparison.
5. **Update `VAPROSI.md`**: questions answered, new questions for the next round, and
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

## 5. After the loop

When no open question blocks the plan, split the plan into sub-tasks. Each one gets its
own Baton folder, linked from PLAN.md. Research swarms stay for research. Judgement
(price, name, letters, strategy) stays with the human, and building goes to agents only
where the success criterion can be checked by a machine and there is a hard cap on
effort.
