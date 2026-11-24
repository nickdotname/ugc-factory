"""Lyric sync: the measurement (studio/sync_check.py), the gate lyric styles pass, and the songs themselves."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pytest

STUDIO = Path(__file__).resolve().parent.parent / "studio"
sys.path.insert(0, str(STUDIO))
sf = pytest.importorskip("soundfile")
pytest.importorskip("librosa")
import sync_check as S  # noqa: E402

SR = 22050


def _song(tmp: Path, onsets: list[float], dur: float, words: list[list[float]], secs=None) -> Path:
    """A song folder whose vocal stem is a sung-like burst at every onset, and whose lines put words at `words` (shown
    times, so LEAD early, as force_align.py writes them)."""
    rng = np.random.default_rng(0)
    y = np.zeros(int(dur * SR), np.float32); t = np.arange(int(0.16 * SR)) / SR
    for k, o in enumerate(onsets):
        f0 = 180 + 60 * (k % 5)
        burst = sum(np.sin(2 * np.pi * f0 * h * t) / h for h in range(1, 6)) * np.minimum(1, t / 0.008) * np.exp(-t * 6)
        a = int(o * SR); y[a:a + len(burst)] += 0.3 * burst.astype(np.float32)
    y += 0.0005 * rng.standard_normal(len(y)).astype(np.float32)
    (tmp / "stems").mkdir(parents=True, exist_ok=True)
    sf.write(tmp / "stems" / "Vocals.ogg", y, SR)
    lines = [[round(ws[-1] + 0.3, 2), [["w%d" % i, round(x, 3)] for i, x in enumerate(ws)]] for ws in words]
    (tmp / "lines.json").write_text(json.dumps(lines))
    secs = secs or [dict(id="s01", start=0, end=dur, lines=[0, len(words) - 1], confidence=1.0)]
    (tmp / "song.json").write_text(json.dumps(dict(slug=tmp.name, sections=secs, line_conf=[1.0] * len(words))))
    S._CACHE.clear(); S._REP.clear()
    return tmp


def _onsets(n=60, start=1.0):
    rng = np.random.default_rng(1); t, out = start, []
    for _ in range(n):
        out.append(round(t, 3)); t += rng.uniform(0.2, 0.32)
    return out


def _lines(times, per=6):
    return [list(times[i:i + per]) for i in range(0, len(times), per)]


def test_words_on_their_onsets_pass(tmp_path):
    on = _onsets()
    d = _song(tmp_path / "good", on, on[-1] + 2, _lines([o - S.LEAD for o in on]))
    r = S.report(str(d))
    sec = r["sections"][0]
    assert sec["med"] <= 0.02 and sec["silent"] == 0 and abs(r["song"]["lag"]) <= 0.02
    assert sec["ok"] and S.sections_ok(str(d)) == {"s01": True}
    assert S.trusted_lines(str(d)) == set(range(len(r["lines"])))


def test_a_whole_song_late_is_seen_as_a_lag_and_fails(tmp_path):
    on = _onsets()
    d = _song(tmp_path / "late", on, on[-1] + 2, _lines([o - S.LEAD + 0.12 for o in on]))   # every word 120 ms late
    r = S.report(str(d))
    assert abs(r["song"]["lag"] + 0.12) <= 0.02            # the best shift puts it back: a systematic offset, found
    assert not r["sections"][0]["ok"]


def test_guessed_evenly_spaced_words_fail(tmp_path):
    on = _onsets()
    even = list(np.linspace(on[0], on[-1], len(on)) - S.LEAD)    # what a placeholder spread looks like
    d = _song(tmp_path / "even", on, on[-1] + 2, _lines(even))
    sec = S.report(str(d))["sections"][0]
    assert not sec["ok"] and sec["contrast"] < S.MIN_CONTRAST + 0.3


def test_words_on_silence_fail_and_are_counted(tmp_path):
    on = _onsets(40)
    words = [o - S.LEAD for o in on] + [on[-1] + 2 + 0.25 * k for k in range(12)]     # 12 words after the singing stops
    d = _song(tmp_path / "silent", on, on[-1] + 6, _lines(words))
    sec = S.report(str(d))["sections"][0]
    assert sec["silent"] >= 0.2 and not sec["ok"]


def test_untrusted_lines_come_whole_and_words_past_the_stem_are_dropped(tmp_path):
    on = _onsets(36)
    words = [o - S.LEAD for o in on[:30]] + [o - S.LEAD + 0.15 for o in on[30:]]       # the last line is off
    d = _song(tmp_path / "mixed", on, on[-1] + 1, _lines(words))
    raw = json.loads((d / "lines.json").read_text())
    raw.append([on[-1] + 9, [["past", on[-1] + 5], ["end", on[-1] + 6]]])             # beyond the vocal stem
    (d / "lines.json").write_text(json.dumps(raw)); S._REP.clear()
    L = S.load_lines(str(d))
    assert len(L) == 6                                                                # the line past the stem is gone
    assert len({t for _, t in L[-1][1]}) == 1                                         # the off line shows whole
    assert len({t for _, t in L[0][1]}) == 6                                          # a good line keeps its words


def test_a_failing_section_carries_no_trusted_lines(tmp_path):
    on = _onsets()
    secs = [dict(id="s01", start=0, end=8, lines=[0, 4], confidence=1.0), dict(id="s02", start=8, end=20, lines=[5, 9], confidence=1.0)]
    words = [o - S.LEAD for o in on[:30]] + [o - S.LEAD + 0.15 for o in on[30:]]       # the second section is 150 ms late
    d = _song(tmp_path / "half", on, on[-1] + 2, _lines(words), secs)
    assert S.sections_ok(str(d)) == {"s01": True, "s02": False}
    assert S.trusted_lines(str(d)) <= set(range(5))


# ---- the real songs ------------------------------------------------------------------------------------------------

SONGS = STUDIO / "songs"
SUNG = sorted(p.name for p in SONGS.iterdir() if (p / "lines.json").exists() and json.loads((p / "lines.json").read_text()))


@pytest.mark.parametrize("slug", SUNG)
def test_no_song_is_early_or_late_as_a_whole(slug):
    """A stem/master offset or an intro trimmed from one file shows as every word off by the same amount."""
    r = S.report(str(SONGS / slug))
    assert r["song"]["lag"] is not None and abs(r["song"]["lag"]) <= 0.03, r["song"]
    assert abs(r["song"]["signed"]) <= 0.02, r["song"]


@pytest.mark.parametrize("slug", SUNG)
def test_every_word_is_inside_the_vocal_stem(slug):
    import soundfile
    d = SONGS / slug; info = soundfile.info(str(S._stem(str(d), "Vocals")))
    last = max(t for _, _, t in S.words(str(d)))
    assert last < info.frames / info.samplerate, "words after the vocal stem ends: their times were never heard"


@pytest.mark.parametrize("slug", SUNG)
def test_sections_lyric_styles_use_are_in_sync(slug):
    """What nightly lets a lyric style use (confidence floor and the sync gate) measures as on time."""
    import yaml
    floor = yaml.safe_load((STUDIO / "nightly.yaml").read_text()).get("min_confidence", 0.45)
    r = S.report(str(SONGS / slug))
    for s in r["sections"]:
        if (s["confidence"] or 0) >= floor and s["ok"]:
            assert s["med"] <= S.MAX_MED and s["silent"] <= S.MAX_SILENT and s["contrast"] >= S.MIN_CONTRAST


def test_stems_line_up_with_the_master():
    for slug in ("talk", "notta-problem"):
        lag = S.stem_lag(str(SONGS / slug))
        assert lag is not None and abs(lag) <= 0.01, (slug, lag)
