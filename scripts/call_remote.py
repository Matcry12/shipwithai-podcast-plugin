#!/usr/bin/env python3
# call_remote.py — Caller-side client for the Podcast Render Server.
# Requires: requests  (pip install requests)
#
# Usage (CLI):
#   python call_remote.py render     --url URL --token TOKEN --script script.json --out out.mp3 \
#                                    [--backend chatterbox|kokoro|vieneu|omnivoice|dummy] \
#                                    [--voice ref.wav]        # voice cloning
#                                    [--voice-name af_heart]  # kokoro / vieneu preset
#   python call_remote.py transcribe --url URL --token TOKEN --mp3 file.mp3 [--script s.json] --out result.json
#
# Usage (programmatic):
#   from scripts.call_remote import render, transcribe
#   mp3_path = render(url, token, "script.json", "out.mp3", backend="kokoro")
#   result   = transcribe(url, token, "out.mp3", "result.json")
#
# Engines:
#   chatterbox  — EN voice cloning from a .wav clip (voice=); GPU-intensive.
#   kokoro      — EN fast preset voices (voice_name=, e.g. af_heart / af_sarah / am_adam).
#   vieneu      — VI + bilingual TTS; voice clone (voice=) or preset (voice_name=).
#                 Auto-reads $PODCAST_VI_VOICE for the clip if voice= is not passed.
#   omnivoice   — Multilingual zero-shot voice cloning (600+ languages incl. VI).
#                 Tunable via backend_opts=. Auto-reads $PODCAST_VI_VOICE if voice= omitted.
#   dummy       — silent MP3 placeholder for pipeline smoke tests.

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:
    sys.exit(
        "ERROR: 'requests' is not installed.\n"
        "Install it with:  pip install requests"
    )


# ── Public exception ──────────────────────────────────────────────────────────

class PodcastClientError(RuntimeError):
    """Raised by render() / transcribe() on any non-2xx response or bad input."""


# ── Internal helpers ──────────────────────────────────────────────────────────

def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _check_response(resp: "requests.Response", context: str) -> None:
    if resp.status_code == 401:
        raise PodcastClientError(
            f"[{context}] 401 Unauthorized — wrong or missing bearer token.\n"
            f"Check that the token matches the TOKEN printed by start.command."
        )
    if resp.status_code == 404:
        raise PodcastClientError(
            f"[{context}] 404 Not Found — is the URL correct?\n"
            f"Received: {resp.text[:200]}"
        )
    if 400 <= resp.status_code < 500:
        raise PodcastClientError(
            f"[{context}] {resp.status_code} Client Error\n{resp.text[:400]}"
        )
    if resp.status_code >= 500:
        raise PodcastClientError(
            f"[{context}] {resp.status_code} Server Error\n{resp.text[:400]}"
        )


# ── Factory functions (importable) ────────────────────────────────────────────

def health(url: str, token: str) -> dict:
    """Hit /health and return the JSON, or raise PodcastClientError."""
    import requests
    try:
        resp = requests.get(
            url.rstrip("/") + "/health",
            headers=_auth_header(token),
            timeout=10,
        )
    except requests.exceptions.ConnectionError as exc:
        raise PodcastClientError(
            f"[health] Could not connect to {url}\n"
            "Is start.command running? Check the server terminal."
        ) from exc
    except requests.exceptions.Timeout:
        raise PodcastClientError("[health] Health check timed out — server may be overloaded.")
    _check_response(resp, "health")
    return resp.json()


def render(
    url: str,
    token: str,
    script: str | Path,
    out: str | Path,
    *,
    backend: str | None = None,
    voice: str | Path | None = None,
    voice_name: str | None = None,
    backend_opts: dict[str, Any] | None = None,
    verbose: bool = True,
) -> Path:
    """Render a script.json to an MP3 via the remote server.

    Parameters
    ----------
    url:          Server base URL, e.g. "https://xxxx.ngrok-free.app"
    token:        Bearer token printed by start.command
    script:       Path to a PRD-shape script.json file
    out:          Output MP3 path to write
    backend:      TTS backend name (chatterbox / kokoro / vieneu / omnivoice / dummy)
    voice:        Path to a .wav reference clip for voice cloning
    voice_name:   Preset voice name (kokoro: "af_heart"; vieneu: "Đức Trí")
    backend_opts: Dict of backend-specific params, e.g. {"num_step": 16} for omnivoice
    verbose:      Print progress lines (default True)

    Returns
    -------
    Path  — absolute path to the written MP3 file

    Raises
    ------
    PodcastClientError — on any server or client error
    FileNotFoundError  — if script or voice file does not exist
    """
    script_path = Path(script)
    if not script_path.exists():
        raise FileNotFoundError(f"Script file not found: {script_path}")

    endpoint = url.rstrip("/") + "/render"
    if verbose:
        print(f"[render] POST {endpoint}")
        print(f"[render] Script: {script_path}  ({script_path.stat().st_size} bytes)")

    data: dict = {"script": script_path.read_text(encoding="utf-8")}
    if backend:
        data["backend"] = backend
        if verbose:
            print(f"[render] Backend: {backend}")

    if voice_name:
        if backend == "chatterbox":
            if verbose:
                print("[render] NOTE: --voice-name ignored by chatterbox (uses --voice clip)")
        else:
            data["voice_name"] = voice_name
            if verbose:
                print(f"[render] Voice name: {voice_name}")

    if backend_opts:
        data["backend_opts"] = json.dumps(backend_opts)
        if verbose:
            print(f"[render] Backend opts: {backend_opts}")

    files: dict = {}
    voice_fh = None
    if voice:
        if backend == "kokoro":
            if verbose:
                print("[render] NOTE: voice clip ignored by kokoro (uses --voice-name preset)")
        voice_path = Path(voice)
        if not voice_path.exists():
            raise FileNotFoundError(f"Voice reference file not found: {voice_path}")
        voice_fh = voice_path.open("rb")
        files["voice"] = (voice_path.name, voice_fh, "audio/wav")
        if verbose:
            print(f"[render] Voice ref: {voice_path}  ({voice_path.stat().st_size:,} bytes)")
    elif not voice_name and verbose:
        print("[render] Voice ref: (none — server will use bundled narrator.wav)")

    try:
        resp = requests.post(
            endpoint,
            headers=_auth_header(token),
            data=data,
            files=files if files else None,
            stream=True,
            timeout=600,
        )
    except requests.exceptions.ConnectionError as exc:
        raise PodcastClientError(f"[render] Could not connect to {endpoint}\n{exc}") from exc
    except requests.exceptions.Timeout:
        raise PodcastClientError("[render] Request timed out after 600 s — render still running on server.")
    finally:
        if voice_fh:
            voice_fh.close()

    _check_response(resp, "render")

    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Write to a .part sibling and rename into place only on success, so a
    # truncated/interrupted response (e.g. requests.ChunkedEncodingError mid-
    # stream) never leaves a partial file sitting at the real output path
    # looking like a valid render.
    tmp_path = out_path.with_name(out_path.name + ".part")
    total = 0
    try:
        with tmp_path.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
                    total += len(chunk)
    except requests.exceptions.RequestException as exc:
        tmp_path.unlink(missing_ok=True)
        raise PodcastClientError(
            f"[render] Download interrupted after {total:,} bytes: {exc}\n"
            "No partial file was written to the output path — re-run the render."
        ) from exc

    if total == 0:
        tmp_path.unlink(missing_ok=True)
        raise PodcastClientError("[render] Server returned an empty file — check server logs.")

    tmp_path.replace(out_path)  # atomic rename on the same filesystem
    if verbose:
        print(f"[render] ✅  Saved {total:,} bytes → {out_path.resolve()}")
    return out_path.resolve()


def transcribe(
    url: str,
    token: str,
    mp3: str | Path,
    out: str | Path,
    *,
    script: str | Path | None = None,
    verbose: bool = True,
) -> dict:
    """Transcribe an MP3 via the remote server.

    Parameters
    ----------
    url:    Server base URL
    token:  Bearer token
    mp3:    Path to the MP3 file to transcribe
    out:    Output JSON path to write
    script: (Optional) path to script.json for overlap scoring

    Returns
    -------
    dict  — {"text": str, "segments": list, "overlapPct": float | None}

    Raises
    ------
    PodcastClientError — on any server or client error
    FileNotFoundError  — if mp3 or script file does not exist
    """
    mp3_path = Path(mp3)
    if not mp3_path.exists():
        raise FileNotFoundError(f"MP3 file not found: {mp3_path}")

    endpoint = url.rstrip("/") + "/transcribe"
    if verbose:
        print(f"[transcribe] POST {endpoint}")
        print(f"[transcribe] Audio: {mp3_path}  ({mp3_path.stat().st_size:,} bytes)")

    files: dict = {"file": (mp3_path.name, mp3_path.open("rb"), "audio/mpeg")}
    data: dict = {}
    if script:
        script_path = Path(script)
        if not script_path.exists():
            raise FileNotFoundError(f"Script file not found: {script_path}")
        data["script"] = script_path.read_text(encoding="utf-8")

    try:
        resp = requests.post(
            endpoint,
            headers=_auth_header(token),
            files=files,
            data=data,
            timeout=600,
        )
    except requests.exceptions.ConnectionError as exc:
        raise PodcastClientError(f"[transcribe] Could not connect to {endpoint}\n{exc}") from exc
    except requests.exceptions.Timeout:
        raise PodcastClientError("[transcribe] Request timed out after 600 s.")

    _check_response(resp, "transcribe")

    result = resp.json()
    if verbose:
        overlap = result.get("overlapPct", result.get("overlap_pct", "n/a"))
        print(f"[transcribe] overlapPct: {overlap}")

    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    if verbose:
        print(f"[transcribe] ✅  Saved result → {out_path.resolve()}")
    return result


# ── Locale detection ──────────────────────────────────────────────────────────

# Vietnamese-specific characters not found in other Latin scripts.
# U+1E00–U+1EFF (Latin Extended Additional) is almost entirely Vietnamese
# tone-marked vowels; the extra set covers ă/đ/ơ/ư which sit outside that block.
_VI_EXTRA = frozenset("ăĂđĐơƠưƯ")


def _detect_locale_from_script(script_dict: dict) -> str:
    """Return 'vi' if script text looks Vietnamese, else 'en'."""
    turns = script_dict.get("turns", [])
    text = " ".join(t.get("line") or t.get("text", "") for t in turns)
    if not text:
        return "en"
    vi_chars = sum(
        1 for ch in text
        if ch in _VI_EXTRA or ("Ḁ" <= ch <= "ỿ")
    )
    return "vi" if vi_chars / len(text) > 0.005 else "en"


# ── render factory: derive mode/locale/backend/voices, explicit flags win ─────
#
# Canonical single call: `call_remote.py render --script s.json --out o.mp3`.
# Everything else (single vs dialogue, locale, backend, voice/ref-text env
# fallbacks) is derived below; any flag the caller does pass takes precedence
# over the derived value, so today's explicit-flag invocations behave exactly
# as they did before this factory existed.

def _resolve_mode(script_dict: dict) -> str:
    """'dialogue' if host_mode == 'dialogue'; 'single' if host_mode is absent.

    An explicitly-present but unrecognized value (typo, e.g. 'dialouge') is
    rejected rather than silently treated as 'single' — a silent wrong mode
    is worse than a crash.
    """
    mode = script_dict.get("host_mode")
    if mode is None:
        return "single"
    if mode in ("single", "dialogue"):
        return mode
    raise PodcastClientError(
        f"unknown host_mode {mode!r} in script; expected one of: single, dialogue"
    )


def _stem_locale(path: str | Path) -> str | None:
    """'en'/'vi' from a --en/--vi filename suffix, or None if neither matches."""
    stem = Path(path).stem
    if stem.endswith("--en"):
        return "en"
    if stem.endswith("--vi"):
        return "vi"
    return None


def _resolve_locale(
    script_path: str | Path,
    out_path: str | Path,
    script_dict: dict,
    *,
    explicit_locale: str | None = None,
) -> str:
    """Resolve locale, in precedence order: explicit --locale > --script suffix >
    --out suffix > script-text detection (warns) > 'en' default (warns).

    A --script/--out suffix disagreement (e.g. foo--en.json -> foo--vi.mp3) is
    an error, not a coin flip: silently picking one risks rendering VI text in
    EN voices (or vice versa) with no signal to the caller.
    """
    if explicit_locale:
        return explicit_locale

    script_locale = _stem_locale(script_path)
    out_locale = _stem_locale(out_path)
    if script_locale and out_locale and script_locale != out_locale:
        raise PodcastClientError(
            f"conflicting locale: --script suggests {script_locale!r} "
            f"({Path(script_path).name}) but --out suggests {out_locale!r} "
            f"({Path(out_path).name}); pass --locale to disambiguate"
        )
    if script_locale:
        return script_locale
    if out_locale:
        return out_locale

    # Neither filename carries a --en/--vi suffix: fall back to inspecting the
    # script text itself, then finally to 'en' — but never silently. Print
    # exactly which assumption was made so a VI script without the suffix
    # doesn't quietly render in English voices.
    detected = _detect_locale_from_script(script_dict)
    print(
        f"[render] WARNING: could not determine locale from --script/--out "
        f"filename suffix ('--en'/'--vi'); falling back to script-text "
        f"detection -> {detected!r}. Pass --locale en|vi to make this explicit.",
        file=sys.stderr,
    )
    return detected


def _resolve_backend(locale: str, *, dialogue: bool) -> str:
    """Per-locale engine auto-detection — reuses the rule documented in
    skills/content-podcast/SKILL.md Step 0 ("Engine auto-detection"):

    EN prefers omnivoice when it is configured (PODCAST_EN_VOICE, plus
    PODCAST_EN_VOICE_2 for dialogue, set in the environment), else falls back
    to kokoro. VI has no fallback engine — omnivoice is always selected.

    Note: the SKILL.md rule also cross-checks the server's /health response
    to confirm omnivoice is actually loaded. This derivation is pure/offline
    (no network, so it works under --dry-run) and only checks the env-var
    half of that rule; the skill-level flow remains responsible for the
    live health check and for stopping VI renders when the clip env vars
    are unset.
    """
    prefix = f"PODCAST_{locale.upper()}"
    configured = bool(os.environ.get(f"{prefix}_VOICE"))
    if dialogue:
        configured = configured and bool(os.environ.get(f"{prefix}_VOICE_2"))
    if locale == "en":
        return "omnivoice" if configured else "kokoro"
    return "omnivoice"


def _import_render_dialogue():
    """Import render_dialogue's dialogue-rendering helpers.

    Robust to both invocation styles:
      - `python3 scripts/call_remote.py ...`   (script exec; __package__ == "")
      - `from scripts.call_remote import ...`  (package import; __package__ == "scripts")
    A relative import only resolves in the second case (it needs a known
    parent package). Script execution falls back to a plain absolute import,
    which works because Python already puts this file's own directory
    (scripts/) on sys.path when it runs the script directly.
    """
    try:
        from . import render_dialogue as _rd  # package import
    except ImportError:
        import render_dialogue as _rd  # script import: scripts/ already on sys.path
    return _rd


def _plan_render(args: argparse.Namespace, script_dict: dict) -> dict[str, Any]:
    """Resolve the full render plan from CLI args + script.json.

    Every field an explicit flag already covers is taken from args as-is;
    only omitted fields are derived. Returns a JSON-printable plan dict.
    """
    mode = _resolve_mode(script_dict)
    locale = _resolve_locale(
        args.script, args.out, script_dict,
        explicit_locale=getattr(args, "locale", None),
    )
    backend = args.backend or _resolve_backend(locale, dialogue=(mode == "dialogue"))

    plan: dict[str, Any] = {
        "mode": mode, "locale": locale, "backend": backend,
        "script": str(args.script), "out": str(args.out),
    }

    if mode == "single":
        voice = args.voice
        ref_text = args.ov_ref_text
        # Existing vieneu/omnivoice env fallback, generalized from the old
        # hardcoded PODCAST_VI_VOICE-only lookup to the derived locale (so it
        # also works for an EN omnivoice render) — same PODCAST_<LOCALE>_VOICE
        # / _REF_TEXT convention render_dialogue.py already uses per speaker.
        if backend in ("vieneu", "omnivoice") and not voice:
            prefix = f"PODCAST_{locale.upper()}"
            voice = os.environ.get(f"{prefix}_VOICE") or None
            ref_text = ref_text or os.environ.get(f"{prefix}_REF_TEXT")

        ov_opts: dict[str, Any] = {}
        for key, attr in [
            ("num_step",        "ov_num_step"),
            ("guidance_scale",  "ov_guidance_scale"),
            ("speed",           "ov_speed"),
            ("denoise",         "ov_denoise"),
            ("t_shift",         "ov_t_shift"),
            ("class_temperature", "ov_class_temp"),
        ]:
            val = getattr(args, attr, None)
            if val is not None:
                ov_opts[key] = val
        if ref_text:
            ov_opts["ref_text"] = ref_text

        plan["voice"] = str(voice) if voice else None
        plan["voice_name"] = args.voice_name
        plan["backend_opts"] = ov_opts or None
    else:
        # Dialogue path only honors --backend / --ov-speed / --ov-num-step
        # (applied to both speakers); per-speaker voice/ref-text comes from
        # PODCAST_<LOCALE>_VOICE[_2] / _REF_TEXT[_2] in .env. Any other flag
        # the caller passed here is silently unused unless we say so — same
        # convention render() already follows for --voice-name/chatterbox and
        # --voice/kokoro.
        for flag, val in [
            ("--voice", args.voice),
            ("--voice-name", args.voice_name),
            ("--ov-ref-text", args.ov_ref_text),
            ("--ov-guidance-scale", args.ov_guidance_scale),
            ("--ov-denoise", args.ov_denoise),
            ("--ov-t-shift", args.ov_t_shift),
            ("--ov-class-temp", args.ov_class_temp),
        ]:
            if val is not None:
                print(
                    f"[render] NOTE: {flag} ignored on the dialogue path — "
                    "per-speaker voices come from PODCAST_<LOCALE>_VOICE[_2]/"
                    "_REF_TEXT[_2] (.env). For per-speaker control, call "
                    "scripts/render_dialogue.py directly.",
                    file=sys.stderr,
                )
        _rd = _import_render_dialogue()
        plan["voices"] = _rd.build_voice_kwargs(
            backend, locale,
            ov_speed=args.ov_speed, ov_num_step=args.ov_num_step,
        )

    return plan


# ── CLI wrapper ───────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="call_remote.py",
        description="Client for the Podcast Render Server.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_render = sub.add_parser("render", help="Render a script.json to an MP3 file.")
    p_render.add_argument("--url",     default=None, help="Server base URL (default: $PODCAST_URL)")
    p_render.add_argument("--token",   default=None, help="Bearer token (default: $PODCAST_TOKEN)")
    p_render.add_argument("--script",  required=True, help="Path to PRD-shape script.json")
    p_render.add_argument("--out",     required=True, help="Output MP3 path")
    p_render.add_argument("--locale",  default=None, choices=("en", "vi"),
                           help="Force locale instead of deriving it from the --script/--out --en/--vi suffix "
                                "(or, absent that, script-text detection).")
    p_render.add_argument("--voice",      default=None, help="Path to a .wav reference clip for voice cloning")
    p_render.add_argument("--voice-name", default=None, dest="voice_name", help="Preset voice name (kokoro: af_heart; vieneu: Đức Trí)")
    p_render.add_argument("--backend",    default=None, help="TTS backend: chatterbox / kokoro / vieneu / omnivoice / dummy")
    p_render.add_argument("--ov-num-step",       type=int,   default=None, dest="ov_num_step",       help="OmniVoice: diffusion steps (default 32)")
    p_render.add_argument("--ov-guidance-scale", type=float, default=None, dest="ov_guidance_scale", help="OmniVoice: guidance scale (default 2.0)")
    p_render.add_argument("--ov-speed",          type=float, default=None, dest="ov_speed",          help="OmniVoice: playback rate (default 1.0)")
    p_render.add_argument("--ov-denoise",        type=lambda x: x.lower() not in ("0","false","no"), default=None, dest="ov_denoise", help="OmniVoice: noise removal (default true)")
    p_render.add_argument("--ov-t-shift",        type=float, default=None, dest="ov_t_shift",        help="OmniVoice: noise schedule shift (default 0.1)")
    p_render.add_argument("--ov-class-temp",     type=float, default=None, dest="ov_class_temp",     help="OmniVoice: token temperature (default 0.0)")
    p_render.add_argument("--ov-ref-text",       type=str,   default=None, dest="ov_ref_text",       help="OmniVoice: transcription of the reference clip (skips internal Whisper)")
    p_render.add_argument("--dry-run", action="store_true", dest="dry_run",
                           help="Print the resolved render plan (mode/locale/backend/voices) and exit 0 without calling the server.")

    p_health = sub.add_parser("health", help="Check server is reachable and show backend status.")
    p_health.add_argument("--url",   default=None, help="Server base URL (default: $PODCAST_URL)")
    p_health.add_argument("--token", default=None, help="Bearer token (default: $PODCAST_TOKEN)")

    p_trans = sub.add_parser("transcribe", help="Transcribe an MP3 and optionally score against a script.")
    p_trans.add_argument("--url",    default=None, help="Server base URL (default: $PODCAST_URL)")
    p_trans.add_argument("--token",  default=None, help="Bearer token (default: $PODCAST_TOKEN)")
    p_trans.add_argument("--mp3",    required=True, help="Path to the MP3 to transcribe")
    p_trans.add_argument("--script", default=None,  help="(Optional) path to script.json for alignment")
    p_trans.add_argument("--out",    required=True, help="Output JSON path")

    return parser


def _resolve_env(args: argparse.Namespace) -> None:
    """Fill url/token from env vars when not passed as flags."""
    args.url   = args.url   or os.environ.get("PODCAST_URL", "")
    args.token = args.token or os.environ.get("PODCAST_TOKEN", "")
    # --dry-run never touches the network, so it needs no credentials.
    if getattr(args, "dry_run", False):
        return
    missing = []
    if not args.url:
        missing.append("--url   (or export PODCAST_URL)")
    if not args.token:
        missing.append("--token (or export PODCAST_TOKEN)")
    if missing:
        sys.exit(
            "ERROR: missing credentials:\n  "
            + "\n  ".join(missing)
            + "\nPass the flag, or: set -a; source .env; set +a"
        )


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    _resolve_env(args)

    try:
        if args.command == "render":
            script_path = Path(args.script)
            if not script_path.exists():
                raise FileNotFoundError(f"Script file not found: {script_path}")
            script_dict = json.loads(script_path.read_text(encoding="utf-8"))

            plan = _plan_render(args, script_dict)

            if args.dry_run:
                print(json.dumps(plan, indent=2, ensure_ascii=False))
                return

            if plan["mode"] == "single":
                render(
                    args.url, args.token, args.script, args.out,
                    backend=plan["backend"],
                    voice=plan["voice"],
                    voice_name=plan["voice_name"],
                    backend_opts=plan["backend_opts"],
                )
            else:
                _rd = _import_render_dialogue()
                _rd.render_dialogue_to_mp3(
                    args.url, args.token, script_dict, args.out,
                    plan["backend"], plan["voices"],
                )

        elif args.command == "health":
            import json as _json
            status = health(args.url, args.token)
            print(_json.dumps(status, indent=2))

        elif args.command == "transcribe":
            transcribe(
                args.url, args.token, args.mp3, args.out,
                script=args.script,
            )

    except (PodcastClientError, FileNotFoundError) as exc:
        sys.exit(f"ERROR: {exc}")


if __name__ == "__main__":
    # Dialogue rendering lazily does `from render_dialogue import ...`, which
    # itself does `from call_remote import ...`. Run as a script, this module
    # is loaded as "__main__", not "call_remote" — without this alias, that
    # inner import would load a *second* copy of this file, producing a
    # PodcastClientError class distinct from the one used in the try/except
    # below (so dialogue errors here would go uncaught).
    sys.modules.setdefault("call_remote", sys.modules["__main__"])
    main()
