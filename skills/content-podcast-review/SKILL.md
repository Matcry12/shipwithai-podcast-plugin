---
name: content-podcast-review
description: Independent review pass for rendered podcast artifacts. Dispatches the podcast-critic agent in a separate context, writes a scored report to podcast-reports/<slug>--<locale>.md, and gates ship/fix/regenerate. Run after /content-podcast and before /content-podcast-posting.
---

# content-podcast-review

Run the independent quality gate on rendered podcast artifacts. This is a
separate pass by a separate agent — the author never grades its own work.

## When to invoke

- User runs `/content-podcast-review podcasts/<slug>--<locale>.json` or
  `/content-podcast-review <slug>--<locale>`.
- The generation skill's Step 5 self-check is the author grading itself in
  the same context. This skill is the **independent** pass — different agent,
  different context, no access to the author's reasoning.

## Required inputs

Locate the three artifact inputs (fail fast with a clear message if any is
missing — instruct the user to run `/content-podcast` first):

1. **Source draft (EN or VI)** — path from `sourcePost` field in
   `podcasts/<slug>--<locale>.podcast.json`.
2. **Render script** — `podcasts/<slug>--<locale>.json`.
3. **Whisper transcript** — `podcasts/<slug>--<locale>.transcript.json`.

## Steps

### 1. Resolve slug and locate artifacts

Accept either `podcasts/<slug>--<locale>.json` or bare `<slug>--<locale>` as the argument.
Derive `<slug>--<locale>` accordingly. Verify all three required files exist:
- `podcasts/<slug>--<locale>.json`
- `podcasts/<slug>--<locale>.transcript.json`
- `podcasts/<slug>--<locale>.podcast.json` (to read `sourcePost`)

If any file is missing, **STOP** with:

> "Podcast artifacts not found for `<slug>--<locale>`. Run `/content-podcast <draft-path>` first."

### 2. Read the stub and load inputs

Read `podcasts/<slug>--<locale>.podcast.json`. Extract `sourcePost`. Read all three inputs:
- The source draft (EN or VI) at `sourcePost`.
- `podcasts/<slug>--<locale>.json` (the render script).
- `podcasts/<slug>--<locale>.transcript.json` (the Whisper QA result, including `overlapPct`).

### 3. Dispatch podcast-critic in a separate context

Dispatch `agents/orchestration/podcast-critic.md` as an independent reviewer
subagent. Pass it:
- The full text of the source draft (EN or VI).
- The full contents of `podcasts/<slug>--<locale>.json`.
- The full contents of `podcasts/<slug>--<locale>.transcript.json`.

The critic runs in its own context. It does not have access to the generation
skill's reasoning or self-check notes — independence is the feature.

**Handoff contract (required — file-based, not message-based).**
A subagent's *final message* is NOT a reliable transport: the dispatch layer may
replace it with a one-line summary, so the full YAML block can be lost even when
the critic produced it correctly. Do **not** depend on the returned message, and
do **not** scrape the subagent's transcript. Instead, instruct the critic to
**write** its output to a file, then read that file. The dispatch prompt MUST end
with:

> "As your FINAL action, write your complete YAML output block (the exact shape
> from your 'Output format' section — `reviewer`, `score`, `max`, `dimensions`
> with every per-atom pass/fail + notes, `blockers`/`majors`/`minors`/`nits`,
> `overall`, `verdict`) to `podcast-reports/<slug>--<locale>.critic.yaml`. Write the raw
> YAML only — no Markdown fences, no prose. That file is the deliverable."

Create `podcast-reports/` before dispatching so the path exists. After the critic
returns, read `podcast-reports/<slug>--<locale>.critic.yaml` and parse `verdict` + the
per-dimension scores from it. If the file is missing or not parseable YAML
(missing `verdict:` or the scored dimensions — six for single-narrator, seven
including `conversationality` for dialogue), re-dispatch once with the same
instruction; if it still fails, surface the problem to the user rather than
guessing the scores.

### 4. Write the report

Read the critic's `podcast-reports/<slug>--<locale>.critic.yaml` (per the handoff contract
above). Then write the human-facing report `podcast-reports/<slug>--<locale>.md`,
embedding that YAML verbatim in the "Raw critic output" block:

```markdown
---
slug: <slug>--<locale>
reviewed: YYYY-MM-DD
verdict: <ship|fix|regenerate>
score: X / 30
---

# Podcast Review: <slug>--<locale>

**Source draft**: <sourcePost>
**Script**: podcasts/<slug>--<locale>.json
**Transcript**: podcasts/<slug>--<locale>.transcript.json
**Verdict**: ship / fix / regenerate
**Score**: X / 30

## Per-dimension scores

| Dimension | Score | Max |
|---|---|---|
| Faithfulness | X | 8 |
| Value | X | 6 |
| Eyes-free sayability | X | 6 |
| Standalone | X | 3 |
| Memorability | X | 5 |
| Render integrity | X | 2 |

## Findings (sorted by severity)

### Blockers
<list or "(none)">

### Majors
<list or "(none)">

### Minors
<list or "(none)">

### Nits
<list or "(none)">

## Raw critic output

<details>
<summary>podcast-critic</summary>

<full YAML output from podcast-critic>

</details>
```

### 5. Print verdict and next step

Print a summary to the user:

- Score and verdict.
- Top findings (blockers and majors only, with fix instructions).
- Exact next step based on verdict:
  - **`ship`**: "Artifacts pass review. Proceed to `/content-podcast-posting <slug>--<locale>`."
  - **`fix`**: "Minor issues found. Edit `podcasts/<slug>--<locale>.json` to fix the listed
    sayability/standalone issues, re-render by re-running
    `/content-podcast <sourcePost>`, then re-run
    `/content-podcast-review <slug>--<locale>`."
  - **`regenerate`**: "Substantive faithfulness or value issues found. Re-author
    from the source draft by re-running `/content-podcast <sourcePost>`, then
    re-run `/content-podcast-review <slug>--<locale>`."

### 6. Bounded loop enforcement

Track fix/regenerate cycles. After **3 cycles** without a `ship` verdict,
do not loop further. Instead, surface to the user:

> "This is the 3rd review attempt and the verdict is still `<verdict>`. Human
> review required. See `podcast-reports/<slug>--<locale>.md` for the full findings."

Stop and wait for a human decision.

## What this skill does NOT do

- Does not edit `podcasts/<slug>--<locale>.json` (the critic scores and explains; the
  generation skill re-authors on regenerate).
- Does not re-run `/content-podcast` automatically (the loop is human-driven
  across the two commands).
- Does not bypass a missing artifact — it fails fast with a clear message.

## Output

`podcast-reports/<slug>--<locale>.md` (gitignored) with scored rubric and verdict.
`podcast-reports/<slug>--<locale>.critic.yaml` (raw critic YAML; the file-based handoff the skill reads).
