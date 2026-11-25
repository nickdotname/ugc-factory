# Playbook: add a song

Back to [[README]] · see [[songs]].

## With vocals
1. Inputs: the master WAV, a vocal/instrumental split (FLAC), the lyrics as plain text (one line per line).
2. `python studio/prep_song.py --master song.wav --lyrics lyrics.txt --out studio/songs/<slug> --title "Title" --track N --vox vox.flac --inst inst.flac`
   (Whisper `small.en` from a local cache: `HF_HUB_OFFLINE=1`).
3. `python studio/force_align.py <slug>` (wav2vec2) for tighter word timing; keep prep's timing if it fails.
4. Convert: `master.wav` → `master.ogg` (libvorbis q5); each stem → mono 22050 Hz ogg (q3). Remove the .flac and
   the master.wav symlink.
5. `python studio/beatmap.py <slug>` (needs `stems/Drums.ogg`): writes the real tempo and `beat_times`.
6. Don't commit `report.txt`, `emissions.npz`, `heard.json`.
7. `python studio/sync_check.py <slug> --lines`: every section a lyric style should use must say PASS, the song's
   `lag` must be 0 (±30 ms) and `stem_ms` 0. Check the stems are the whole song (Subway Maintenance, Silver and Gold,
   Evil Close Quarters and Notta Problem once came with stems cut at 100 s, so nothing after 1:40 could be timed).
   If Whisper stops hearing the vocal partway (force_align.py: "the transcription and the lyrics disagree too
   much"), transcribe the rest from where it stopped and add it to heard.json before re-running.

## Instrumental
`python studio/prep_instrumental.py --master song.wav --out studio/songs/<slug> --title "Title" --track N`
does everything above with sections from the beat grid (confidence 0, so lyric styles never use them).

## Put it in rotation
- Add a creative `name: <slug with _>`, `title`, `assets_release: assets-<campaign>-<name>` to every campaign that
  should use it. Instrumentals: picture campaigns only. Physics also needs `project_hits.json` from the Ableton
  project (`studio/als_hits.py`).
- Check one frame sheet in two styles on the new song before opening the PR.
- The next nightly studio run makes its first videos; render and topup queue them.
- Update [[songs]] and [[log]].
