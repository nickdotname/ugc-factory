# Styles (renderers)

Back to [[README]]. A style is one script in `studio/` that turns `(song dir, seed, window)` into a finished
vertical video with the song as its sound. `studio/nightly.py` maps styles to scripts (`VISUAL` = picture styles
that can use any stretch of a song; `LYRIC` = styles that show the proven lyrics, so only well-timed stretches).
Every random choice inside a renderer goes through `studio/knobs.py` (`K.pick(name, options, rng)`), which records
it so [[learning]] can score it; `CQ_KNOBS` forces knobs.

| style | script | account | what it is | knobs (as of 2026-11-23) |
|---|---|---|---|---|
| band | lyric_video.py | close__quarters | Y2K desktop lyric video with band photos (now hot-take hooks) | wall, chrome, theme, caption, pictures, punch, chroma, scan |
| lofi | lofi_video.py | close__quarters | the band's own dance footage cut out, in a Y2K media player | theme, pop |
| cursor | cursor_video.py | close__quarters | the band rebuilt out of mouse cursors in a 3D Win98 world | world |
| cutout | cutout_video.py | close__quarters | the dance footage cut out full screen with sticker outlines, thrown around on the beat (big, echo, grid, duo); behind them flat colour with rings or library footage graded to the palette; spring motion, squash on the kick, a slide in each bar | stage, palette, trip, outline, words, bg, tone |
| producer | lyric_video.py | dylancantor23 | the song's stems as lanes / a mixer | layout, wall, colours, caption, ... |
| type | type_video.py | the.loose.change | kinetic type lyrics | layout, font, motion, palette, texture |
| psy | psy_video.py | psychedelic.station | audio-reactive fields (oil, julia, tunnel, ...) | field, pal, sym, motif, feedback, mirror, lyrics, ... |
| collage | collage_video.py | psychedelic.station | mirrored techno-temple collage | palette, density, ground |
| liminal | liminal_video.py | nostalgia.hub.vhs | liminal spaces on VHS | place, tape, tint, label, stamp, pace |
| math | math_video.py (+ studio/mathviz/) | math.explainers | integrals, Fourier, derivative, zeta, paper fold, sci8 pixel science (brain, heart, eyes, fission) | topic, theme, room, grid, target, ... |
| glitch | glitch_video.py | glitch.archive.exe | public-domain footage broken on the beat: datamosh, tracking, pixel sort, slit-scan, point cloud | source, main, accent, tone, pace, label |
| ascii | ascii_video.py (+ studio/asciiviz/, studio/pixelviz/) | ascii.terminal.dreams | pictures set in bold letters (108 x 66, 10 x 18 px each) with the code that draws them underneath. **wild** (the most-picked scene): a real picture set in type by `asciiviz/letters.py`: each letter cell is a material (orange takes o O 0 Q, water ~ = S, leaves v V Y W...), heavier where brighter, a stroke / \| - where an outline crosses it, over a dim wash of the picture's colour; pictures are hand-picked public-domain clips with one bold subject (NASA Earth, sunrise, zinnias, a lit creek: `SUBJECTS` in `wild.py`) and, once Kaggle has made them, our own single-subject clips (koi, jellyfish, macaw...: `studio/retro/prompts.json` `subjects`, themes `subject-*`, a third of each retro run). The koi (goldfish) also goes through the typesetter; galaxy, aurora, daisies paint per cell; planet, boulder, jelly are raymarched. About a third are isometric pixel worlds (old bridge, clay court, blacktop basketball, subway platform) under a painted sky (`pixelviz/sky.py`: night, dusk or dawn, drifting clouds, distant ridges, a moon or sun, birds) with weather (rain with splashes and lightning on the big bar line, snow that settles), small worlds drawn 5x instead of 4x. fireworks retired 2026-11-24 | scene, subject, palette, ramp, layout, sparks, pixel_sky, pixel_weather, pixel_cuts |
| physics | physics_video.py | physics.bounce.lab | bouncing-ball sims; every collision is a hit from the song's Ableton project. In circle and square the arena fills the screen and something builds with every bounce, said in frame 0 (`rule`: grow = the ball grows until it fills the arena, lines = every bounce leaves a line, multiply = the balls keep doubling to 32); the ball is already flying in frame 0 | scene, rule, hits, palette, trail, hook |
| earth | earth_video.py | earth.data.live | real satellites, flights, earthquakes on the beat | scene, palette, spin, hook |
| retro | retro_video.py | retro.vibes.arcade | Kaggle-made PS2-era levels, cut on the bar. A line over the picture (`hook`): spot ("pick one to live in", each place numbered), smoke ("where would you smoke?"; its own value so the numbers show if Instagram holds it back), memory, none | theme, screen, frame, cut, pace, hook |
| rocket | rocket_video.py | rocket.league.lit | our Rocket League clips: as-is or montage, moments on downbeats | format, frame, ramp |
| vintage | vintage_video.py | vintage.media.archive | pre-1931 film as an old print: tint, crank stutter, gate/iris, grain, dust, scratches, intertitle lyric cards; sometimes melts, burns or double-exposes | tint, crank, gate, cards, trip, pace, source |
| nyc | nyc_video.py | nyc.daily.aesthetic | NYC footage as a meme (white caption bar) or a fact that counts up on the beat | kind, look, pace, line/fact, source |
| tinycode | tinycode_video.py | tiny.code.loops | a few lines of numpy in an editor, and what they draw (13 programs: sunflower, knot, ridges, orbits, interference, lissajous, rose, spirograph, attractor, plasma, tunnel, metaballs, galaxy); the code shown is the code run | program, palette, glow, trail |
| cinema | cinema_video.py | ascii.cinema.tty | a public-domain film clip cut into a grid of letter cells, each the letter whose ink matches its brightness and the colour of the film under it, in a terminal; the kick pushes in, the snare flashes the brightest letters | cell, ramp, look, crt |
| alife | alife_video.py | digital.petri.dish | a slime mould of ~200,000 agents (each smells the trail ahead, turns to the strongest, leaves its own); the kick makes them run, the snare drops new ones in, the bass widens how far they look | start, palette, sense, steps |
| illusion | illusion_video.py | rotation.illusions | a shape made of dots, turning with no depth cue, so the direction is up to the viewer, then flipped for them (cloud, shadow); a flat disc that reads as a cone; a wheel that seems to run backwards at 30 fps; twelve dots that are three squares and four triangles at once (group); stripes that never move under sliding discs (stripes). 12 shapes drawn from formulas | kind, shape, palette, ask |
| race | race_video.py (scenes in studio/mathviz/: sorts, paths) | algorithm.races | algorithms racing on the same problem, one step each on the beat: four sorts on the same shuffled numbers; breadth-first, depth-first and A* through one maze | topic, lineup, maze, bars, theme |
| tests8 | tests8_video.py (scene: studio/mathviz/tests8.py) | 8bit.tests | pixel-art tests taken along with the song, in a room with a boombox that plays it: count the flashes (one per snare, answer at the end), read as fast as he raps (words-per-minute gauge) | test, sky |
| notes | text_video.py (thoughts: studio/notes/lines.txt) | moth.ate.my.notes | one thought, lower case, centred on a slowly drifting gradient that breathes with the kick; 11 s at most; a line is never reused until all are | line, look (dusk, sunset, orchid, lagoon), ink (white, black), face (round, tall) |

Open PRs adding styles (not merged at the time of writing): **fluid** (wind-tunnel Navier-Stokes sims for
physics.bounce.lab, #80), sorting/maze races for math (#77), goldfish for ascii (#79). See [[backlog]].

## Shared conventions

- Output 1080×1920, 30 fps, H.264, the song's audio clip muxed in (`beat.audio_clip`).
- `beat.load(slug, t0, t1)` gives per-frame stem levels, kick/snare/hat frames and the beat grid; renderers move
  on those, not on guesses.
- A `.json` beside each video records its knobs (and footage keys); nightly copies it into `recipes.json`.
- A credit line `♪ title — close quarters` near the bottom, above Instagram's UI.
- No engagement bait in on-screen text. Lyric styles show lyrics only where timing was verified.
