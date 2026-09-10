#!/usr/bin/env python3
# call_local.py - local counterpart of call_remote.py. Same contracts, same
# subcommands, no server / tunnel / token. EN + Kokoro only.
#
#   python call_local.py render     --script script.json --out out.mp3 \
#                                   [--voice-name af_heart] [--voice-name-2 am_adam] \
#                                   [--speed 1.0]
#   python call_local.py transcribe --mp3 out.mp3 --script script.json --out result.json
#
# render     - Kokoro ONNX on this machine (~2.5x realtime). Single narrator by
#              default; if script.json has two distinct speakers it renders a
#              dialogue, first speaker -> --voice-name, second -> --voice-name-2.
# transcribe - faster-whisper on this machine, emitting the same
#              {text, segments, overlapPct} shape the server returns.
#
# Must run under the Video-maker venv, which owns kokoro_onnx, faster_whisper
# and the model files:
#   "$VIDEOMAKER_ROOT/.venv/bin/python" scripts/call_local.py ...
import argparse
import difflib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

VIDEOMAKER = Path(os.environ.get("VIDEOMAKER_ROOT", str(Path.home() / "Documents/Video maker")))
GAP_SEC = 0.35          # breath between turns
DEFAULT_VOICE = "af_heart"    # US female
DEFAULT_VOICE_2 = "am_adam"   # US male
WHISPER_SIZE = os.environ.get("LOCAL_WHISPER_SIZE", "base.en")


def _videomaker_path():
    if not (VIDEOMAKER / "src" / "tts.py").exists():
        sys.exit(f"ERROR: no Video-maker checkout at {VIDEOMAKER}. Set VIDEOMAKER_ROOT.")
    sys.path.insert(0, str(VIDEOMAKER))


def _load_script(path):
    s = json.loads(Path(path).read_text(encoding="utf-8"))
    for t in s.get("turns", []):
        t.setdefault("text", t.get("line", ""))
        t.setdefault("speaker", t.get("voice", "host"))
    turns = [t for t in s.get("turns", []) if (t.get("text") or "").strip()]
    if not turns:
        sys.exit(f"ERROR: {path} has no turns with text.")
    if s.get("locale", "en") != "en":
        sys.exit(f"ERROR: call_local is EN-only; script says locale={s.get('locale')!r}.")
    return s, turns


def _norm(text):
    return re.findall(r"[a-z0-9']+", (text or "").lower())


def cmd_render(a):
    _videomaker_path()
    try:
        import numpy as np
        import soundfile as sf
        from src.tts import _KokoroBackend
    except ImportError as e:
        sys.exit(f"ERROR: run this with the Video-maker venv python ({e}).")

    script, turns = _load_script(a.script)

    # Speaker -> voice. One speaker means one voice; two means a dialogue.
    speakers = list(dict.fromkeys(t.get("speaker", "host") for t in turns))
    v1 = a.voice_name or script.get("voice") or DEFAULT_VOICE
    v2 = a.voice_name_2 or DEFAULT_VOICE_2
    voices = {speakers[0]: v1}
    if len(speakers) > 1:
        voices[speakers[1]] = v2
    for extra in speakers[2:]:      # 3+ speakers is not a shape this pipeline emits
        sys.exit(f"ERROR: {a.script} has {len(speakers)} speakers ({speakers}); max 2.")
    mode = "dialogue" if len(speakers) > 1 else "single"
    print(f"  mode={mode}  " + "  ".join(f"{s}={voices[s]}" for s in speakers), flush=True)

    be = _KokoroBackend.get()
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    pcm, sr = [], None
    with tempfile.TemporaryDirectory() as td:
        for i, t in enumerate(turns):
            spk = t.get("speaker", speakers[0])
            wav = Path(td) / f"{i:03d}.wav"
            dur, rate = be.synthesize_to_wav(t["text"], voices[spk], wav, speed=a.speed)
            audio, rate = sf.read(wav, dtype="float32")
            if sr is None:
                sr = rate
            elif rate != sr:
                sys.exit(f"ERROR: sample-rate changed mid-render ({sr} -> {rate}).")
            if pcm:
                pcm.append(np.zeros(int(GAP_SEC * sr), dtype="float32"))
            pcm.append(audio)
            print(f"  turn {i+1}/{len(turns)}  {dur:5.1f}s  {spk} ({voices[spk]})", flush=True)

        joined = Path(td) / "joined.wav"
        sf.write(joined, np.concatenate(pcm), sr)
        # ffmpeg because Kokoro emits PCM and the pipeline contract is an mp3.
        r = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(joined), "-b:a", "128k", str(out)],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            sys.exit(f"ERROR: ffmpeg failed: {r.stderr.strip()}")

    total = sum(len(c) for c in pcm) / sr
    print(f"RENDERED {out}  {total:.1f}s  mode={mode}  turns={len(turns)}")


def cmd_transcribe(a):
    _videomaker_path()
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        sys.exit(f"ERROR: run this with the Video-maker venv python ({e}).")

    model = WhisperModel(WHISPER_SIZE, device="cpu", compute_type="int8")
    segs, _ = model.transcribe(a.mp3, language="en")
    segments = [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
                for s in segs]
    text = " ".join(s["text"] for s in segments).strip()

    # overlapPct: word-sequence similarity against the script we asked for. Same
    # meaning as the server's number - "did it say what we wrote?" - so the
    # skill's >=85% rule reads the same either way.
    overlap = None
    if a.script:
        _, turns = _load_script(a.script)
        want = _norm(" ".join(t["text"] for t in turns))
        got = _norm(text)
        overlap = round(difflib.SequenceMatcher(None, want, got).ratio() * 100, 1)

    result = {"text": text, "segments": segments, "overlapPct": overlap}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"TRANSCRIBED {a.out}  segments={len(segments)}  overlapPct={overlap}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("render")
    r.add_argument("--script", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--voice-name", default=None, help=f"first speaker (default {DEFAULT_VOICE})")
    r.add_argument("--voice-name-2", default=None, help=f"second speaker (default {DEFAULT_VOICE_2})")
    r.add_argument("--speed", type=float, default=1.0)
    r.set_defaults(fn=cmd_render)

    t = sub.add_parser("transcribe")
    t.add_argument("--mp3", required=True)
    t.add_argument("--script", default=None, help="omit to skip overlapPct")
    t.add_argument("--out", required=True)
    t.set_defaults(fn=cmd_transcribe)

    a = ap.parse_args()
    a.speed = max(0.5, min(2.0, getattr(a, "speed", 1.0)))
    a.fn(a)


if __name__ == "__main__":
    main()
