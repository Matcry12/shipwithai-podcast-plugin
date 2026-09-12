#!/usr/bin/env python3
# render_dialogue.py — Client-side 2-speaker renderer for the Podcast Render Server.
#
# The server renders ONE voice per request (single-narrator). This script makes
# dialogue mode work without server changes: it splits the script into
# contiguous same-speaker groups, renders each group with that speaker's voice
# via call_remote.render(), and concatenates the segment MP3s with ffmpeg.
#
# Script shape (PRD dialogue variant):
#   { "host_mode": "dialogue",
#     "turns": [ {"voice": "host", "line": "..."},
#                {"voice": "cohost", "line": "..."} ] }
#
# Usage:
#   EN (kokoro presets):
#     python3 render_dialogue.py --script s.json --out out.mp3 --backend kokoro \
#       --host-voice-name af_heart --cohost-voice-name am_adam
#   VI (omnivoice cloning; falls back to $PODCAST_VI_VOICE[_2] / $PODCAST_VI_REF_TEXT[_2]):
#     python3 render_dialogue.py --script s.json --out out.mp3 --backend omnivoice \
#       --ov-speed 0.85
#   Smoke test (no server voices needed):
#     python3 render_dialogue.py --script s.json --out out.mp3 --backend dummy

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Robust to both invocation styles — mirrors call_remote.py's
# _import_render_dialogue(). A plain `from call_remote import ...` would load
# a *second*, distinct copy of call_remote.py when this module is reached via
# `from scripts.render_dialogue import ...` (package import): the resulting
# PodcastClientError class wouldn't be the same object as scripts.call_remote's,
# so `except PodcastClientError` there would silently fail to catch dialogue
# errors raised here. Try the relative import first so both entry points share
# one module; only fall back to sys.path + absolute import for direct script
# execution (`python3 scripts/render_dialogue.py ...`), where no parent
# package exists for a relative import to resolve against.
try:
    from .call_remote import PodcastClientError, render  # package import
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    from call_remote import PodcastClientError, render  # noqa: E402  script import

SPEAKERS = ("host", "cohost")

# Dropped-words guard. OmniVoice is non-autoregressive: it fixes the output
# frame budget up front from a text-weight × reference-clip-rate estimate, then
# has to fit every word into it. When the cloned voice's real pace is slower
# than that budget the model doesn't slow down, it silently omits clauses —
# deterministically, so a plain re-render reproduces the same hole (observed
# 2026-09-12: turns 1/5/15/29 of think-plan-execute-pattern--vi lost the same
# clauses across three re-renders; the render itself ran at 0.18–0.21 s/word).
# The one client-reachable knob that enlarges the budget is `speed` (budget ∝
# 1/speed), so a retry slows the turn down rather than rolling the dice again.
# Floor calibrated on VI omnivoice: turns with drops measured 0.18–0.21 s/word,
# intact ones ≥ 0.23. EN speech is slower per word, so the same floor holds.
# ponytail: one floor for both locales; split per locale if EN ever trips it.
MIN_SEC_PER_WORD = 0.23
RETRY_SLOWDOWN = 0.85
MAX_RETRIES = 2


def _probe_duration(path: Path) -> float:
    """Seconds of audio in *path*, via ffprobe."""
    return float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout.strip())


def render_turn_guarded(
    url: str, token: str, seg_script: Path, seg_mp3: Path, *,
    backend: str, voice_kwargs: dict, line: str, turn_no: int, verbose: bool = True,
) -> None:
    """Render one turn, re-rendering slower while its audio is too short for its words.

    Raises PodcastClientError after MAX_RETRIES if the turn is still short, so a
    dropped clause fails the render instead of surfacing three review cycles
    later. `dummy` is a silent placeholder with no speech to measure — skipped.
    """
    kw = dict(voice_kwargs)
    n_words = len(line.split())
    floor = n_words * MIN_SEC_PER_WORD
    for attempt in range(MAX_RETRIES + 1):
        render(url, token, seg_script, seg_mp3, backend=backend, verbose=False, **kw)
        if backend == "dummy":
            return
        dur = _probe_duration(seg_mp3)
        if verbose:
            print(f"[dialogue]   turn {turn_no}: {dur:.1f}s / {n_words} words = {dur / n_words:.2f} s/word")
        if dur >= floor:
            return
        opts = dict(kw.get("backend_opts") or {})
        opts["speed"] = round(opts.get("speed", 1.0) * RETRY_SLOWDOWN, 3)
        kw["backend_opts"] = opts
        if attempt < MAX_RETRIES:
            print(f"[dialogue] WARNING: turn {turn_no} rendered {dur:.1f}s for {n_words} words "
                  f"(floor {floor:.1f}s) — likely dropped words; retrying at speed {opts['speed']}",
                  file=sys.stderr)
    raise PodcastClientError(
        f"turn {turn_no} still too short after {MAX_RETRIES} retries: {dur:.1f}s for "
        f"{n_words} words (floor {floor:.1f}s) — the TTS is dropping words from: {line!r}"
    )


def group_turns(turns: list[dict]) -> list[tuple[str, list[dict]]]:
    """Split turns into contiguous same-speaker groups, preserving order."""
    groups: list[tuple[str, list[dict]]] = []
    for turn in turns:
        speaker = turn.get("voice")
        if speaker not in SPEAKERS:
            raise PodcastClientError(
                f"Dialogue turn has voice={speaker!r}; must be one of {SPEAKERS}"
            )
        if groups and groups[-1][0] == speaker:
            groups[-1][1].append(turn)
        else:
            groups.append((speaker, [turn]))
    return groups


def build_voice_kwargs(
    backend: str,
    locale: str,
    *,
    host_voice_name: str | None = None,
    cohost_voice_name: str | None = None,
    host_voice: str | None = None,
    host_ref_text: str | None = None,
    cohost_voice: str | None = None,
    cohost_ref_text: str | None = None,
    ov_speed: float | None = None,
    ov_num_step: int | None = None,
) -> dict[str, dict]:
    """Build per-speaker render() kwargs for a dialogue backend.

    kokoro uses presets (host_voice_name/cohost_voice_name, defaulting to
    af_heart/am_adam). omnivoice clones from PODCAST_<LOCALE>_VOICE[_2] /
    PODCAST_<LOCALE>_REF_TEXT[_2], with an explicit --*-voice/--*-ref-text
    taking precedence (ref-text is only inherited from env when its clip is
    also from env — an explicit clip's ref-text must be explicit too).
    dummy needs no per-speaker kwargs.
    """
    voices: dict[str, dict] = {"host": {}, "cohost": {}}
    if backend == "kokoro":
        voices["host"]["voice_name"] = host_voice_name or "af_heart"
        voices["cohost"]["voice_name"] = cohost_voice_name or "am_adam"
    elif backend == "omnivoice":
        env = os.environ.get

        def resolve(clip_arg, ref_arg, env_clip, env_ref):
            if clip_arg:
                return clip_arg, ref_arg
            return env_clip, (ref_arg or env_ref)

        pfx = "PODCAST_EN" if locale == "en" else "PODCAST_VI"
        pairs = {
            "host":   resolve(host_voice, host_ref_text,
                              env(f"{pfx}_VOICE"), env(f"{pfx}_REF_TEXT")),
            "cohost": resolve(cohost_voice, cohost_ref_text,
                              env(f"{pfx}_VOICE_2"), env(f"{pfx}_REF_TEXT_2")),
        }
        for speaker, (clip, ref_text) in pairs.items():
            opts: dict = {}
            if ov_speed is not None:
                opts["speed"] = ov_speed
            if ov_num_step is not None:
                opts["num_step"] = ov_num_step
            kw: dict = {}
            if clip:
                kw["voice"] = clip
                if ref_text:
                    opts["ref_text"] = ref_text
            else:
                print(f"[dialogue] WARNING: no ref clip for {speaker!r} — omnivoice "
                      "uses its default voice; host/cohost won't be distinct.",
                      file=sys.stderr)
            if opts:
                kw["backend_opts"] = opts
            voices[speaker] = kw
    elif backend != "dummy":
        raise PodcastClientError(
            f"unsupported dialogue backend {backend!r} (kokoro / omnivoice / dummy)"
        )
    return voices


def render_dialogue_to_mp3(
    url: str,
    token: str,
    script: dict,
    out: str | Path,
    backend: str,
    voices: dict[str, dict],
    *,
    gap: float = 0.5,
    fade: bool = True,
    verbose: bool = True,
) -> Path:
    """Render a dialogue-shape script dict to one MP3: per-turn render + ffmpeg concat.

    `voices` is the {"host": {...}, "cohost": {...}} kwargs map produced by
    build_voice_kwargs(). Factored out of main() so call_remote.py's unified
    `render` factory can dispatch dialogue scripts through the same
    grouping/concat logic as this module's own CLI, without duplicating it.
    """
    turns = script["turns"]
    for t in turns:
        if t.get("voice") not in SPEAKERS:
            raise PodcastClientError(
                f"Dialogue turn has voice={t.get('voice')!r}; must be one of {SPEAKERS}"
            )
    if verbose:
        print(f"[dialogue] {len(turns)} turns → {len(turns)} individual renders")

    out_path = Path(out)
    tmp_dir = Path(tempfile.mkdtemp(prefix="dialogue-"))
    try:
        segments: list[Path] = []
        # One render call per turn (not per same-speaker group): packing several
        # lines into a single render call left the model to generate them in one
        # continuous pass with no guaranteed clean boundary between lines, which
        # showed up as a break/glitch at the internal seam. A render call per
        # turn removes that seam — concat_mp3s already normalizes/gaps every
        # segment boundary uniformly, so this just makes every boundary a
        # concat boundary instead of some being buried inside one clip.
        for i, t in enumerate(turns):
            speaker = t["voice"]
            seg_script = tmp_dir / f"seg-{i:03d}-{speaker}.json"
            seg_script.write_text(json.dumps(
                {"host_mode": "single", "voice": "narrator",
                 "turns": [{"voice": "narrator", "line": t["line"]}]},
                ensure_ascii=False), encoding="utf-8")
            seg_mp3 = tmp_dir / f"seg-{i:03d}-{speaker}.mp3"
            if verbose:
                print(f"[dialogue] rendering turn {i + 1}/{len(turns)} ({speaker})")
            render_turn_guarded(url, token, seg_script, seg_mp3,
                                backend=backend, voice_kwargs=voices[speaker],
                                line=t["line"], turn_no=i + 1, verbose=verbose)
            segments.append(seg_mp3)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        concat_mp3s(segments, out_path, gap=gap, fade=fade)
        if verbose:
            print(f"[dialogue] ✅  Saved {out_path.stat().st_size:,} bytes → {out_path.resolve()}")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return out_path.resolve()


def concat_mp3s(segments: list[Path], out: Path, gap: float = 0.5, fade: bool = True) -> None:  # noqa: default matches CLI
    """Concatenate MP3 segments with ffmpeg, collapsing inter-turn silence.

    Each TTS render pads its clip with leading/trailing silence, so a raw concat
    stacks tail+head padding at every boundary → long gaps. `silenceremove` with
    stop_periods=-1 shortens every silent stretch anywhere in the stream down to
    `gap` seconds, leaving speech intact. Requires a re-encode (not stream copy),
    which is cheap for a handful of short segments.
    """
    # Each speaker's reference clip has its own loudness, so raw segments arrive
    # at different levels → one voice sounds louder than the other. Loudness-
    # normalize every segment to the same EBU R128 target before concat so both
    # speakers sit at equal perceived volume. Single-pass loudnorm is enough for
    # speech leveling. ponytail: single-pass; go two-pass only if levels still drift.
    # 30ms in/out fade per segment (not the whole-file intro/outro fade below) so
    # a hard concat boundary never lands on a sample discontinuity — this is what
    # made turn boundaries sound "trimmed"/clicky once whole-file fading was off.
    edge_fade = 0.03
    tmp_norm: list[Path] = []
    for seg in segments:
        norm = seg.with_suffix(".norm.mp3")
        dur = _probe_duration(seg)
        fade_out_start = max(0.0, dur - edge_fade)
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(seg),
             "-af", f"loudnorm=I=-16:TP=-1.5:LRA=11,"
                    f"afade=t=in:st=0:d={edge_fade},"
                    f"afade=t=out:st={fade_out_start}:d={edge_fade}",
             str(norm)],
            check=True, capture_output=True,
        )
        tmp_norm.append(norm)

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
        for seg in tmp_norm:
            fh.write(f"file '{seg.resolve()}'\n")
        list_path = fh.name
    # stop_threshold loosened (more negative) from -40dB to -50dB: -40dB was
    # classifying quiet speech onsets/tails (soft consonants, breath) as silence
    # and shaving them off along with the real gap, which is what sounded "trimmed".
    # -50dB only catches genuine silence.
    # apad: 2s of silence after the final turn, so the 3s outro fade below lands
    # mostly on silence rather than on speech. Without it a short sign-off ("Hẹn
    # gặp lại ở tập sau." ~2s) sits entirely inside the fade window and is taken
    # to near-silence -- present in the file, inaudible to Whisper, and the
    # critic fails the episode for a missing final turn. Observed 2026-09-12.
    # ponytail: fixed pad; scale it with the last turn's length if 2s ever proves
    # short for a longer sign-off.
    af = (f"silenceremove=stop_periods=-1:stop_duration={gap}"
          f":stop_threshold=-50dB:stop_silence={gap},"
          f"apad=pad_dur=2.0")
    concat_tmp = out.with_suffix(".concat.mp3") if fade else out
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
             "-i", list_path, "-af", af, str(concat_tmp)],
            check=True, capture_output=True,
        )
        if fade:
            # The first/last turn otherwise snap in and stop dead on the first/final
            # word — taper both ends instead of a hard cut. The outro fade needs to be
            # longer than the intro: measured on a real render, the last word's volume
            # was still near-full (-14dB) 3s from the end and dropped ~35dB within the
            # next second — a 1s fade starting at -1s only covers already-near-silent
            # tail, so the actual word-ending still sounds abrupt. A wider 3s outro
            # window overlaps the real decay instead of trailing behind it.
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "csv=p=0", str(concat_tmp)],
                check=True, capture_output=True, text=True,
            )
            duration = float(probe.stdout.strip())
            fade_in_dur = min(0.8, duration / 4)
            fade_out_dur = min(3.0, duration / 3)
            fade_out_start = max(0.0, duration - fade_out_dur)
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(concat_tmp),
                 "-af", f"afade=t=in:st=0:d={fade_in_dur},"
                        f"afade=t=out:st={fade_out_start}:d={fade_out_dur}",
                 str(out)],
                check=True, capture_output=True,
            )
    except subprocess.CalledProcessError as exc:
        raise PodcastClientError(
            f"ffmpeg concat failed:\n{exc.stderr.decode(errors='replace')[-400:]}"
        ) from exc
    finally:
        os.unlink(list_path)
        if fade:
            concat_tmp.unlink(missing_ok=True)
        for n in tmp_norm:
            n.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="render_dialogue.py",
        description="Render a 2-speaker dialogue script.json to one MP3.",
    )
    parser.add_argument("--url",     default=None, help="Server base URL (default: $PODCAST_URL)")
    parser.add_argument("--token",   default=None, help="Bearer token (default: $PODCAST_TOKEN)")
    parser.add_argument("--script",  required=True, help="Path to dialogue-shape script.json")
    parser.add_argument("--out",     required=True, help="Output MP3 path")
    parser.add_argument("--backend", required=True, help="TTS backend: kokoro / omnivoice / dummy")
    # Default matches call_remote.py's derived default ("en") — the two entry
    # points used to disagree (this one defaulted to "vi"), which would pick
    # different voice clips for the same unmarked script depending on which
    # CLI rendered it.
    parser.add_argument("--locale", default="en", choices=("en", "vi"),
                        help="Selects the omnivoice env-var prefix: en -> PODCAST_EN_*, vi -> PODCAST_VI_* (default en)")
    parser.add_argument("--host-voice-name",   default=None, help="Kokoro preset for host (e.g. af_heart)")
    parser.add_argument("--cohost-voice-name", default=None, help="Kokoro preset for cohost (e.g. am_adam)")
    parser.add_argument("--host-voice",     default=None, help="OmniVoice: host ref .wav (default: $PODCAST_<LOCALE>_VOICE)")
    parser.add_argument("--host-ref-text",  default=None, help="OmniVoice: host ref transcript (default: $PODCAST_<LOCALE>_REF_TEXT)")
    parser.add_argument("--cohost-voice",   default=None, help="OmniVoice: cohost ref .wav (default: $PODCAST_<LOCALE>_VOICE_2)")
    parser.add_argument("--cohost-ref-text", default=None, help="OmniVoice: cohost ref transcript (default: $PODCAST_<LOCALE>_REF_TEXT_2)")
    parser.add_argument("--ov-speed",    type=float, default=None, help="OmniVoice: playback rate")
    parser.add_argument("--ov-num-step", type=int,   default=None, help="OmniVoice: diffusion steps")
    parser.add_argument("--gap", type=float, default=0.5, help="Seconds of silence to keep between turns (default 0.5)")
    parser.add_argument("--no-fade", action="store_true", help="Skip the intro/outro fade-in/fade-out")
    args = parser.parse_args()

    url = args.url or os.environ.get("PODCAST_URL", "")
    token = args.token or os.environ.get("PODCAST_TOKEN", "")
    if args.backend != "dummy" and (not url or not token):
        sys.exit("ERROR: missing --url/--token (or export PODCAST_URL / PODCAST_TOKEN)")

    script_path = Path(args.script)
    script = json.loads(script_path.read_text(encoding="utf-8"))
    if script.get("host_mode") != "dialogue":
        sys.exit(f"ERROR: {script_path} has host_mode={script.get('host_mode')!r}; expected 'dialogue'")

    try:
        voices = build_voice_kwargs(
            args.backend, args.locale,
            host_voice_name=args.host_voice_name, cohost_voice_name=args.cohost_voice_name,
            host_voice=args.host_voice, host_ref_text=args.host_ref_text,
            cohost_voice=args.cohost_voice, cohost_ref_text=args.cohost_ref_text,
            ov_speed=args.ov_speed, ov_num_step=args.ov_num_step,
        )
        render_dialogue_to_mp3(
            url, token, script, args.out, args.backend, voices,
            gap=args.gap, fade=not args.no_fade,
        )
    except (PodcastClientError, FileNotFoundError) as exc:
        sys.exit(f"ERROR: {exc}")


if __name__ == "__main__":
    # ponytail: self-check — `render_dialogue.py selftest` exercises grouping only.
    if len(sys.argv) == 2 and sys.argv[1] == "selftest":
        g = group_turns([
            {"voice": "host", "line": "A."}, {"voice": "host", "line": "B."},
            {"voice": "cohost", "line": "C."}, {"voice": "host", "line": "D."},
        ])
        assert [(s, len(t)) for s, t in g] == [("host", 2), ("cohost", 1), ("host", 1)], g
        print("selftest OK")
        sys.exit(0)
    main()
