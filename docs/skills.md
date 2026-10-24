# Skills

Part of the [Baton](../README.md) documentation. Installing comes first: [install.md](install.md).

### Existing work: `/baton-inventory`

The installer copies five skills into `~/.claude/skills/` -- `baton-inventory`, `baton-plan`,
`baton-task`, `baton-key` and `baton-doctor` (every folder under `skills/`). Baton starts
empty, but the machine rarely does. Run `/baton-inventory` once after installing:

1. **Scan.** Four read-only agents search the machine at the same time. They cover git
   repositories, loose files, Claude Code memory and history, and project folders.
2. **Review.** The results are gathered into one inventory: tasks with a next step,
   recurring work, frozen, done, files that belong to existing tasks, and risks found on the
   way (a repository with no remote, a readable private key). **You confirm the state of
   each item.**
3. **Apply.** Only then are task folders created. Each logbook opens with an entry marked
   *reconstructed*, and nothing is moved.

When the evidence conflicts, memory and history decide the state and files decide the
location. A file date tells you when something was touched, not whether it is finished.
On its first run the file-only agents misjudged state three times, and memory was right
each time.

You do not have to remember it: while the task root is empty and the machine has earlier Claude
Code conversations, the session starts with the agent offering it — once a day, until there is a
folder. Claude Code deletes conversation transcripts older than `cleanupPeriodDays` — 30 days by
default ([its documentation](https://code.claude.com/docs/en/claude-directory#cleaned-up-automatically)).
Its auto memory is kept. The same page lists the prompt history (`history.jsonl`) in the sweep; on
the author's machine it still reached back six months. For work older than a month, the memory is
what is certain to be left. The inventory reads all three.

### Two paths, and the cheap one is the default

**The direct path** needs no skill: read the logbook, do the work, write the entry. The hooks
already enforce it. One letter, one fix, one decision, one measurement — this is most work.

**The swarm** is `/baton-plan`, and it costs. Measured on real rounds: seven agents ≈ 1.3 million
tokens and half an hour; four agents ≈ 660 thousand. Worth it when there is something to
**measure** or a written **claim to attack**; not worth it for judgement — a price, a name, a
letter — where a swarm returns opinions, and opinions do not improve by being seven.

The test: *what would the round check its answer against?* No answer, no round.

### Before any of it: `/baton-task`

Research answers a question; if the question was never stated, it answers the one the agent
assumed. `/baton-task` is the step before: **recognise** that a conversation has become a task
or a decision, **read back** what was already done and decided — the entries on the topic, not
the top one — **formulate** the goal and a criterion someone could check, and only then go
outward (large → `/baton-plan`).

Two hooks hold the checkable half of it, so it does not depend on the agent remembering:
- **UserPromptSubmit** (`baton_prompt.py`): a message that names a task — its folder, or one of
  the `aliases` in its header, in any alphabet, meeting endings halfway (`скенер` finds
  `скенера`, `страницата` finds `страници`; a long alias keeps all of itself but its ending, so
  `рестак` does not find `рестартирам`; a short Cyrillic alias takes a noun's ending, so `пост`
  finds `поста` and `постове`, not `построй`; a Latin alias takes only -s, -es, -y -> -ies, so `bot`
  does not find `both`) — gets that task's last entry and next step put in front of the agent, with
  "read the logbook first". Once per task per session; silent when nothing is named; never
  blocks a message. A task whose name or logbook holds a word from `review_confidential` is shown
  with its `next:` like any other: that list is read only by the review tools, and this is
  deliberate (decided 2026-10-22, ZA-OPRAVYANE row 66).
  The same hook watches the length of the session: every message re-sends the whole context,
  so a long session eats the usage limit. From ~200k tokens of context (read from the last
  answer's `usage` in the transcript) it has the agent write the logbook of every task touched
  and shows the human one line — type `/clear` — and again every +100k; after `/clear` or
  `/compact` it starts over. `/clear` keeps the window: SessionStart sees `source: "clear"` and
  brings the board back, told the logbooks were just written. No hook can run `/clear` itself
  (Claude Code issues #35150 and #16659, closed as not planned), so it costs one command. Set `restart_at` /
  `restart_step` in `baton.local.json` (or `BATON_RESTART_AT` / `BATON_RESTART_STEP`);
  `restart_at: 0` turns it off. The 200k default was set for cost, not for quality, and it stays
  (decided 2026-10-21): what stretches a session before a restart is needed is handing heavy work
  -- many commands, large output -- to a subagent with its own fresh context, so the main
  context grows by the subagent's report rather than by everything it read. A lower
  `restart_at` is yours to set if quality slips earlier for you.
- **Stop**: a task worked on now whose header has no `done_when` (or `kriterii_zavarshvane`) hands the turn back
  once per session: say when it is done, or ask the human — never invent one.

Measured on the day that made it (2026-09-28), against its three misses: a proposal to redo a
review finished two days earlier (the prompt hook names the task, given an alias); a
conversation that became a decision on priorities without anyone saying so (the Stop hook
asks, once the folder exists; recognising it before that is the skill's job, not a hook's);
and a comment drafted from half a post (a reading rule, out of scope here).

### A big new goal: `/baton-plan`

For a task that runs in several directions at once (launching a product, finding
customers), the second skill runs a loop in which **research comes before the plan**:

1. **Goal first.** You and the agent agree on the result you expect and how you will
   know you reached it. The task folder gets a `PLAN.md` v0, drafted from what the agent
   already knows and labelled as such. That draft is the yardstick for what research
   changed.
2. **Research round.** 6–10 agents run in parallel, one narrow angle each, taken from the
   open questions: competitors, prices, buyers, regulation, channels, and so on. Two agents
   run every time: one that reads your own files and memory, and a devil's advocate
   against the current plan. Each agent writes a table of claims with sources. A claim
   without a source is marked as inferred.
3. **Verify.** An independent agent checks the claims the plan rests on against primary
   sources. `FAKTI.md` records every fact with its status and source.
4. **Plan vN.** The plan is built backwards from the goal. It starts with a section on
   what changed since the last version and why. Long-lead "doors" (listings, partners,
   standards) are started first.
5. **Human checkpoint.** You make the decisions. The open questions go into the next
   round. The loop stops when nothing blocks the plan, or after two rounds.

Agents work in English. The consolidated output comes back in your language. In its first
real use, the first round changed the plan's core argument, and the second round changed
the shape of the product and caught a factual error left over from round one.
