# Review tools

Part of the [Baton](../README.md) documentation.

## The review: does the index still match the files?

```
python3 tools/baton_review.py --stale          # has a pointer gone stale?
python3 tools/baton_review.py --which <file>    # which claim is unsupported?
```

**Optional, off by default, and it needs a key.** Without an
[OpenRouter](https://openrouter.ai) key this does not run, and nothing else in Baton wants
one — the hooks never call it. (The one request the hooks may make is the weekly update check,
and only if you switched it on.)

**Getting the key: `/baton-key`.** The agent walks you through openrouter.ai (account, a little
credit, a key with a spending limit) and then gives you one command to run **in your own
terminal**, so the key never enters the conversation:

```
python3 tools/baton_key.py          # asks for the key without showing it, checks it, stores it
python3 tools/baton_key.py --check  # the agent runs this: limit and spend, never the key
```

It is stored in `~/.config/baton/env` (mode 600). A refused key is not stored. On its first real
run `--check` printed OpenRouter's `label` — which, for a key without a name, is the key's own
first characters. It no longer prints the label; a test holds it.

It exists for the one kind of rot Baton cannot catch by matching strings: an index line that
asserts something the file it points at has since contradicted. A contradiction has no
textual signature. Either someone re-reads both, or it stays. Measured on 19 such pointers
here: six were wrong, two in ways no pattern could have found, for **$0.0013** the run.

It sends the pointer and part of the file to a hosted model ([TypeSafe's
Jev](https://typesafe.ai), which returns calibrated probabilities rather than text). That is
the whole reason it is opt-in and separate from the hooks: logbooks carry client matter.

### Configure it before it will run

In `baton.local.json` -- next to the installed hooks (`~/.claude/baton/hooks/`) with the
install script; in the plugin's data folder (`~/.claude/plugins/data/baton-…/`) as a plugin,
run with `CLAUDE_PLUGIN_DATA` set to that folder:

```json
{
  "review_index": "~/notes/INDEX.md",
  "review_shortlist": "~/notes/AT-RISK.md",
  "review_confidential": ["client-name", "Client Name", "unreleased-product"]
}
```

| | |
|---|---|
| `review_index` | the index whose pointers get checked — any file with `[title](path.md)` links |
| `review_shortlist` | optional shortlist: only the targets it names are checked, so a long index need not be paid for whole |
| `review_confidential` | substrings that must never leave the machine |
| `review_required` | optional, `true`: a run that could not read everything it was pointed at is `BLOCKED` (exit 1) instead of `PARTIAL` (exit 2); also `BATON_REVIEW_REQUIRED=1` |

Every run ends with an account of what it was pointed at and what it read, each one not read
named with the reason. Nothing read is `BLOCKED`, exit 1. Some read and some not is `PARTIAL`,
exit 2 -- including a folder that was never meant to hold a logbook, which looks the same to the
tool as one whose logbook went missing. Name such a folder in a `.batonignore` at the task root
(see [Ignoring files](how-it-works.md#ignoring-files-that-change-on-their-own)) and it is neither expected nor
missing; the run prints it as `skipped`. `review_required` stays all-or-nothing: which folders
are required cannot yet be said one by one.

The guard reads the **whole source file**, not the part that gets sent: the question is
whether this document is about confidential matter, not whether the bytes that happened to fit
contained the word. That is deliberately conservative and it costs coverage — on the corpus
here it holds 10 of 19 rows. Holding too much is a list to narrow; holding too little is a
disclosure.

**`review_confidential` is required, and absent is not empty.** With the key missing the tool
stops and tells you to decide; write `[]` if you really mean that nothing is held back. The
match is on the path *and* the content, because material sits in an innocent folder and still
recounts a client's business.

⚠️ **Write every name in every alphabet you use.** Here the list held only the Latin spelling
of a client's name while the notes about that client were written in Cyrillic. The guard was
structurally correct, matched nothing, and a request went out. A test caught it; reading the
line had not, three times.

A held row stops *itself*, not the run — otherwise the only way to get a review is to remove
the barrier. Every run appends to `$BATON_HOME/.pregled-dnevnik.tsv`: what was sent, when,
what it cost.

### `--tasks`: the header against its own logbook

```
python3 tools/baton_review.py --tasks
```

Same shape, different corpus: a header's `sledvashto` and `kriterii_zavarshvane` are pointers,
and the logbook under them is the source. A task marked finished on a criterion its own latest
entry retracted is the same rot as a stale index line — and equally invisible to string
matching. It found exactly that on the first run here.

⚠️ **Measured, and the measurement is not flattering.** On the corpus here: 13 of 19 tasks were
held by the confidentiality guard, because interlinked projects mention each other constantly.
Of the six that ran, five scored above the memory-index threshold — a number that flags almost
everything is an ordering, not a verdict. The largest logbook scored lowest, which suggests the
score partly tracks logbook length rather than staleness; six rows is far too few to say so.

Read what it ranks. Do not carry the threshold here.

### Two questions, opposite amounts of evidence

Measured, and the easiest thing here to get backwards:

| question | evidence | what the other way does |
|---|---|---|
| has the pointer gone stale? | an **extract** (~2600 chars): the head, plus the paragraphs the pointer is about | the whole file drops real cases 0.73 → 0.43 |
| which claim is unsupported? | the **whole file** | an extract gives false ones: 0.02 against 0.97 |

One reason both ways: a summary judgement is diluted by a long text, while a single claim has
its evidence *somewhere* in it — and a cut above that evidence fails the claim innocently.

`--which` caps at 28000 characters and **says so** when it cuts, because below the cut nothing
can support anything and a low score there means "don't know", not "no".

Until v2.16.0 the extract was the first 2600 characters, and that cut is why `--stale` kept
flagging a pointer whose correction was recorded deep in the file: the fix was real, the
extract could not see it. Now the first 1000 characters always go -- these files put what is
true now at the top -- and the rest is filled with the paragraphs sharing the most words with
the pointer, in file order, each gap marked `[…]`. The size stays, because the whole file
dilutes. No paragraph shares a word: the old extract, unchanged.

Retrieval is **by words, not by meaning** -- Baton is stdlib only. Words are cut to five
letters to meet Bulgarian endings halfway, and rare words weigh more than common ones.

Measured on a control of 14 pointers into six real memory files, 12 of them with their
evidence below character 2600, half deliberately made false: **7/14 right before, 13/14
after**; false pointers rose by 0.32 on average, true ones fell by 0.23, and the two whose
evidence is in the head did not move. One false pointer stayed below the threshold in both
versions with the right paragraph in the extract -- that miss is the model's, not the
retrieval's. On the live index the three rows sent moved by at most 0.04. Fourteen rows is a
control, not a calibration: the threshold is still an ordering.

### `--which` takes a task name

`--which` cuts a pointer into separate claims and asks the source about each. Its corpus was
index lines. Measured 2026-09-23 on the index this was built against:

| | before | after |
|---|---|---|
| rows yielding **0** claims | 2 | **13** |
| rows yielding **≥3** claims | **10** | **0** |
| most claims on one row | 4 | 2 |

The index had been compressed on purpose, so that a pointer carries no state. That was
right, and it left this mode without input: **an index that cannot rot is an index `--which`
cannot check.** The two rules are in tension by design, and the tension is worth naming.

Task headers rot by design — that is what `sledvashto` is for — and `--tasks` already asks
the whole-header version of this question against the same logbooks. So `--which <task-name>`
asks it per claim:

```
$ baton_review.py --which qrp-benchmark
🔴 NOT SUPPORTED 0.14  sastoyanie: priklyuchila
🔴 NOT SUPPORTED 0.28  na_hod: nie
🟡 unclear       0.50  kriterii_zavarshvane: benchmark against the paper — done (14/30)
```

`--tasks` had flagged that task at 0.66; this says **which part**. (That was the first run; the
first two lines are no longer asked -- see below -- and fields print by their English names,
`done_when:`.) A bare task name that
holds a logbook wins over an index target; an index path still reaches the old mode.

**`sastoyanie` and `na_hod` are not claims here.** Measured by running the mode over all 19
tasks: they came back "not supported" on 6 of 6 reviewed tasks, 0.02–0.13 and 0.07–0.35. The
deciding row is a task with a 42,317-character logbook and 33 entries whose three real claims
scored 0.95, 0.97 and 0.97 — and whose own logbook "does not support" `postoyanna`. A logbook
never writes `sastoyanie: postoyanna`: it is the word that names where the work stands, not
something the entries assert. Twelve of that run's 25 claims were these two fields and every
one was a false positive — the majority of the output, and its most visible part. They stay in
`--tasks`, which reads the whole header together; judging where the work stands is that
mode's job, and naming which claim broke is this one's.

⚠️ `na_hod` sometimes carries a name rather than an enum. That case was not measured
separately — the three thick-logbook rows all read `nie` — so it is excluded with the field,
not on evidence of its own.

**Two things this output says before the numbers, because both change how they read:**

- The 0.4 / 0.7 cutoffs come from the index corpus and have **not** been measured here.
- **"Not supported" means both "contradicted" and "never mentioned."** The criterion the
  model is given merges them, and they are not the same finding: one says the header is
  wrong, the other says the logbook is thin. Found by the positive control — a task whose
  header spoke of a review, a board and a submission came back unsupported on all four
  claims, correctly, because its logbook is 562 characters and mentions none of it. So the
  logbook's size and entry count are printed, and a thin one is named as thin.

⚠️ A logbook is **newest-first**, so the `WHOLE_CHARS` cut keeps the newest entries — the evidence
a header's currency is judged against. On the index corpus the same cut fell anywhere and
failed claims innocently. Same cut, opposite meaning; the announcement says which.

⚠️ `claims()` also extracts link text and trigger phrases as "claims"
(`*history:* [sessions and commits](…)`). On the old index those were diluted by real ones; on
the new one they are most of what is left. Flagged, not fixed.

### The grey band: one draw near the threshold is partly a coin flip

Measured 2026-09-23 on 45 pointers, **three identical runs of the same request**. The model
is not deterministic — an independent audit measured 50 identical requests returning 15
distinct answers — so the question was how much that costs here:

| | |
|---|---|
| median spread across 45 rows | **0.010** |
| mean | 0.020 |
| identical in all three runs | 6 of 45 |
| **the two rows whose mean sat between 0.38 and 0.55** | **±0.12 and ±0.09** |

The spread is negligible where the model is confident and **largest exactly where the
decision is made**. The mean hides it: 0.02 sounds calm. One row of the 45 changed sides of
the threshold between identical runs — 0.41 / 0.47 / 0.38 — so it was flagged in one run of
three.

So `--stale` and `--tasks` draw **three times and average** when the first draw lands in
`GREY_BAND = (0.35, 0.60)`, and print the draws next to the mean, because a mean shown alone is
indistinguishable from one draw. Outside the band a second draw buys a hundredth of a point
and is not paid for. On a 45-row index this cost **$0.0040 instead of $0.0034**.

⚠️ `--which` is deliberately left alone: it asks a different question, one claim at a time
against the whole file, and its spread has **not** been measured. Averaging it would carry a
number from one corpus to another — the mistake this feature exists to correct.

⚠️ The band, like the threshold, is measured on **one** corpus. Measure yours.

Two things the same probe measured, worth knowing before trusting the output:

- **The evidence does drive the answer.** Swap the detail file's body for an unrelated
  file's and the value jumps 0.21 → 0.70, ten times the row's own spread. The audit's
  "answers without reading the state" finding does not reproduce for this question shape.
- **An empty body does not raise the number** (0.23 against 0.21). The question catches
  *contradiction with present content*, not *absence of support* — a pointer whose file has
  been emptied or truncated reads as fine.

### What the number is not

`THRESHOLD = 0.46` was measured by hand — 14 of 19 pointers checked personally, everything ≥0.47
real and everything ≤0.45 false. ⚠️ That is **one corpus of 19 rows, one person's writing, one
language.** It is a starting point. Run it on yours, check what it flags, move the number.

And in TypeSafe's own words: *calibration is measured across groups of predictions; it does
not guarantee that an individual answer is correct.* This ranks and says "look here". A person
opens the file and decides. Nothing is rewritten because a number was high.

## Where else does this live — and is that place still claiming it?

```
python3 tools/baton_where.py "2500"           # where else does this number appear
python3 tools/baton_where.py "0\.4[0-9]" --regex
python3 tools/baton_where.py --duplicates     # find them without being asked
```

`grep -r` answers *where a string occurs*. The question that actually comes up is a different
one: **which of those places still claim something, and which are only a record of what was
once true.** A price decided in one task and copied into another task's header is a defect. The
same number in an old logbook entry is history.

Baton already draws that line for a person to read; this reads it. A logbook header, a plan and
a memory file are **live**. An entry, a file whose name carries a date, and a row in a claims
register are not — they repeat old values legitimately, and the first version counted them,
which took one query from four live places to seven. The kinds come from
[`baton_corpus`](#the-corpus-and-saying-what-is-in-it), so the two tools cannot drift apart
about what a place is.

### ⚠️ It does not find contradictions. It finds duplicated state.

Whether the duplicates disagree is the reader's call. Put it the other way round and someone
will pronounce a tree "consistent" while the same wrong number sits in six places.

### `--duplicates`, and what it is calibrated against

Numbers living in live places in two or more task folders. Measured over 20 task folders plus a
memory tree — 149 distinct numbers, every hit labelled by hand:

| kind | duplicates | relevant | noise |
|---|---|---|---|
| **money (€)** | 6 | **6** | 0 |
| **percentages with a decimal** (84.8%) | 3 | **3** | 0 |
| thresholds (`0.92`, `0.46`) | 41 | 1 | **40** |
| round percentages (100%, 30%) | 16 | 0 | **16** |
| version numbers (v1.0.0) | 11 | 0 | **11** |

⇒ **A number with a decimal point or a currency sign is a decision. A round number or a version
is shared vocabulary** — it turns up everywhere because it is a word, not a state. `100%`
appeared in nine folders. So the default is money and decimals only, which gave **9 hits and no
false positives**; `--all` restores the rest, which was noise 27 times out of 27.

⚠️ The threshold row exists because the first measurement missed it: that run excluded some
folders and never saw them. **A rate measured on a scope that is not declared is not a rate** —
which is why `Scope` exists at all.

⚠️ One corpus, labelled by its author, on one day. Run it on your own tree, label what it
prints, and move the filter to where it separates yours.

On the corpus it was built against it reported `€2500` in one task's decisions file marked
*decided, 19.09* — and in another task's header dated **26.09**. Seven days between two live
places, and nothing would have said so. It reports the spread in when those places were last
touched, which is the part that says how long they have disagreed.

## Reading order for a long list

```
baton_sift.py --question "Does this repository ship a CBOM generator?" < candidates.tsv
baton_sift.py --question "..." --threshold 0.5 --out scores.tsv < candidates.tsv
```

A research pass reads hundreds of candidates and judges each one expensively. Measured here
on 2026-09-26: one run paged 300 code-search hits and de-duplicated them by hand, another
filtered 935 + 576 arXiv entries with a title regex. `tools/baton_sift.py` scores the same
list once with the calibrated classifier `baton_review` already talks to, and puts the
worthwhile ones first. Input is TSV on stdin — an id in column one, everything else is what
gets judged.

Measured on a real triage: 40 GitHub repositories, hand-labelled **before** the scores were
seen, question "does this ship a tool that produces a cryptographic inventory".

| | |
|---|---|
| cost | **$0.00069** for 40 |
| false positives among the 11 hand-labelled *no* | **0 at every threshold** — the highest *no* scored 0.49 |
| medians | yes **0.84** · no **0.19** · undecidable-from-the-input 0.36 |
| ⭐ the actual win | sorted by score, **all 21 yeses were in the top 25 of 40** |

⚠️ Of the three disagreements, **two were the labeller's fault**: one repository's only CBOM
file was a frontend graph component, another had none at all. The third was a real limit of
the input — a repository whose description does not say what it does — and no scorer fixes
that.

### ⛔ Reading order, not a right of exclusion

Nothing is dropped, ever. `--threshold` splits the list into **read first** and **read after**,
and prints both with counts. The threshold travels in the output for the same reason a
coverage figure travels with its denominator, and the report says in as many words that a
candidate below the line is one nobody has read yet.

This is not fastidiousness. The failure it prevents was made four times in one day here: a
search reported as "found X" where the truth was "did not look at the rest". A scorer used
as a filter makes the unread invisible, and **an absence written without the check that
would find it** is the defect this project exists to refuse.

### ⚠️ It scores a question; it does not tell you the question is wrong

Every mistake made here that day was in the framing — a regex too narrow to match
`DHE_RSA`, an evidence window that hid 59% of the text, a category asserted from an
unvalidated pattern, a baseline two dozen versions stale. A classifier would have answered
each of those confidently and uselessly. Use it to order reading and to cross-check a claim
against a document; not to decide what the claim should be.

⚠️ Measured on one kind of candidate, n=40. A threshold does not transfer — measure it again
on arXiv rows or code hits, the same way `baton_review` says.

## The corpus, and saying what is in it

Two questions come up in every tool that reads a whole tree of task folders: **which files
are part of the corpus**, and **what kind of place is this passage** — something that claims
a thing now, or a record of what was once true. `tools/baton_corpus.py` is the one owner of
both.

```python
from baton_corpus import Scope, chunks, kind, walk

scope = Scope(["docs", "sdks", "*/vendor/*"])      # what is OUTSIDE the corpus
for text, source, what in chunks([home], scope, "LOGBOOK.md"):
    ...                                            # what ∈ LIVE HEADER RECORD SNAPSHOT CLAIM
```

A logbook arrives as its header plus one chunk per entry; a claims register as one chunk per
row; anything else split on its headings, with a dated filename marking the whole file a
snapshot. `--duplicates` in `tools/baton_where.py` uses the same `kind()`, so the two cannot
drift apart about what a place is.

### `Scope(None)` raises, and that is the feature

An empty scope is allowed — `Scope([])` — but it has to be written down. The reason is
measured, twice in one day:

| | what an undeclared scope did |
|---|---|
| a duplicate-state prototype silently skipped one subtree | the same corpus went from **9 hits to 100** once it was scoped properly, and the false-positive rate with it |
| a corpus built for detection declared nothing | **805 of 1167 live passages (69%)** turned out to be imported comparison fixtures and vendored SDKs. Two of three detectors sat near 50% false positives, and the corpus was the reason |

**A rate measured on a scope nobody declared is not a rate.** `Scope.describe()` returns that
scope as one line, so a number can be quoted together with what it was measured over.

### ⚠️ `.batonignore` answers a different question

`.batonignore` means *"do not demand a logbook entry for this"*. It does not mean *"this is
not my writing"*. They overlap — raw agent output is both — and they diverge: a task that
ignores its live transcripts for the Stop hook has those transcripts as its actual work.

It is honoured by `Scope` because the duplicate-state calibration was measured with it
honoured, and dropping it would invalidate that measurement. It is not a substitute for
declaring what is outside.
