#!/usr/bin/env python3
# podcast_stub.py — canonical reader/writer for the `podcast` embed block in a
# <slug>.podcast.json stub. Pure standard library (matches scripts/r2_upload.py).
#
# The block is what the website player component consumes:
#   "podcast": {
#     "type":      "audio" | "spotify",   # which player branch renders it
#     "url":       "<canonical link>",     # mp3 URL (audio) | episode page (spotify)
#     "embedUrl":  "<src the site uses>",  # mp3 URL (audio) | /embed/episode/<id>
#     "episodeId": "<spotify id>"          # spotify only; "" for audio
#   }
# It stays all-empty until a posting backend fills it.

from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

VALID_TYPES = ("audio", "spotify")
_EPISODE_RE = re.compile(r"/episode/([A-Za-z0-9]+)")


def _spotify_episode_id(url: str) -> str:
    m = _EPISODE_RE.search(url or "")
    return m.group(1) if m else ""


def build_block(podcast_type, url, embed_url=None, episode_id=None) -> dict:
    if podcast_type not in VALID_TYPES:
        raise ValueError(f"--type must be one of {VALID_TYPES}, got {podcast_type!r}")
    if not url:
        raise ValueError("--url is required")
    if podcast_type == "audio":
        return {"type": "audio", "url": url, "embedUrl": embed_url or url, "episodeId": ""}
    ep = episode_id or _spotify_episode_id(url)
    if not ep:
        raise ValueError(
            "spotify --url has no /episode/<id> segment; pass --episode-id explicitly")
    return {
        "type": "spotify",
        "url": url,
        "embedUrl": embed_url or f"https://open.spotify.com/embed/episode/{ep}",
        "episodeId": ep,
    }


def validate_block(block) -> str | None:
    """Return an error string, or None if the block is valid (empty = valid)."""
    if not isinstance(block, dict):
        return "podcast block is missing or not an object"
    t = block.get("type", "")
    if t == "":
        return None
    if t not in VALID_TYPES:
        return f"type {t!r} is not one of {VALID_TYPES}"
    if not block.get("url"):
        return f"type={t} requires a non-empty url"
    if not block.get("embedUrl"):
        return f"type={t} requires a non-empty embedUrl"
    if t == "spotify" and not block.get("episodeId"):
        return "type=spotify requires a non-empty episodeId"
    return None


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="podcast_stub.py",
        description="Read/write the `podcast` embed block in a .podcast.json stub.")
    ap.add_argument("stub", help="Path to <slug>.podcast.json")
    ap.add_argument("--type", choices=VALID_TYPES, help="Embed type to write")
    ap.add_argument("--url", help="Canonical URL (mp3 for audio; episode page for spotify)")
    ap.add_argument("--embed-url", dest="embed_url", default=None,
                    help="Override the embed src (else derived)")
    ap.add_argument("--episode-id", dest="episode_id", default=None,
                    help="Spotify episode id (else parsed from --url)")
    ap.add_argument("--validate", action="store_true",
                    help="Validate the existing block; write nothing")
    args = ap.parse_args()

    path = Path(args.stub)
    if not path.is_file():
        sys.exit(f"ERROR: stub not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))

    if args.validate:
        err = validate_block(data.get("podcast"))
        if err:
            sys.exit(f"INVALID: {path} — {err}")
        print(f"VALID: {path}")
        return

    if not args.type:
        sys.exit("ERROR: --type is required unless --validate is given")
    try:
        block = build_block(args.type, args.url, args.embed_url, args.episode_id)
    except ValueError as e:
        sys.exit(f"ERROR: {e}")
    data["podcast"] = block
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[stub] wrote podcast block ({block['type']}) -> {path}", file=sys.stderr)
    print(block["embedUrl"])


if __name__ == "__main__":
    main()
