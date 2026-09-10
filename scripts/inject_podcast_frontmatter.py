#!/usr/bin/env python3
# Inject the `podcast` block from a <slug>.podcast.json stub into a published
# post's YAML frontmatter, in place. Used by /content-publish (Step 6.5) so a
# post ships with its player wired. Pure standard library (matches
# scripts/podcast_stub.py / scripts/r2_upload.py — no PyYAML, PEP-668 safe).
#
# Behavior:
#   - No stub, or stub's podcast.type is empty  -> NO-OP (exit 0). Podcast is
#     optional; a post without one ships unchanged.
#   - Otherwise: write a top-level `podcast:` block into the frontmatter,
#     replacing any existing one. Idempotent (re-running is safe).
#
# Usage:
#   inject_podcast_frontmatter.py <post.md> --stub podcasts/<slug>.podcast.json
#
# Output (stdout): one line, e.g.
#   PODCAST-EMBED: injected spotify (https://open.spotify.com/embed/episode/<id>)
#   PODCAST-EMBED: none (no stub)
#   PODCAST-EMBED: none (empty block)

import argparse
import json
import os
import sys

VALID_TYPES = ("audio", "spotify")


def _read_block(stub_path):
    """Return the podcast block dict, or None if there is nothing to inject."""
    if not stub_path or not os.path.exists(stub_path):
        print("PODCAST-EMBED: none (no stub)")
        return None
    try:
        with open(stub_path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        sys.exit(f"PODCAST-EMBED-FAIL: stub {stub_path} is not readable JSON: {e}")
    block = data.get("podcast")
    if not isinstance(block, dict) or block.get("type") not in VALID_TYPES:
        print("PODCAST-EMBED: none (empty block)")
        return None
    # Minimal validation — mirror podcast_stub.validate_block's essentials.
    if not block.get("url") or not block.get("embedUrl"):
        sys.exit(f"PODCAST-EMBED-FAIL: stub {stub_path} has type={block['type']} "
                 "but is missing url/embedUrl")
    if block["type"] == "spotify" and not block.get("episodeId"):
        sys.exit(f"PODCAST-EMBED-FAIL: stub {stub_path} type=spotify requires episodeId")
    return block


def _yaml_lines(block):
    """Render the podcast block as frontmatter lines (2-space indent).

    Values are simple strings (URLs, ids) with no YAML-special chars, so they
    are emitted bare — consistent with how the existing posts write scalars.
    episodeId is omitted when empty (audio); the website schema treats it as
    optional.
    """
    def q(v):
        # Single-quote scalars so YAML-special chars (':', '#', leading @!*&[{,
        # spaces) in a user-supplied audio URL can't break or silently re-shape
        # the frontmatter. Embedded single quotes are doubled per YAML rules.
        return "'" + str(v).replace("'", "''") + "'"

    lines = ["podcast:",
             f"  type: {block['type']}",
             f"  url: {q(block['url'])}",
             f"  embedUrl: {q(block['embedUrl'])}"]
    if block.get("episodeId"):
        lines.append(f"  episodeId: {q(block['episodeId'])}")
    return lines


def _split_frontmatter(text):
    """Return (pre, fm_lines, rest) where fm_lines are the lines BETWEEN the
    opening and closing `---`. Raises if there is no frontmatter."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        sys.exit("PODCAST-EMBED-FAIL: file has no opening '---' frontmatter")
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return lines[0], lines[1:i], lines[i:]
    sys.exit("PODCAST-EMBED-FAIL: frontmatter has no closing '---'")


def _strip_existing_podcast(fm_lines):
    """Drop an existing top-level `podcast:` block (the key line plus its
    indented children) so re-injection replaces rather than duplicates."""
    out = []
    skipping = False
    for line in fm_lines:
        if not skipping and line.startswith("podcast:"):
            skipping = True
            continue
        if skipping:
            # Children are indented; a non-indented, non-blank line ends the block.
            if line.startswith((" ", "\t")) or line.strip() == "":
                continue
            skipping = False
        out.append(line)
    return out


def main():
    ap = argparse.ArgumentParser(description="Inject podcast block into post frontmatter")
    ap.add_argument("post", help="Path to the published post markdown file")
    ap.add_argument("--stub", help="Path to <slug>.podcast.json")
    args = ap.parse_args()

    block = _read_block(args.stub)
    if block is None:
        return  # no-op, already logged

    with open(args.post, encoding="utf-8") as f:
        text = f.read()
    trailing_nl = text.endswith("\n")

    opener, fm_lines, rest = _split_frontmatter(text)
    fm_lines = _strip_existing_podcast(fm_lines)
    fm_lines = fm_lines + _yaml_lines(block)

    new_text = "\n".join([opener] + fm_lines + rest)
    if trailing_nl:
        new_text += "\n"
    with open(args.post, "w", encoding="utf-8") as f:
        f.write(new_text)

    print(f"PODCAST-EMBED: injected {block['type']} ({block['embedUrl']})")


if __name__ == "__main__":
    main()
