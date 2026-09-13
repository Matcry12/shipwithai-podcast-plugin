#!/usr/bin/env python3
# test_render_guard.py — the dropped-words guard in render_dialogue.py must
# never accept a too-short turn without retrying slower, and must fail loudly
# when retries run out. Stdlib only, no server: render() and ffprobe are stubbed.
#
#   python3 scripts/test_render_guard.py

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import render_dialogue as rd  # noqa: E402
from call_remote import PodcastClientError  # noqa: E402

LINE = "Ý tưởng cốt lõi gói gọn trong một câu. Đừng bảo Claude code ngay."
FLOOR = len(LINE.split()) * rd.MIN_SEC_PER_WORD


class Guard(unittest.TestCase):
    def setUp(self):
        self.calls: list[dict] = []          # backend_opts per render() call
        self.durations: list[float] = []     # what ffprobe "measures", per call

        def fake_render(url, token, script, out, *, backend, verbose, **kw):
            self.calls.append(dict(kw.get("backend_opts") or {}))
            Path(out).write_bytes(b"mp3")

        rd.render = fake_render
        rd._probe_duration = lambda p: self.durations[len(self.calls) - 1]

    def run_guard(self, backend="omnivoice", opts=None):
        rd.render_turn_guarded(
            "u", "t", Path("/dev/null"), Path("/dev/null"),
            backend=backend, voice_kwargs={"backend_opts": opts} if opts else {},
            line=LINE, turn_no=5, verbose=False,
        )

    def test_long_enough_renders_once(self):
        self.durations = [FLOOR + 0.1]
        self.run_guard()
        self.assertEqual(len(self.calls), 1)

    def test_short_retries_slower_then_accepts(self):
        self.durations = [FLOOR * 0.8, FLOOR * 1.1]
        self.run_guard(opts={"speed": 1.0, "ref_text": "x"})
        self.assertEqual(len(self.calls), 2)
        self.assertAlmostEqual(self.calls[1]["speed"], rd.RETRY_SLOWDOWN)
        self.assertEqual(self.calls[1]["ref_text"], "x")  # other opts survive the retry

    def test_still_short_after_retries_raises_naming_turn_and_words(self):
        self.durations = [FLOOR * 0.8] * (rd.MAX_RETRIES + 1)
        with self.assertRaises(PodcastClientError) as cm:
            self.run_guard()
        self.assertEqual(len(self.calls), rd.MAX_RETRIES + 1)
        self.assertIn("turn 5", str(cm.exception))
        self.assertIn("Đừng bảo Claude code ngay", str(cm.exception))
        # speed compounds: 1 → 0.85 → 0.72
        self.assertAlmostEqual(self.calls[-1]["speed"], rd.RETRY_SLOWDOWN ** rd.MAX_RETRIES, places=2)

    def test_dummy_backend_is_not_measured(self):
        self.durations = [0.0]
        self.run_guard(backend="dummy")
        self.assertEqual(len(self.calls), 1)


class SegmentCache(unittest.TestCase):
    """A turn whose backend, voice and words are unchanged is not rendered again."""

    def test_second_render_only_renders_changed_turns(self):
        import shutil, tempfile
        rendered: list[str] = []

        def fake_render(url, token, script, out, *, backend, verbose, **kw):
            rendered.append(Path(script).read_text())
            Path(out).write_bytes(b"ID3fake")

        rd.render = fake_render
        rd._probe_duration = lambda p: 999.0
        rd.concat_mp3s = lambda segs, out, gap=0.5, fade=True: Path(out).write_bytes(b"ID3out")
        d = Path(tempfile.mkdtemp())
        try:
            voices = {"host": {"backend_opts": {"ref_audio": "a.wav"}}, "cohost": {"backend_opts": {"ref_audio": "b.wav"}}}
            script = {"host_mode": "dialogue", "turns": [
                {"voice": "host", "line": "one"}, {"voice": "cohost", "line": "two"}, {"voice": "host", "line": "three"}]}
            rd.render_dialogue_to_mp3("u", "t", script, d / "ep.mp3", "omnivoice", voices, verbose=False)
            self.assertEqual(len(rendered), 3)
            script["turns"][1]["line"] = "two, patched"
            rd.render_dialogue_to_mp3("u", "t", script, d / "ep.mp3", "omnivoice", voices, verbose=False)
            self.assertEqual(len(rendered), 4)                      # only the patched turn
            self.assertIn("two, patched", rendered[-1])
            # same words, other voice -> different segment
            script["turns"][0]["voice"] = "cohost"
            rd.render_dialogue_to_mp3("u", "t", script, d / "ep.mp3", "omnivoice", voices, verbose=False)
            self.assertEqual(len(rendered), 5)
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
