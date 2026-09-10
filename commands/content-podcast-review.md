---
name: content-podcast-review
description: Run the independent podcast review pass (podcast-critic agent, audio-specific 25-pt rubric) on rendered podcast artifacts and gate ship/fix/regenerate.
argument-hint: podcasts/<slug>--<locale>.json | <slug>--<locale>
---

# /content-podcast-review

Run the independent quality gate on rendered podcast artifacts. Delegates the
full procedure to the `content-podcast-review` skill.

## Usage

```
/content-podcast-review podcasts/<slug>--<locale>.json
/content-podcast-review <slug>--<locale>
```

Both forms are equivalent. When given `<slug>--<locale>` alone, the skill locates
`podcasts/<slug>--<locale>.json`, `podcasts/<slug>--<locale>.transcript.json`, and
`podcasts/<slug>--<locale>.podcast.json` automatically.

## Pre-conditions

1. `/content-podcast` must have already run and produced the trio:
   `podcasts/<slug>--<locale>.json`, `podcasts/<slug>--<locale>.mp3`, `podcasts/<slug>--<locale>.transcript.json`,
   and `podcasts/<slug>--<locale>.podcast.json`. If any artifact is missing, the skill exits
   with a clear error — run `/content-podcast` first.
2. No env vars required for the review step itself.

## What it does

Invokes the `content-podcast-review` skill, which:

1. Locates the three inputs: source EN draft (from `sourcePost` in the stub),
   `podcasts/<slug>--<locale>.json` (render script), and `podcasts/<slug>--<locale>.transcript.json`.
2. Dispatches the `podcast-critic` agent in a separate context (independent pass —
   not the author grading itself).
3. `podcast-critic` grades five dimensions against the 25-pt audio rubric.
4. Writes a scored report to `podcast-reports/<slug>--<locale>.md`.
5. Prints the verdict and top findings.

## Scoring rubric (25 pts)

| Dimension | Pts | What is graded |
|---|---|---|
| Faithfulness | 8 | Every spoken claim supported by the source draft; nothing invented. |
| Value | 6 | Carries the draft's genuinely valuable ideas; no padding; worth a listener's time. |
| Eyes-free sayability | 6 | No surviving raw token / acronym / code / URL / number-as-digit. |
| Standalone | 3 | No "as shown below" / "see the diagram" / bare-URL refs. |
| Render integrity | 2 | Whisper overlap >= 85%; mismatches judged real-defect vs homophone. |

## Verdict

| Verdict | Meaning | Next step |
|---|---|---|
| `ship` | Score >= 20/25, no faithfulness failure, overlap >= 85% (or low overlap judged a Whisper artifact) | Proceed to `/content-podcast-posting` |
| `fix` | Minor sayability/standalone issues only | Edit `podcasts/<slug>--<locale>.json`, re-render via `/content-podcast`, re-review |
| `regenerate` | Any invented claim, or value/faithfulness substantively off | Re-author from scratch via `/content-podcast`, re-review |

A faithfulness failure is a hard fail regardless of total score.

Bounded loop: at most 2 fix/regenerate cycles; a 3rd failure is surfaced to the
user for a human decision rather than looping further.

## Output

`podcast-reports/<slug>--<locale>.md` (gitignored) with:

- Scored rubric (per-dimension breakdown).
- Verdict: `ship` / `fix` / `regenerate`.
- Blockers, majors, minors, nits sorted by severity.
- Exact fix instructions on a non-`ship` verdict.

## Related

- `/content-podcast` — must run (and produce artifacts) before this.
- `/content-podcast-posting` — run after this passes with `ship`.
