# inbox — drop your files here

This is the only folder you need to think about.

```
inbox/clubs/
  hooks/     ← hook clips (the first 1–2 seconds that stop the scroll)
  bodies/    ← main videos
  music/     ← tracks
```

Drop files into the folder that matches what they are. **Names don't matter** —
spaces, capitals, `FINAL_v3 (copy).mp4`, anything. The folder is what assigns
the role, and correct names are generated for you on upload.

Then:

```bash
python -m src.cli ingest --campaign clubs
```

That probes every file, tells you what it found, renames them to
`hook_01.mp4` / `body_01.mp4` / `music_01.mp3` (continuing from whatever is
already uploaded, never overwriting), and pushes them to the campaign's assets
Release. Successfully uploaded files move to `_uploaded/` so re-running is safe.

Add `--dry-run` to see the plan without uploading anything.

## What gets rejected

Only things the pipeline genuinely cannot use:

- files ffprobe can't read (corrupt, or not actually video)
- wrong type for the folder — an `.mp3` in `hooks/`, a `.mp4` in `music/`
- clips under 0.5s, tracks under 1s

## What gets a warning but still works

The renderer fixes these, so they are notes rather than errors:

- **landscape or square footage** — centre-cropped to 9:16, so keep your
  subject centred in frame
- **no audio track** — silence is added automatically
- **odd frame rates, non-square pixels** — normalised

## Accepted formats

| folder | extensions |
|---|---|
| `hooks/`, `bodies/` | `.mp4` `.mov` `.m4v` `.webm` |
| `music/` | `.mp3` `.m4a` `.wav` |

## After uploading

`ingest` prints your library size and whether it supports your configured
cadence. If it warns that cooldowns will relax, believe it — that means an
alert every day and visibly repeating content. Fix it by adding assets or
lowering `posts_per_day` in the campaign config.

Music also needs a row in `campaigns/clubs/LICENSES.md` (SPEC §4.4) — the
renderer warns about tracks with no entry.
