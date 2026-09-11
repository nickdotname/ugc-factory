# Music licences

Every track baked into a video is fingerprinted by the network it lands on.
What happens next is not the same on every network, and this campaign group
deliberately treats them differently.

Approved royalty-free sources, if tracks are ever swapped: Pixabay Music,
Uppbeat (free tier), YouTube Audio Library, Epidemic Sound (paid).

Note: the **YouTube Audio Library** (studio.youtube.com → Audio Library) is a
free, cleared catalogue. It is not the same as downloading a song *from* a
YouTube video, which yields the copyrighted master.

| filename | source | licence | used on |
|---|---|---|---|
| music_01.mp3 | downloaded from YouTube | none | clubs (Instagram) only |
| music_02.mp3 | downloaded from YouTube | none | clubs (Instagram) only |
| music_03.mp3 | downloaded from YouTube | none | clubs (Instagram) only |

## Why these are muted on two networks and not the third

All three tracks are copyrighted recordings. That is a deliberate, informed
choice rather than an oversight, and it is why `clips.json` in `clubs_tt` and
`clubs_yt` holds every track out of the randomizer while `clubs` does not.

The networks enforce differently, and the campaigns are shaped around it:

* **YouTube** runs Content ID on every upload. A claim can block a Short
  outright, which reads as zero views rather than few.
* **TikTok** mutes or removes commercial audio on business accounts.
* **Instagram** licences far more broadly, and in practice has not touched
  these across 132 posts and ~37,000 views.

The evidence for the split is in the metrics cache. Both muted channels went
to literal zero on new posts from 2026-08-18 while Instagram kept climbing.
After the mute landed on 2026-08-23, TikTok posts began clearing 50–400 views
again. YouTube did not recover, which is consistent with claims already
accrued on the channel — muting stops new ones, it does not clear old ones.

## The residual risk, recorded rather than argued

Instagram's tolerance is not a licence. Meta's deals cover audio selected from
Instagram's own library rather than an arbitrary MP3 baked into an uploaded
file, and consumer music licensing does not extend to promotional use. The
exposure is small in practice and has been weighed; it is written down because
if it ever does land, it lands on the only channel carrying this brand.

Swapping in royalty-free tracks would remove it without changing anything a
viewer notices — the bed sits at `music_volume: 0.10`, under voiceover — and
TikTok recovered with no music at all, so the beds are not carrying
performance. That remains available, and is not currently planned.
