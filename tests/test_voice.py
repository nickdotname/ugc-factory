"""studio/voice.py without the model: a fake Kokoro pipeline (no download), the timing fallback, the ffmpeg filter
graph, the mute ranges, the disclosure line, and one real ffmpeg mix on synthetic audio when ffmpeg is installed."""
import os, subprocess, sys, types

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'studio'))
import voice as V

from tests.conftest import needs_ffmpeg


class Tok:
    def __init__(self, text, s=None, e=None): self.text, self.start_ts, self.end_ts = text, s, e


class Result:
    def __init__(self, graphemes, audio, tokens=None): self.graphemes, self.audio, self.tokens = graphemes, audio, tokens


class Tensor:                                   # stands in for torch's: speak() must accept .numpy()
    def __init__(self, a): self.a = a
    def numpy(self): return self.a


def fake_pipe(results, calls=None):
    def pipe(text, voice, speed):
        if calls is not None: calls.append((text, voice, speed))
        yield from results
    return pipe


def tone(sec, sr=V.SR, amp=0.3):
    return (amp * np.sin(np.linspace(0, 2 * np.pi * 220 * sec, int(sr * sec), endpoint=False))).astype('float32')


# ---- speak ------------------------------------------------------------------------------------------------------
def test_speak_uses_token_timestamps_and_joins_chunks(monkeypatch, tmp_path):
    calls = []
    r1 = Result('what if.', Tensor(tone(1.0)), [Tok('what', 0.1, 0.4), Tok('if', 0.45, 0.7), Tok('.', 0.7, 0.75)])
    r2 = Result('nobody left', tone(0.5), [Tok('nobody', 0.05, 0.3), Tok('left', 0.3, 0.45)])
    monkeypatch.setattr(V, 'pipeline', lambda lang='a': fake_pipe([r1, r2], calls))
    out = str(tmp_path / 'v.wav')
    path, dur, words = V.speak('what if.\nnobody left', voice='af_heart', speed=1.1, out_wav=out)
    assert path == out and os.path.exists(out)
    assert calls == [('what if.\nnobody left', 'af_heart', 1.1)]
    assert words == [('what', 0.1, 0.4), ('if', 0.45, 0.7), ('nobody', 1.05, 1.3), ('left', 1.3, 1.45)]   # second chunk shifted; '.' dropped
    assert 1.4 <= dur <= 1.5                                                                           # 1.5 s of sound, trailing tail kept
    import soundfile as sf
    info = sf.info(out); assert info.samplerate == V.SR and info.channels == 1


def test_speak_trims_the_silence_kokoro_leaves_after_the_last_word(monkeypatch, tmp_path):
    a = np.concatenate([tone(0.5), np.zeros(V.SR * 2, 'float32')])
    monkeypatch.setattr(V, 'pipeline', lambda lang='a': fake_pipe([Result('hi', a, [Tok('hi', 0.0, 0.5)])]))
    _p, dur, _w = V.speak('hi', out_wav=str(tmp_path / 'v.wav'))
    assert 0.5 <= dur <= 0.8


def test_speak_falls_back_to_proportional_timing(monkeypatch, tmp_path):
    # tokens without timestamps (older kokoro) and no tokens at all (a quiet result) both get the character guess
    for toks in ([Tok('what'), Tok('if'), Tok('every'), Tok('door')], None):
        monkeypatch.setattr(V, 'pipeline', lambda lang='a', toks=toks: fake_pipe([Result('what if every door', tone(2.0), toks)]))
        _p, dur, words = V.speak('what if every door', out_wav=str(tmp_path / 'v.wav'))
        assert [w for w, _s, _e in words] == ['what', 'if', 'every', 'door']
        assert words[0][1] == 0.0 and abs(words[-1][2] - dur) < 0.3
        assert all(s < e for _w, s, e in words) and all(a[2] <= b[1] for a, b in zip(words, words[1:]))


def test_proportional_shares_by_characters():
    w = V.proportional('aa bbbb', 1.0)                 # 7 characters incl. the space: 2/7 then 4/7 from 3/7
    assert w == [('aa', 0.0, round(2 / 7, 3)), ('bbbb', round(3 / 7, 3), 1.0)]
    assert V.proportional('', 1.0) == [] and V.proportional('x', 0) == []


def test_speak_without_kokoro_raises_voice_unavailable(monkeypatch):
    V._PIPE.clear()
    monkeypatch.setitem(sys.modules, 'kokoro', None)             # import kokoro -> ImportError
    with pytest.raises(V.VoiceUnavailable): V.speak('hello')


def test_pipeline_failure_is_voice_unavailable(monkeypatch):
    V._PIPE.clear()
    mod = types.ModuleType('kokoro')
    def KPipeline(lang_code, repo_id): raise OSError('huggingface.co unreachable and nothing cached')
    mod.KPipeline = KPipeline
    monkeypatch.setitem(sys.modules, 'kokoro', mod)
    with pytest.raises(V.VoiceUnavailable, match='not available'): V.pipeline()
    assert 'a' not in V._PIPE
    # the pipeline exists but speaking fails (a voice file that never downloaded): still a fallback, not a crash
    def boom(text, voice, speed): raise RuntimeError('no such voice'); yield
    monkeypatch.setattr(V, 'pipeline', lambda lang='a': boom)
    with pytest.raises(V.VoiceUnavailable, match='could not speak'): V.speak('hello')


def test_one_voice_per_account():
    assert V.VOICES['lowpoly_stories'] == 'af_heart'


# ---- ranges and envelopes ---------------------------------------------------------------------------------------
def test_mute_ranges_pad_merge_and_clip():
    assert V.ranges([(1.0, 2.0)]) == [(0.85, 2.15)]
    assert V.ranges([(0.05, 1.0)]) == [(0.0, 1.15)]                                 # never before the clip starts
    assert V.ranges([(3.0, 4.0), (1.0, 2.0)]) == [(0.85, 2.15), (2.85, 4.15)]      # sorted, two ranges: the gap is wider than MUTE_GAP
    assert V.ranges([(1.0, 2.0), (2.5, 3.0)]) == [(0.85, 3.15)]                    # close ranges are one: the singer does not flicker back
    assert V.ranges([(1.0, 2.0), (1.5, 1.8)]) == [(0.85, 2.15)]                    # nested
    assert V.ranges([(1.0, 2.0), (9.0, 12.0)], end=10.0) == [(0.85, 2.15), (8.85, 10.0)]
    assert V.ranges([(9.9, 12.0)], end=10.0, pad=0.0) == [(9.9, 10.0)] and V.ranges([(11, 12)], end=10.0) == []
    assert V.ranges([]) == []


def test_envelope_expression():
    assert V.envelope([]) == '0'
    e = V.envelope([(1.0, 2.0)])
    assert e == 'clip(min((t-0.880)/0.120,(2.400-t)/0.400),0,1)'                  # ramps in before, out after
    e2 = V.envelope([(1.0, 2.0), (5.0, 6.0)])
    assert e2.startswith('max(') and e2.count('clip(') == 2
    for ch in e2: assert ch in '0123456789.()-/,tmaxclipn' or ch in 'maxclipn'    # nothing that needs quoting in a filter graph


def test_envelope_values(tmp_path):
    """The expression really is a trapezoid: evaluate it the way ffmpeg would at a few times."""
    e = V.envelope([(1.0, 2.0)]).replace('clip(', 'np.clip(').replace('min(', 'np.minimum(')
    f = lambda t: float(eval(e, {'np': np, 't': t}))
    near = lambda a, b: abs(a - b) < 1e-6
    assert near(f(0.5), 0) and near(f(0.88), 0) and near(f(0.94), 0.5) and near(f(1.0), 1) and near(f(1.5), 1) and near(f(2.0), 1)
    assert near(f(2.2), 0.5) and near(f(2.4), 0) and near(f(3), 0)


# ---- the ffmpeg command ---------------------------------------------------------------------------------------
def test_mix_cmd_without_stems():
    cmd = V.mix_cmd('song.m4a', [('a.wav', 1.0, 0.8)], 'out.m4a')
    assert cmd[:4] == ['ffmpeg', '-loglevel', 'error', '-y'] and cmd[-1] == 'out.m4a'
    assert cmd.count('-i') == 2 and 'song.m4a' in cmd and 'a.wav' in cmd and '-ss' not in cmd
    g = cmd[cmd.index('-filter_complex') + 1]
    assert 'loudnorm=I=-16:TP=-1.5:LRA=11:dual_mono=true' in g and 'adelay=1000:all=1[v0]' in g
    assert '[v0]anull[voice]' in g                                                  # one voice clip: nothing to mix
    assert "volume='(1-0.749*clip(min((t-0.880)/0.120,(2.200-t)/0.400),0,1))':eval=frame[bed]" in g   # -12 dB = x0.251 under the voice, 0.4 s back
    assert '[inst]' not in g and g.endswith('[bed][voice]amix=inputs=2:normalize=0:duration=first[out]')
    assert cmd[cmd.index('-map') + 1] == '[out]' and cmd[cmd.index('-c:a') + 1] == 'aac'


def test_mix_cmd_duck_depth_follows_duck_db():
    graph = lambda cmd: cmd[cmd.index('-filter_complex') + 1]
    assert '1-0.499*' in graph(V.mix_cmd('s', [('a', 0.0, 1.0)], 'o', duck_db=-6))
    assert '1-0.000*' in graph(V.mix_cmd('s', [('a', 0.0, 1.0)], 'o', duck_db=0))


def test_mix_cmd_with_stems_mutes_the_singer_under_the_speech():
    stems = {'Drums': 'd.ogg', 'Bass': 'b.ogg', 'Other': 'o.ogg'}
    cmd = V.mix_cmd('song.m4a', [('a.wav', 1.0, 0.8), ('b.wav', 3.0, 1.0)], 'out.m4a', stems=stems, t0=23.4)
    assert cmd.count('-i') == 6 and cmd.count('-ss') == 3 and cmd[cmd.index('-ss') + 1] == '23.400'
    assert cmd.index('d.ogg') < cmd.index('b.ogg') < cmd.index('o.ogg')
    g = cmd[cmd.index('-filter_complex') + 1]
    assert '[v0][v1]amix=inputs=2:normalize=0[voice]' in g
    mute = V.envelope(V.ranges([(1.0, 1.8), (3.0, 4.0)]))
    duck = V.envelope(V.ranges([(1.0, 1.8), (3.0, 4.0)], pad=0.0, gap=0.3))
    assert "volume='(1-%s)*(1-0.749*%s)':eval=frame[song]" % (mute, duck) in g      # master out while the voice speaks
    assert "[3:a][4:a][5:a]amix=inputs=3:normalize=0" in g
    assert "volume='%s*(1-0.749*%s)':eval=frame[inst]" % (mute, duck) in g           # the band without the singer in its place
    assert '[song][inst]amix=inputs=2:normalize=0:duration=first[bed]' in g
    # a renderer may widen the mute to the shot
    cmd2 = V.mix_cmd('song.m4a', [('a.wav', 1.0, 0.8)], 'out.m4a', stems=stems, mute=[(0.0, 5.0)])
    assert V.envelope([(0.0, 5.0)]) in cmd2[cmd2.index('-filter_complex') + 1]


def test_mix_cmd_incomplete_stems_means_no_mute():
    cmd = V.mix_cmd('song.m4a', [('a.wav', 1.0, 0.8)], 'out.m4a', stems={'Drums': 'd.ogg'})
    assert cmd.count('-i') == 2 and '[inst]' not in cmd[cmd.index('-filter_complex') + 1]


def test_stems_of(tmp_path):
    assert V.stems_of(str(tmp_path)) is None
    sd = tmp_path / 'stems'; sd.mkdir()
    for n in ('Drums', 'Bass', 'Other', 'Vocals'): (sd / (n + '.ogg')).write_bytes(b'')
    (sd / 'Drums.flac').write_bytes(b'')
    st = V.stems_of(str(tmp_path))
    assert set(st) == {'Drums', 'Bass', 'Other'} and st['Drums'].endswith('Drums.flac') and st['Bass'].endswith('Bass.ogg')


def test_disclosure():
    assert V.disclosure() == 'voice: ai narration'
    assert V.disclosure().islower() and len(V.disclosure()) < 40


# ---- one real mix ----------------------------------------------------------------------------------------------
def _gen(path, src, *extra):
    subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', src, *extra, path], check=True)


def _wav(path):
    import soundfile as sf
    out = path + '.wav'; subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', path, '-ac', '1', out], check=True)
    y, sr = sf.read(out, dtype='float32'); return y, sr


@needs_ffmpeg
def test_mix_runs_and_ducks_the_song(tmp_path):
    song = str(tmp_path / 'song.m4a'); voice = str(tmp_path / 'v.wav'); out = str(tmp_path / 'out.m4a')
    _gen(song, 'sine=frequency=220:sample_rate=44100:duration=4', '-ac', '2', '-c:a', 'aac')
    _gen(voice, 'sine=frequency=1000:sample_rate=24000:duration=1', '-ac', '1')         # the "voice": 1 kHz, so it can be told apart
    assert V.mix(song, [(voice, 1.5)], out) == out                                       # duration probed from the wav
    y, sr = _wav(out)
    assert abs(len(y) / sr - 4.0) < 0.15
    # the 220 Hz bed is ~12 dB quieter at 2.0 s (under the voice) than at 0.5 s and back by 3.5 s
    def level(t, hz):
        seg = y[int((t - 0.1) * sr):int((t + 0.1) * sr)]; n = len(seg)
        k = int(round(hz * n / sr)); return abs(np.fft.rfft(seg)[k]) / n
    clear, under, back = level(0.5, 220), level(2.0, 220), level(3.5, 220)
    assert 9 < 20 * np.log10(clear / under) < 15, (clear, under)
    assert abs(20 * np.log10(clear / back)) < 1
    assert level(2.0, 1000) > level(0.5, 1000) * 20                                      # and the voice is there, only there


@needs_ffmpeg
def test_mix_with_stems_swaps_the_master_for_the_band(tmp_path):
    song = str(tmp_path / 'song.m4a'); voice = str(tmp_path / 'v.wav'); out = str(tmp_path / 'out.m4a')
    _gen(song, 'sine=frequency=220:sample_rate=44100:duration=4', '-ac', '2', '-c:a', 'aac')     # the "master": the singer at 220 Hz
    _gen(voice, 'sine=frequency=1000:sample_rate=24000:duration=1', '-ac', '1')
    stems = {}
    for n, hz in (('Drums', 440), ('Bass', 55), ('Other', 880)):                           # the band, at 22050 mono like the repo's stems
        stems[n] = str(tmp_path / (n + '.ogg')); _gen(stems[n], 'sine=frequency=%d:sample_rate=22050:duration=6' % hz, '-ac', '1', '-c:a', 'libvorbis')
    V.mix(song, [(voice, 1.5, 1.0)], out, stems=stems, t0=1.0)
    y, sr = _wav(out)
    assert abs(len(y) / sr - 4.0) < 0.15                                                   # the clip's length, not the stems'
    def level(t, hz):
        seg = y[int((t - 0.1) * sr):int((t + 0.1) * sr)]; n = len(seg)
        k = int(round(hz * n / sr)); return abs(np.fft.rfft(seg)[k]) / n
    assert level(0.5, 220) > 20 * level(2.0, 220)                                           # the singer is gone under the speech
    assert level(2.0, 440) > 20 * level(0.5, 440)                                           # the band stands in, ducked
    assert level(3.5, 220) > 20 * level(3.5, 440)                                           # and the master is back after
