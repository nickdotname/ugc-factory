# Playbook: narration (the voice on @what.if.town)

Back to [[README]] · see [[styles]], [[accounts]], [[learning]], [[traps]].

Only one account speaks: **@what.if.town** (`lowpoly_stories`, `studio/lowpoly_video.py`). The notes pages stay silent
text over the song. The voice is `studio/voice.py`; the renderer calls it, the publisher appends the disclosure.

## How it works
1. **Speech.** Kokoro-82M (Apache 2.0, runs on the CPU, no key) reads the story through `voice.speak(text, voice=
   voice.VOICES['lowpoly_stories'])` → `(wav, seconds, [(word, start, end)])`, 24 kHz mono. One fixed voice per
   account (`VOICES`, `af_heart`), so the page sounds like itself. Kokoro 0.9 stamps every token with start/end
   (the renderer lands caption chunks on the spoken words); an older build gets a per-character guess.
2. **The mix.** `voice.mix(song_clip, [(wav, offset_s, seconds), ...], out_m4a, stems=voice.stems_of(song_dir),
   t0=t0 - stems_start_sec)` is one ffmpeg run: each voice clip at its offset, levelled to about -16 LUFS; the song
   ducked 12 dB (`duck_db`) under every spoken range by a volume envelope (120 ms dive, 400 ms return: the ranges are
   known exactly, so nothing is left to a sidechain detector to guess); and, when `stems/` has Drums, Bass and Other,
   the master crossfades to the band without the singer for the padded speech ranges (`MUTE_PAD` 0.15 s, ranges
   closer than 0.6 s stay joined), so two voices never overlap, and the full mix comes back for the last shots.
   `mute=[(a, b), ...]` lets the renderer widen the mute to a whole shot. The repo's stems are the small mono 22 kHz
   copies, so under the speech the band is mono; at -12 dB it does not show. Full `.flac` stems are used first when
   they are on disk.
3. **Fallback.** Anything that stops speech (kokoro missing, model not cached and huggingface.co unreachable, a voice
   file that never downloaded) raises `voice.VoiceUnavailable`. The renderer catches it and renders the silent video
   with `voice=off` recorded; the nightly job never fails for a voice.
4. **Disclosure.** `voice.disclosure()` → `voice: ai narration`. Meta asks realistic AI-made voice to be labelled, so
   the publisher appends that line to the caption of every narrated post (the clip's record says `voice: on`).
   Statement, not an ask: it is not engagement bait.

## The knob
`voice: on | off` in the low-poly renderer (`Video.plan_spoken` / `plan_beats`), picked through `K.pick('voice',
['on', 'off'], r, weights=[3, 1])` like every other knob, so the learner measures whether a spoken story keeps people
longer than silent words on the beat. Force it for a night with `set=voice=on` (or `off`) on `studio.yml`. When the
voice is unavailable (or the mix fails) the clip is recorded as `off` whatever was picked, so the numbers stay honest.

With the voice on: one `speak()` per shot; a shot starts on the first beat after the previous narration ends (+0.3 s),
lasts at least as long as its words, and each caption chunk appears as its first word is spoken (the "what if" chunk
from frame 0, for the cover). A story longer than the clip is read again up to 1.3x faster; shots that still do not
fit are left out whole (the log says `voice: 4 of 5 shots fit`), never cut mid-sentence. The posting core
(`src/cli.py` `_voiced_clips` / `_disclosed`) appends the label to every caption of a clip whose recipe says `voice: on`.

## Where the model lives
`~/.cache/huggingface/hub/models--hexgrad--Kokoro-82M` (about 330 MB plus `voices/af_heart.pt`). `studio.yml`
installs torch (CPU wheel) and `kokoro>=0.9` only on nights `studio/nightly.yaml` has a `style: lowpoly` target,
caches that folder with `actions/cache` keyed `kokoro-model-<kokoro version>-af_heart`, and runs `voice.warm()` so a
cache miss downloads once per version. Kokoro needs Python < 3.13 (the job runs 3.11) and `espeak-ng` (its fallback
G2P, on the apt line).

## Testing
- **Unit tests** run anywhere: `python -W ignore -m pytest -q -p no:warnings tests/test_voice.py` (a fake pipeline, no
  download; two real ffmpeg mixes on synthetic tones check the duck depth and the singer swap).
- **The model itself only in Actions.** Cloud sessions cannot reach huggingface.co and run Python 3.13, so the real
  voice is never heard locally. Run `studio.yml` with `campaign=lowpoly_stories`, `count=1`, `set=voice=on`; the log
  shows `narrator ready` after the warm step and the renderer's `done` line with `voice: on`. Pull the clip from the
  library release (`gh release download assets-lowpoly_stories-<song>`), listen: the words should sit on the voice,
  the song should drop under it and come back clean, the singer should not be heard while the narrator speaks.
- If the warm step warns (`model could not be fetched`), that night's stories are silent, not missing: look at the
  Actions log for the huggingface error, re-run the workflow later; nothing to fix in the repo.
- A new Kokoro voice: change `VOICES['lowpoly_stories']` and the cache key suffix in `studio.yml`; one voice per
  account, never a menu (the page must stay recognisable).
