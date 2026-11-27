#!/usr/bin/env python3
"""Narration for @what.if.town: Kokoro-82M reads the story, ffmpeg lays it over the song.

    path, dur, words = speak("what if every door in town opened at once", voice=VOICES['lowpoly_stories'])
    mix(song_clip_m4a, [(path, 2.4)], out_m4a, stems=stems_of(song_dir), t0=t0 - stems_start)

One fixed voice per account (VOICES), so the page sounds like itself. speak() returns the wav (24 kHz mono),
its length and the word timings the pipeline knows (Kokoro 0.9 puts start/end on every token; older builds get
a per-character guess), so the renderer can land its caption chunks on the spoken words. mix() is one ffmpeg
run: the voice clips at their offsets, levelled to about -16 LUFS, the song ducked by duck_db under each one
(a volume envelope with a 120 ms dive and a 400 ms return: the spoken ranges are known exactly, so there is
nothing for a sidechain detector to guess), and, when the song's stems are there, the song's own singer
muted around the speech (the master crossfades to Drums + Bass + Other, then back), so two voices never talk
over each other and the full mix is back for the last shots. disclosure() is the caption line Meta's
labelling rule asks for on a realistic AI voice.

The model (about 330 MB) lives under ~/.cache/huggingface; the studio job caches that folder. Anything that
stops speech (kokoro not installed, model not cached and huggingface.co unreachable, the pipeline failing) is
raised as VoiceUnavailable so a renderer falls back to a silent video: the nightly job must not die for a voice.
Cloud sessions cannot reach huggingface.co, so this is tested for real only in Actions (docs/brain/playbooks/narration.md).
"""
import os, re, subprocess, tempfile

SR = 24000                                       # Kokoro's rate
REPO_ID = 'hexgrad/Kokoro-82M'
VOICES = {'lowpoly_stories': 'af_heart'}         # one voice per account; the page should be recognisable
DISCLOSURE = 'voice: ai narration'
VOICE_LUFS = -16.0
RAMP_UP, RAMP_DOWN = 0.12, 0.4                   # the music gets out of the way fast, comes back slowly
MUTE_PAD, MUTE_GAP = 0.15, 0.6                   # the singer is muted this far around each spoken range; ranges this close are one
STEM_NAMES = ('Drums', 'Bass', 'Other')          # everything but the singer


class VoiceUnavailable(RuntimeError):
    """No narration possible on this host: render without a voice."""


# ---- speech ---------------------------------------------------------------------------------------------------
_PIPE = {}


def pipeline(lang='a'):
    """The Kokoro pipeline for a language (a = American English), made once. VoiceUnavailable when it cannot be."""
    if lang in _PIPE: return _PIPE[lang]
    try: from kokoro import KPipeline
    except Exception as exc: raise VoiceUnavailable('kokoro is not installed: %s' % exc)
    try: _PIPE[lang] = KPipeline(lang_code=lang, repo_id=REPO_ID)
    except Exception as exc: raise VoiceUnavailable('kokoro model not available: %s' % exc)  # not cached, host unreachable
    return _PIPE[lang]


def proportional(text, dur):
    """Word timings when the pipeline gives none: each word's share of the characters (the space after it included)."""
    words = text.split()
    if not words or dur <= 0: return []
    total = sum(len(w) for w in words) + len(words) - 1
    out, at = [], 0.0
    for w in words:
        out.append((w, round(at, 3), round(at + dur * len(w) / total, 3))); at += dur * (len(w) + 1) / total
    return out


def word_times(result, dur):
    """(word, start, end) for one pipeline chunk, from its tokens' timestamps when they have them."""
    tokens = getattr(result, 'tokens', None) or []
    out = []
    for t in tokens:
        text = (getattr(t, 'text', '') or '').strip()
        if not re.search(r'\w', text): continue                         # punctuation is not a word
        s, e = getattr(t, 'start_ts', None), getattr(t, 'end_ts', None)
        if s is None or e is None: return proportional(getattr(result, 'graphemes', '') or '', dur)
        out.append((text, round(float(s), 3), round(float(e), 3)))
    return out or proportional(getattr(result, 'graphemes', '') or '', dur)


def speak(text, voice='af_heart', speed=1.0, out_wav=None, tail=0.25):
    """Read text aloud -> (wav path, seconds, [(word, start, end)]). Chunks (one per line) are joined back to back."""
    import numpy as np, soundfile as sf
    pipe = pipeline()
    try: results = list(pipe(text, voice=voice, speed=speed))
    except Exception as exc: raise VoiceUnavailable('kokoro could not speak: %s' % exc)   # a voice file that never downloaded, usually
    parts, words, at = [], [], 0.0
    for r in results:
        a = r.audio if hasattr(r, 'audio') else r[2]
        if a is None: continue
        a = np.asarray(a.numpy() if hasattr(a, 'numpy') else a, dtype='float32').reshape(-1)
        dur = len(a) / SR
        words += [(w, round(at + s, 3), round(at + e, 3)) for w, s, e in word_times(r, dur)]
        parts.append(a); at += dur
    if not parts: raise VoiceUnavailable('kokoro produced no audio for %r' % text[:40])
    y = np.concatenate(parts)
    keep = np.nonzero(np.abs(y) > 0.003)[0]                              # Kokoro leaves a long silence after the last word
    if len(keep): y = y[:min(len(y), keep[-1] + int(tail * SR))]
    y = np.clip(y, -1, 1)
    if not out_wav: fd, out_wav = tempfile.mkstemp(prefix='voice-', suffix='.wav'); os.close(fd)
    sf.write(out_wav, y, SR, subtype='PCM_16')
    return out_wav, round(len(y) / SR, 3), words


def warm(voice='af_heart'):
    """Download the model and a voice into the cache (the studio job runs this once so the cache step has something to keep)."""
    pipe = pipeline()
    try: pipe.load_voice(voice)
    except Exception as exc: raise VoiceUnavailable('voice %s not available: %s' % (voice, exc))
    return pipe


# ---- the mix ----------------------------------------------------------------------------------------------------
def ranges(spoken, pad=MUTE_PAD, gap=MUTE_GAP, end=None):
    """Spoken (start, end) pairs -> padded, merged, in order, clipped to [0, end]. Where the singer is muted."""
    out = []
    for a, b in sorted((float(a), float(b)) for a, b in spoken):
        a, b = max(0.0, a - pad), b + pad
        if end is not None: b = min(b, end)
        if b <= a: continue
        if out and a - out[-1][1] <= gap: out[-1][1] = max(out[-1][1], b)
        else: out.append([a, b])
    return [(round(a, 3), round(b, 3)) for a, b in out]


def envelope(rs, up=RAMP_UP, down=RAMP_DOWN):
    """An ffmpeg expression in t: 1 inside each range, 0 outside, ramping in over `up` s before and out over `down` s after."""
    if not rs: return '0'
    terms = ['clip(min((t-%.3f)/%.3f,(%.3f-t)/%.3f),0,1)' % (a - up, up, b + down, down) for a, b in rs]
    e = terms[0]
    for t in terms[1:]: e = 'max(%s,%s)' % (e, t)
    return e


def mix_cmd(song, voices, out, duck_db=-12.0, stems=None, t0=0.0, mute=None, duck=None):
    """The ffmpeg argv for mix(). voices: [(wav, offset_s, duration_s)]. mute/duck: (start, end) ranges in clip time."""
    fmt = 'aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo'
    spoken = [(off, off + dur) for _p, off, dur in voices]
    duck = ranges(spoken, pad=0.0, gap=0.3) if duck is None else duck
    mute = ranges(spoken) if mute is None else mute
    depth = 1 - 10 ** (float(duck_db) / 20)                            # share of the music taken away under the voice
    dk = '(1-%.3f*%s)' % (depth, envelope(duck))                        # 1 clear, 10^(duck_db/20) under speech
    args = ['ffmpeg', '-loglevel', 'error', '-y', '-i', song]
    graph = []
    for i, (wav, off, _d) in enumerate(voices):
        args += ['-i', wav]
        graph.append('[%d:a]loudnorm=I=%.0f:TP=-1.5:LRA=11:dual_mono=true,%s,adelay=%d:all=1[v%d]' % (i + 1, VOICE_LUFS, fmt, round(off * 1000), i))
    graph.append(''.join('[v%d]' % i for i in range(len(voices))) + ('amix=inputs=%d:normalize=0' % len(voices) if len(voices) > 1 else 'anull') + '[voice]')
    stems = dict(stems or {})
    if all(n in stems for n in STEM_NAMES) and mute:
        k = len(voices) + 1
        for n in STEM_NAMES: args += ['-ss', '%.3f' % max(0.0, t0), '-i', stems[n]]
        mt = envelope(mute)
        graph.append('[0:a]%s,asetnsamples=n=256,volume=\'(1-%s)*%s\':eval=frame[song]' % (fmt, mt, dk))
        graph.append(''.join('[%d:a]' % (k + j) for j in range(len(STEM_NAMES))) + 'amix=inputs=%d:normalize=0,%s,asetnsamples=n=256,volume=\'%s*%s\':eval=frame[inst]' % (len(STEM_NAMES), fmt, mt, dk))
        graph.append('[song][inst]amix=inputs=2:normalize=0:duration=first[bed]')
    else:
        graph.append('[0:a]%s,asetnsamples=n=256,volume=\'%s\':eval=frame[bed]' % (fmt, dk))
    graph.append('[bed][voice]amix=inputs=2:normalize=0:duration=first[out]')
    return args + ['-filter_complex', ';'.join(graph), '-map', '[out]', '-c:a', 'aac', '-b:a', '192k', out]


def mix(song, voices, out, duck_db=-12.0, stems=None, t0=0.0, mute=None):
    """Song clip + voice clips -> out (.m4a). voices: [(wav, offset_s[, duration_s])], offsets in seconds into the clip.
    stems: {'Drums': path, 'Bass': path, 'Other': path} (stems_of) and t0 where the clip starts in them, to mute the
    singer under the speech; mute: those ranges, when the renderer wants them wider (default: the speech, padded)."""
    import soundfile as sf
    vs = [(v[0], float(v[1]), float(v[2]) if len(v) > 2 else sf.info(v[0]).duration) for v in voices]
    r = subprocess.run(mix_cmd(song, vs, out, duck_db, stems, t0, mute), capture_output=True, text=True)
    if r.returncode or not os.path.exists(out): raise RuntimeError('voice mix failed: %s' % r.stderr.strip()[-400:])
    return out


def stems_of(song_dir):
    """The song's Drums/Bass/Other stems (flac first, then the small ogg copies) or None when one is missing."""
    out = {}
    for n in STEM_NAMES:
        p = next((os.path.join(song_dir, 'stems', n + e) for e in ('.flac', '.wav', '.ogg') if os.path.exists(os.path.join(song_dir, 'stems', n + e))), None)
        if not p: return None
        out[n] = p
    return out


def disclosure():
    """The caption line the publisher appends to a narrated post (Meta: label realistic AI-made voice)."""
    return DISCLOSURE


if __name__ == '__main__':
    import sys
    text = ' '.join(sys.argv[1:]) or 'what if every door in town opened at once.'
    p, d, w = speak(text, out_wav='/tmp/voice.wav'); print(p, d, w)
