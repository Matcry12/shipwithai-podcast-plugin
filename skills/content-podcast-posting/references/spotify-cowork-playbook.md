# Spotify for Creators — cowork upload playbook

How an agent with a browser capability (browser-harness, Claude Cowork, or any
screenshot+click tool) publishes a rendered episode to Spotify for Creators and
captures its embed link. This is the **durable shape** of the flow — work from
screenshots, not memorized coordinates. Re-screenshot after every action and
verify before assuming success.

**Driving the operator's live browser (tab-drift hazard).** browser-harness/Cowork attaches to
the operator's real Chrome, which has many tabs the operator may switch while you work. The
*active* tab can drift between calls — a coordinate click can land on the WRONG tab (observed: a
click meant for Spotify landed on an open Gmail tab). Before every click: re-find the
`creators.spotify.com` page target by URL, activate it, and confirm `page_info()` is on Spotify;
do each navigate→act→screenshot inside a single tool call. Never click blind after a gap. Target
ids are not stable — re-discover the tab by URL substring each time, not by a cached id.

## Preconditions (the calling skill checks these first)
- `podcasts/<slug>--<locale>.mp3` exists and review returned `ship`.
- A browser capability is available. If none, print `STOP: no browser capability available` — this backend cannot run.
- The Spotify *show* already exists (one-time human setup; not automated here).

## Site map (durable shapes — verify on screen, don't hardcode coordinates)
Observed stable URL patterns (a `<showId>` and `<episodeId>` are base-62 strings):
- Show dashboard / home: `https://creators.spotify.com/home/show/` — **start here, id-less**. When
  logged in, Spotify resolves the bare `…/home/show/` to the account's active show, so you do NOT
  need — and must NOT hardcode — the `<showId>`. A specific `<showId>` is account/device-specific
  and will not carry to another account or machine. The bare root `https://creators.spotify.com` is
  the logged-out MARKETING page even after login (Log in / Sign up CTAs) — do not use it as the
  entry. `…/dashboard` is also invalid (404s).
- New-episode wizard: clicking "New episode" goes to `…/pod/show/<showId>/episode/wizard`,
  three steps shown as **Upload → Details → Review**.
- On upload, the URL gains a **draft episode id**: `…/episode/<episodeId>/wizard`. Capture this
  id from the URL — it is the same id used below.
- Published episode admin page: `…/pod/show/<showId>/episode/<episodeId>/details`.
- **The draft/admin `<episodeId>` has matched the public `open.spotify.com/episode/<episodeId>`
  id in practice (verified across episodes).** So the public URL is a strong candidate from the
  id alone — but you MUST verify it (step 8), never record it unverified.

Required fields are minimal: **Details** needs only **Title** and **Description** (rich-text, with
an HTML toggle); **Review** needs a **Publish date** (radio: *Now* / *Schedule*). Everything else
has a default. **Always select *Now* — publish immediately, never *Schedule*.** This pipeline does
not schedule episodes; if *Now* is not already selected on the Review step, click it before
publishing. (Scheduling is what previously stalled the flow on the Review screen.)

## Flow
1. **Open** `https://creators.spotify.com/home/show/` (id-less — resolves to the logged-in
   account's show; never hardcode a `<showId>`, it is account-specific) and screenshot. Do NOT use
   the bare root `creators.spotify.com` — it is the logged-out marketing page.
   - **Auth wall / login / 2FA / captcha → STOP and hand control to the human.**
     Never type credentials read from a screen. With browser-harness driving the
     operator's own Chrome you are usually already logged in; Cowork starts clean
     and will hit this gate. Print exactly one of:
     `STOP: spotify auth wall` (login page shown) ·
     `STOP: spotify 2FA required` ·
     `STOP: spotify captcha` — then stop.
2. **Check for an existing episode before creating a new one (idempotence).**
   A re-run after a partial success — episode created as a draft on Spotify,
   but the run ended before the stub was written — must not create a second
   episode: a duplicate on a public feed cannot be recalled. Before clicking
   "New episode," scan the dashboard's episode list for one whose title
   exactly matches the title this run is about to publish (exact match only —
   fuzzy matching risks a false positive against an unrelated episode that
   happens to share topic words).
   - **Found, still a draft:** open it and resume from wherever it left off —
     do not re-upload the mp3 if the preview player already shows it; jump to
     whichever step (Details, Review) is incomplete.
   - **Found, already published:** it already went out — do not publish it
     again. Skip straight to step 8 to capture its
     `open.spotify.com/episode/<id>` link and write the stub from that; the
     rest of this flow (upload, details, publish) does not run.
   - **Not found:** proceed — click "New episode" / "Create" and screenshot to
     confirm the episode editor opened.
3. **Upload audio:** the upload area has a hidden file `<input>` (observed id
   `#uploadAreaInput`, accepting `.mp3,.m4a,.wav,.flac,.ogg,.aiff,.mp4,.mov`). Set the file
   **directly on that input** (most browser tools expose a set-input-files / upload helper) rather
   than clicking "Select a file" and fighting the OS file dialog. The wizard auto-advances to
   **Details** and the URL gains the draft episode id. Wait for processing to finish (screenshot
   until the preview player / duration appears, e.g. "Preview ready"). If processing errors, print
   `STOP: spotify upload/processing error — <verbatim message>` and stop.
4. **Fill details** from the values the calling skill passes in:
   - **Title** — the episode title.
   - **Description** — the episode description (includes a link back to the
     article on the site).

   **The description is a Slate-style rich-text editor.** It keeps its content
   in its own model, not the DOM. Synthetic input — `execCommand('insertText')`,
   `type_text()`, setting `innerText` — updates what you *see* but not what the
   editor *has*: the character counter stays at `0 / 4000`, the field paints a
   red border, and **Next** refuses to advance. This was wrongly blamed on
   Grammarly at first; verified 2026-09-13 with zero Grammarly nodes on the page,
   `execCommand` still gave `0 / 4000`.

   **Insert with CDP `Input.insertText`, both fields, both locales.** It is a
   trusted, browser-level text insertion — the same path an IME uses — so the
   editor cannot tell it from typing, and it preserves Vietnamese diacritics and
   em-dashes verbatim (`type_text()` strips non-ASCII: "Đã đến lúc" → "Da den
   luc"). Verified on the live field: `0 / 4000` → `34 / 4000` for
   *"Kiểm tra: Đã đến lúc — thử nghiệm."*, exact text in the model.

   ```python
   import time
   # Title (plain input — id="title-input"): click it, clear, insert.
   box = js("(function(){const r=document.getElementById('title-input').getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]})()")
   click_at_xy(box[0], box[1]); time.sleep(0.3)
   js("document.execCommand('selectAll')"); js("document.execCommand('delete')")
   cdp("Input.insertText", text=TITLE)

   # Description (contenteditable): click INTO the box so the editor owns focus
   # and the caret, clear, then insert. Do not .focus() from JS -- a click is
   # what makes Slate treat the caret as live.
   box = js("(function(){const r=document.querySelector('[contenteditable=\"true\"]').getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]})()")
   click_at_xy(box[0], box[1]); time.sleep(0.4)
   js("document.execCommand('selectAll')"); js("document.execCommand('delete')")
   cdp("Input.insertText", text=DESCRIPTION)
   time.sleep(0.8)
   ```

   `cdp()` takes params as keyword arguments (`text=...`), not a dict — a dict
   as the second positional argument is taken as a session id and errors.

   **Verify by the counter, then by advancing.** Read the description counter:
   `js("(document.body.innerText.match(/\\d+\\s*\\/\\s*4000/)||['?'])[0]")`.
   Non-zero and roughly the description's length means the model has it.
   Screenshot both fields. Then click **Next**; the wizard must advance to
   **Review**. Do **not** clear and retype in a loop. If the counter is still
   `0 / 4000` or Next does not advance:

   1. Reload the draft wizard URL (the SPA sometimes renders a blank content
      area after a burst of synthetic events), wait for the `contenteditable`
      to reappear, and repeat the insert **once**.
   2. If it has not advanced after **two** attempts total, screenshot the field,
      leave the episode as a draft, and print:
      `STOP: description editor rejected input after 2 attempts`.
      Never a third attempt.
5. **Advance to Review and set Publish date = *Now*.** Move to the **Review** step and
   confirm the **Publish date** radio is on ***Now***; if it shows *Schedule* (or any future
   date), click ***Now*** so the episode publishes immediately. Never schedule. Screenshot to
   confirm *Now* is selected before the gate. Title and description carry over
   automatically from step 4 — this step never needs them re-typed; if either
   looks wrong here, go back and re-verify step 4 rather than retyping on this
   screen.
6. **CONFIRM-BEFORE-PUBLISH GATE:** screenshot the filled episode (with *Now*
   selected) and ask the human to approve. Do **not** click Publish without an
   explicit yes. If they decline, leave it as a draft and print
   `STOP: human declined publish — left as draft`.

   **Exception — `--yes-publish`:** when the caller passed `--yes-publish`, the
   human authorized this run in advance, on the strength of the critic's `ship`
   verdict alone (see SKILL.md's precedence rule). Still take the screenshot (it
   is the audit trail of what went out), then proceed to step 7 without asking.
   Do not open `podcast-reports/<slug>--<locale>.md` and do not delay for an
   advisory note in it — a genuine content problem shows up as a `fix` or
   `regenerate` verdict, not a caveat riding on a `ship`. This is the only gate
   `--yes-publish` removes: the auth/2FA/captcha stop in step 1, the
   upload/processing stop in step 3, the description two-attempt stop in step 4,
   and the verify-never-invent rule in step 8 are all unaffected.
7. **Publish now** once approved — click the Publish button (which publishes immediately because
   *Now* is selected). Screenshot to confirm the success state.
8. **Capture the embed link (verify, never invent):**
   - Read the `https://open.spotify.com/episode/<id>` URL from the **Share control's DOM**
     (regex the page/modal text for `open.spotify.com/episode/<id>`). Do **not** rely on the
     copy-link button + clipboard read — that has returned stale clipboard contents.
   - The draft episode id from step 3's URL is a strong candidate for `<id>` (see Site map), but
     CONFIRM it against the Share control before recording it.
   - **Propagation lag is normal:** a just-published episode's public page
     (`open.spotify.com/episode/<id>`) can return "couldn't find that podcast" for a few minutes;
     the **embed iframe** usually propagates faster. An initial 404 is NOT a failure — re-check,
     and confirm via the Share control (which is authoritative immediately).
   - If after polling the link still cannot be confirmed, this is not a publish failure — the
     episode already went out; only the link capture is incomplete. Print
     `STOP: episode published but embed link unconfirmed — paste the episode URL once it appears`.
     Never invent an id. In an unattended run nobody reads this live, so the recovery is manual and
     asynchronous: once the URL is confirmable, write the stub by hand with
     `python3 ${CLAUDE_PLUGIN_ROOT:-.}/scripts/podcast_stub.py podcasts/<slug>--<locale>.podcast.json --type spotify --url "<url>"`.
9. **Return** the captured episode URL to the calling skill.

## Out of scope
- Creating the show, handling credentials, bypassing captcha/2FA.
- Editing the .mp3 or the blog post.
