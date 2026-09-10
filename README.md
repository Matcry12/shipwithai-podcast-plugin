# shipwithai-podcast

Turns a reviewed blog draft into a published podcast episode, and writes the
episode link back into the post.

```
draft ──▶ rewrite for the ear ──▶ TTS render ──▶ critic ──▶ Spotify ──▶ podcast: yml
```

Runs by hand, or unattended on a self-hosted GitHub Actions runner when a blog
post is pushed.

## Quick start

```bash
cp .env.example .env      # then fill in the render server + voice clips
bash scripts/runner-doctor.sh
```

Fix every `FAIL` it reports, then:

```bash
claude -p "/content-podcast-all <draft>.md --mode dialogue"
```

That renders, reviews, and stops at the publish confirm.

## Commands

| Command | Does |
|---|---|
| `/content-podcast` | rewrite for the ear, render the mp3, Whisper QA |
| `/content-podcast-review` | independent critic, scored report, ship/fix/regenerate |
| `/content-podcast-posting` | publish to Spotify for Creators, or upload to R2 |
| `/content-podcast-all` | the first three in order, gated on `ship` — never auto-publishes |

## Unattended

`scripts/ci-podcast.sh` is what CI runs. It diffs a push for new blog posts,
skips any that already have an episode, then renders → reviews → publishes →
injects the `podcast:` block and pushes it back with `[skip ci]`.

It must run on a **self-hosted** runner. Three of its inputs cannot exist on a
cloud VM: the drafts are gitignored, the TTS server is on a private network, and
Spotify for Creators has no publishing API so publishing drives a real
logged-in browser.

The workflow that calls it lives in the site repo, not here.

## Inputs from elsewhere

- **Drafts** — written by `shipwithai-content-agent-plugin` and gitignored there.
  Set `DRAFTS_DIR`; the default assumes both repos sit side by side.
- **Voice clips** — reference `.wav` files for voice cloning, stored outside both
  repos. Without them EN falls back to preset voices.
- **Render server** — `PODCAST_URL` / `PODCAST_TOKEN`.

## Warning

`--yes-publish` skips the human confirm and publishes irreversibly to a public
feed. CI passes it on every qualifying push; the critic's `ship` verdict is then
the only gate. A duplicate episode can only be removed by hand in the Spotify
dashboard.
