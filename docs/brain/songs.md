# Songs

Back to [[README]]. EDUCATION by Close Quarters, 15 tracks. Each prepared song is a folder in `studio/songs/<slug>/`:
`master.ogg`, `stems/{Vocals,Drums,Bass,Other}.ogg` (mono 22.05 kHz), `lines.json` (every sung word with its time),
`song.json` (title, track, tempo, `beat_times`, `sections`), and for physics `project_hits.json`. A song becomes a
**creative** named after its slug with `-` → `_` (`silver-and-gold` → `silver_and_gold`) in each campaign's config.

| # | title | slug | in rotation |
|---|---|---|---|
| 1 | Prologue: Before | prologue | all |
| 2 | Hair of the Dog | hair-of-the-dog | all |
| 3 | Myth of Sisyphus | myth-of-sisyphus | all |
| 4 | Recess (Rewind) | recess-rewind | picture accounts only (instrumental) |
| 5 | Fixation | fixation | all |
| 6 | Subway Maintenance | subway-maintenance | all |
| 7 | Talk | talk | all |
| 8 | Full Ride | full-ride | all |
| 9 | Passage (Waiting) | passage-waiting | picture accounts only (instrumental) |
| 10 | Suspended | suspended | all |
| 11 | Evil Close Quarters | evil-close-quarters | all |
| 12 | Notta Problem | notta-problem | all |
| 13 | Won't Be the Same Again | wont-be-the-same-again | all |
| 14 | Silver and Gold | silver-and-gold | all |
| 15 | Epilogue: Dismissal | epilogue-dismissal | picture accounts only (instrumental) |

(4, 9, 15 arrive with PR #92.) Physics needs `project_hits.json` from the Ableton project, so only songs with one
appear there.

## Preparing a song: see [[add-song]]

- With vocals: `studio/prep_song.py` (vocal/instrumental split, Whisper word timing, sections from sung lines),
  then `studio/force_align.py` (wav2vec2 forced alignment, better timing), then `studio/beatmap.py` (the real
  beat grid from the drums), then convert to ogg.
- Instrumental: `studio/prep_instrumental.py` does all of it: sections are whole bars laid over the loud part,
  confidence 0, so lyric styles never use them.

Sections are 14–24 s stretches; nightly glues neighbours up to a style's `join` seconds, and may tighten a stretch
to its strongest line (10–20 s) or a 6–9 s loop for picture styles.

Source audio (masters, vocal/instrumental splits, lyrics text) is kept outside the repo by Dylan.
