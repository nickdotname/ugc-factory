# Cluster `notes`: the five text-on-gradient accounts

Reviewed 2026-11-26. Accounts: @moth.ate.my.notes (notes_ig, notes_app, studio/notes/lines.txt), @crying.in.trader.joes
(her_ig, notes_her, her.txt), @grip.tape.thoughts (him_ig, notes_him, him.txt), @situationship.notes (date_ig, notes_date,
date.txt), @dining.hall.philosopher (college_ig, notes_college, college.txt). Renderer: studio/text_video.py (the four
others are 21-line wrappers that only swap bank, recipes file, id prefix and look/ink/face weights).

Contact sheets (frames 0/150/320, seeds 5 and 6, each style) are in
/tmp/claude-0/-home-user-ugc-factory/bd16ba37-fa04-5fa1-8c52-0897619fc36c/scratchpad/notes/.

Review only: nothing in the repo was changed.

---

## 0. Why there are no numbers, and whether the learner is blind

**Finding: every insights call for all five accounts (and algorithm.races, 8bit.tests) still fails today with
`(#10) Application does not have permission for this action`, the metrics job stays green, and the learner is
completely blind on this cluster.**

Evidence:

- `campaigns/notes_*/posts.json` holds 9/7/7/1/1 posts, each with `metrics: []` and `fetched_at` 2026-11-26T18:54Z, i.e.
  the fetch runs and returns nothing.
- metrics run 45876580322 (2026-11-26 18:31 UTC), job `metrics (notes_app)`: every media id logs
  `instagram_insights_unavailable ... (#10) Application does not have permission for this action (HTTP 400, code 10)`.
  Same for notes_date (token IG_TOKEN_9, issued through connect.closequarters.vip on 2026-11-25 21:51 UTC, run 45708183745)
  and algo_races (IG_TOKEN_2).
- `studio/weights.json`: `notes_app/notes_her/notes_him/notes_date/notes_college: {"posts": 0, "waiting": 0, "weights": {}}`.
  `studio/learn.py` `score()` returns None when `views` is None, so these posts are not even counted; nightly's Thompson
  sampling runs on empty stats, i.e. pure chance, and `EXPLORE` has nothing to explore against.
- The dashboard/baseline shows n_with_m = 0 for all five.

Why the 2026-11-25 fix in traps.md ("insights permission added; tokens generated again") did not take, in order of
likelihood:

1. **The tokens still do not carry `instagram_business_manage_insights`.** The connect workflow log shows IG_TOKEN_8/9/11
   being saved on 2026-11-25 and no run that saved IG_TOKEN_4/5/6 after the permission was added (the last ig-check
   that saw them, 45638189782, is 2026-11-25 14:49 UTC). IG_TOKEN_9 was minted *through the connect link* that day and
   fails the same way, which points at the login configuration itself: `cqconnect/worker.js` uses
   `CONFIG_ID = 1196481663031292` ("Instagram API (Unified Login)") and passes no `scope=`; the permissions a config
   grants are set in the app dashboard, and if that configuration was not edited to include
   `instagram_business_manage_insights`, every token it issues lacks it, however often it is re-issued.
2. **Host.** `accounts.yaml` has `login: facebook` for all five, so `src/publishers/instagram.py` calls
   `graph.facebook.com/v27.0/{media}/insights`. ig-check confirms the tokens answer on the facebook host for
   publishing, but Page-less (Instagram-login) accounts are documented against `graph.instagram.com`; code 10 on
   graph.facebook.com is also what you get when the asset is not Page-backed. Worth one request to rule in or out.
3. **Metric names.** Not the cause: the same `_INSIGHTS` list works for the Page-backed accounts, and a bad metric name
   returns code 100, not 10.

Nothing alarms, because `_media_metrics` turns `InvalidPostError` into a warning and returns `()`, and
`post_metrics_cached fetched=1` is logged as success. Two days of posts on seven accounts have been thrown away
silently.

What to do (quick, operator + one small PR):

- Add a `scopes` line to `scripts/ig_token_check.py` / `scripts/ig_check.py` (debug_token already answers `scopes`;
  print the list, never the token) and run ig-check for `notes_ig her_ig him_ig date_ig college_ig races_ig tests8_ig`.
  That settles (1) in one run.
- If the scope is missing: in the app dashboard edit the Unified-login configuration 1196481663031292 to include
  `instagram_business_manage_insights`, then re-run the connect link for each of the seven accounts (operator logs in;
  the pickup job overwrites the slot). Note in traps.md that the connect config, not the use-case page, is what
  the tokens inherit.
- If the scope is present: make `_media_metrics` retry on `HOSTS['instagram']` for accounts whose token has no Page
  (or set `login: instagram` for them if publishing also works there; ig-check will say).
- Either way: make `metrics` count `instagram_insights_unavailable` per account and fail/notify when an account's
  every post is refused (`notify.on` already has a webhook); the dashboard should show "no figures (permission)" not "-".
- Until fixed, treat everything below as pre-data. The learner cannot learn here, and `nightly` is choosing look/ink/
  face/cut/song at random with a straight face.

---

## 1. @moth.ate.my.notes (notes_app)

**Verdict: needs work. Biggest lever: make it the one text page that is openly about the sound (the ten "this song"
lines are its only differentiator), and fix the pipeline so it can learn.**

**Numbers.** 10 published, 5 failed as "duplicate booking (two top-ups at once)", 6 queued. No metrics (see §0).
16 recipes: look sunset/lagoon/dusk 5/5/5, orchid 1; ink white 14 / black 2; face round 9 / tall 7; cut tight 8,
short 5, full 3; eight songs over two nights. Nothing can be read from this. Even with numbers, the `line` knob is
single-use (a line is never repeated until the bank is spent), so the learner can never learn *which lines* work,
only look/ink/face/cut/song; 5 posts/night across 4 looks x 2 inks x 3 faces x 3 cuts x 15 songs is ~2 weeks per
reliable signal per knob at best. The "cut" knob is partly fictional here: `MAX_SEC = 11` caps every card, so
`full` (a 22 s stretch) and `tight` (10-20 s) both become 11 s; only `short` (6-9 s) is a different length.

**Content audit.**
- Cover/first second: the whole line is on frame 0 (good: the DM share preview and the grid show the thought). But
  nothing moves except a slow gradient; there is no "look at this" in second one other than the words themselves.
- Legibility: Figtree 800 at ~97 px, 4 rows, centred at 47% height, well inside the safe area (x 96-924). Fine on a
  phone. White on dusk/orchid is the cleanest; black on citrus/lagoon reads but has lower contrast against the
  yellow lobe.
- Loop: the gradient drifts on sines, so frame 329 does not match frame 0; there is no crossfade back. Minor.
- Song credit: three places, all off-card: the reel's audio label (`audio_name` "Full Ride – Close Quarters",
  which is Instagram's own tappable UI and the best of the three), caption line 2 ("🎧 Full Ride – @close__quarters
  #relatable #humor #createmode"), and the first comment. The caption's *first* line is a generic tag ("real ones
  know", "anyway") unrelated to the card. The CTA appended is "stream Full Ride: link in bio" on a faceless page
  whose bio is a band link: this is the weakest part of the funnel (a notes page asking you to "stream" something
  reads as an ad).
- Hashtags: `#createmode` is Instagram's story text-tool tag and signals nothing; `#relatable #humor` are fine.
- Niche consistency: the bank mixes three voices (college deadlines, situationship, band/music). A follower would not
  know what they get; the handle promises "notes app at 3am", which is the strongest of the three.
- Cadence: 5/day from day one on a 2-day-old account with no Page, posting at :41 every slot while her/him post at
  :44 and :47. See §7.
- House rules: no band footage, no bait on cards. `"u up?"` card and the "not a cry for help. a little bit" caption
  (captions.txt line 9) are the two to watch (the second is a self-harm-adjacent phrase that classifiers and
  humans both read badly; drop it).

**Bank review (79 lines).** Voice: three voices, as above; the notes-app/music third (n045-n054, n077-n079) is the
best writing in the whole cluster ("whoever is playing bass on this owes me an apology", "sent them this song / they
said 'nice' / we're over", "i forgive but my notes app doesn't", "the moth ate it"). Specificity: good when it names a
thing (lighthouse keeper, "argue about the snare for 6 weeks", "meet god at 11:58", "- the ghost"); weak in the
"i'm not X i'm just Y" / "normalize ..." slogan lines. Cliché density: medium; "my toxic trait", "my love language",
"healing era", "main character", "not me ...", "nothing humbles you like" are all 2022-23 Twitter formats. Asks: none
(the "u up?" card is a quoted text, not a question to the viewer). Mental-health: n019 "being the funny friend... who
is checking on the comedian" is fine; nothing risky. Real people: none. Song fit: this is the only bank that ever
points at the sound, and that is exactly what the whole engine exists for.

**Send-worthy lines here** (and why): n004 "the group chat has been silent for 3 days. somebody did something"
(sent *to* the group chat), n031 "i'll be there in 5 from your bed" (sent to the late friend), n010 "if i send you
a song at 2am that is the most serious thing i will ever do" (sent *with* the song: the receiver gets the message and
the band in one tap), n052 "i sent this song instead of saying how i feel / again", n054 "sent them this song / they
said 'nice' / we're over", n039 "we should catch up soon / we both know we won't". Pattern: **a named relationship
(you, the group chat, the late friend) + a shared ritual + a detail precise enough that the receiver knows it is
about them.** The song lines add a third thing: the send *is* the message, so the reel's audio travels with it.

**Ten new lines in the house voice (lower case; all statements):**
1. you're the friend i send songs to at 2am and never explain. this is one of them
2. the group chat has 3 people who talk and 5 who just react. you know which one you are
3. we said we'd leave at 10. it's 11:40 and you're taking a photo of the cat again
4. i rehearsed the whole conversation. you just said "hey" and i forgot all of it
5. if you got this with no caption, it's about us and i'm not elaborating
6. you say "5 minutes away" from your bed. i say "take your time" from the parking lot. balance
7. the song isn't about you / (skip to 0:41. it's about you)
8. my notes app has a list called "things to say to you". the song does it better
9. we don't talk anymore but if this came on in a store i'd still think you'd like it
10. you're not getting a text. you're getting this. that's worse and we both know it

---

## 2. @crying.in.trader.joes (notes_her)

**Verdict: needs work. Biggest lever: pick one voice (the cosy, overwhelmed, wry one the handle promises) and move the
raunchy half to date.txt or out.**

**Numbers.** 8 published, 4 duplicate-booking failures, 8 queued; 16 recipes (dusk 6, orchid 5, meadow 3, rainbow 2;
white 16/16 even though INK_W allows black: `strong` face with black ink has never been drawn here; strong 9 /
round 7). No metrics (§0).

**Content audit.** Same card, same caption template ("not me / 🎧 Notta Problem – @close__quarters #relatable
#girlhumor #createmode / link in bio to stream Notta Problem"), same first comment, same window and 5/day, posting 3
minutes after moth. Frame 0 fine; Montserrat ExtraBold black on citrus (seed 5) is the most legible card in the
cluster. Nothing on the card or in the caption is "Trader Joe's", "crying", or in fact feminine except the hashtag:
the identity lives only in the handle.

**Bank review (70 lines).** Voice: h001-h045 are one consistent voice (over-prepared, over-feeling, funny about it:
"i got ready for 2 hours to sit in a car and say i'm tired", "buying a candle that smells like a place you've never
been and getting emotional about it", "i bought a planner and now i plan to use the planner"). h046-h070 are a
different writer: "i'm not easy i'm just efficient", "my body is a temple and right now the temple is accepting
visitors", "a good girl with a bad search history", "i'll be a wife one day. tonight i'm a problem". These are
date.txt lines (h051 and d051 are 78% the same sentence; h062/d028, h050/d002 are the same joke) and they are also
the ones most likely to be classed "sexually suggestive" and kept out of recommendations (§7). Specificity: high in
the first half, slogan-level in the second. Clichés: "girl math", "it's giving", "roman empire", "i'm literally so
back", "bestie", "soft era", "in my bag", "main character" are dated slang; six "era"s. Asks: none. Mental-health:
h037 "crying in the car is cheaper than therapy and the acoustics are better" is on-brand and harmless; h044 "i'm not
ignoring you i'm just emotionally on airplane mode" fine. Real people: none. Song fit: **zero lines mention the
sound**; the song is wallpaper here.

**Send-worthy:** h016 "the friend who says send me the address and then calls you from the parking lot anyway"
(this *is* a send: it names the friend), h035 "'we should hang out soon' is the most beautiful lie two girls can
tell each other", h032 "i need a friend who says let's go before i finish the sentence", h046 "he looked at me like
i was the last slice of pizza", h003 "someone to hold the bag while i try things on". Pattern: **the friend
archetype named precisely enough to be sent to that one friend**.

**Ten new lines:**
1. you're the friend who says "two minutes away" while still choosing earrings. i love you. hurry up
2. we went in for one thing. you're holding a plant, i'm holding a candle, neither of us has the one thing
3. cried in the car, fixed my mascara in the parking lot, bought the flowers anyway. it's called a process
4. you text "are you ok" and i send you a song. that's the answer. read into it
5. "we should hang out soon" is the fifth time we've said it this year. this is me naming a real date
6. the group chat has had "wine night?" pinned since march. i'm calling it. friday
7. i'm not mad. i'm cleaning the whole apartment with this song on. ask me again in an hour
8. to the one who holds my bag, my drink and my opinions while i try things on: you're the one
9. got ready for two hours, sat in your car, said "i'm tired". that's not a complaint, that's a review of my week
10. i can't say it so here's the chorus. if you know, you know. you know

---

## 3. @grip.tape.thoughts (notes_him)

**Verdict: needs work, but the clearest identity of the five. Biggest lever: make every line skate (two thirds of
the bank is generic "guy" content) and drop the "would you rather" cards.**

**Numbers.** 8 published, 5 duplicate failures, 8 queued; 16 recipes (meadow 6, citrus 4, sunset 3, dusk 2,
rainbow 1; black 3; round 8 / strong 8; cut spread 6/5/5). No metrics.

**Content audit.** Same card and caption template ("landed it (emotionally) / 🎧 Prologue: Before – @close__quarters
#skateboarding #relatable #humor / link in bio to stream Prologue: Before"). `#skateboarding` is the only hashtag in the
cluster that puts a post in a real community; it is also the one a skater audience will judge instantly against
pages full of actual footage. A text card on a sunset wash is not what #skateboarding looks like, so the
hashtag may bring the wrong viewers (or none). The handle, captions ("just push", "another day another slam",
"grip tape wisdom") and the skate block of the bank are a coherent page; m001-m070 (fridge, mechanic, dad energy,
"we should get food sometime is how men say i love you") are a different, older-sounding page.

**Bank review (106 lines).** Voice: two voices as above; the skate block (m071-m106) is the best: "my knees sound
like bubble wrap and i'm 20", "bro took 47 tries and then landed it while no one was filming", "a new deck smells
like possibility and also like i'm broke again", "the shoe has a hole in the exact spot where the kickflip happens.
it's a sign", "i don't use capital letters because my thumbs are tired from pushing" (meta, perfect for the format),
"40 - 4 = you're still in bed". Specificity: high in the skate block, low before it. Clichés: "bro" x9 (fine for the
voice), "nothing humbles you like" x2 (m040/m076 are the same template), "my love language" x2, "walk of shame is
cardio with a story" duplicates date's "cardio with plot". Asks: **four "would you rather:" cards (m093, m094, m102,
m106) and "yo bro you got a charger?"**: the "would you rather" cards are questions put to the viewer whose only
purpose is a reply; CLAUDE.md bans comment-asks and these are comment-asks in a trench coat. Retire or cap at one as
a measured experiment once metrics exist. Also m055 "i'm not saying i'm good in bed but i've slept 11 hours straight"
and m045 "i'm not a player i just have a lot of friends who happen to be girls who happen to text me at night" are
the two lines a skate kid audience will find corny. Mental-health: none. Real people/brands: none (good; the bank's
header rule holds). Song fit: zero lines reference the sound; m023 "i don't get sad i just put on a hoodie and listen
to the same album for a week" is the only one that gestures at music.

**Send-worthy:** m098 "u said 'on my way' 40 minutes ago / the skatepark is 4 minutes away / 40 - 4 = you're still in
bed" (sent to that friend; the three-beat layout is also the most watched-to-the-end shape in the bank), m086 "my love
language is you holding my phone while i try the same trick for an hour", m091 "bros will say one more try and then
take nine", m081 "the security guard is the final boss of every good spot", m085 "when the whole park claps after you
finally land it". Pattern: **the crew ritual, told as if to the crew.**

**Ten new lines:**
1. you said "on my way" 40 minutes ago. the park is 4 minutes away. i've done 9 tries and a nap
2. the friend who holds your phone for an hour and still says "one more" after you've landed it: keep him
3. we have one deck's worth of money and two decks' worth of damage. so this is your problem too
4. the security guard knows our names now. that's not a warning, that's a relationship
5. you film every slam and none of the lands. i've seen your camera roll. i know what you are
6. landed it on try 31. nobody filming. so this song is the only proof and you're the only one who knows
7. if this is playing in the car we're going to the spot and we're not discussing it
8. my knees, your wrist, his elbow. between the three of us we have one working skater
9. you said "just push" and that's how i met the ground. send a hospital playlist
10. no thoughts. one song. the lot is empty and your shift ends at 11

---

## 4. @situationship.notes (notes_date)

**Verdict: rethink. It is her.txt's second half under another handle, and its bank is the one most likely to be
kept out of recommendations. Biggest lever: either merge it into crying.in.trader.joes as that page's sharper
mood, or make it the deliberately clean "mixed signals" page (the handle supports that) and move the explicit
innuendo out.**

**Numbers.** 2 published (first on 2026-11-26 13:22 UTC), 2 duplicate failures, 4 queued; 6 recipes (sunset 3; black
2; cut short 5 of 6). No metrics.

**Content audit.** Same card; `#situationship #relatable #datinghumor #talkingstage` is the best hashtag set in the
cluster (four real communities). 2/day for the first week is right. Caption first lines ("i feel attacked", "this is
a call out", "no because why is this me") are better than moth's because they frame the card as *sent to you*.

**Bank review (55 lines).** Voice: consistent (one raunchy, funny, unbothered voice), and the most quotable per line
of the five ("he's not my boyfriend he's just my 2am customer service line", "i told him to text me when he gets home
and he never left", "he said he'd change and he did. his number", "the hookup was a 6 but the forehead kiss was a 10
and now i'm in danger"). Specificity: good. Clichés: "bop era" x3, "walk of shame", "you up" x2, "my love language",
"i'm in my ... era". Asks: none (the four "?" are rhetorical). **Risk lines:** d032 "better conversations with my
vibrator's charger" (explicit object: the clearest recommendation-guideline problem in the cluster), d004 "body
count? i don't do math on weekends" and d040 "cardio with plot", d015 "getting cracked by someone who won't call me
back", d043 "my phone's most used emoji is the eggplant", d050 "i'm not jealous he can talk to whoever he wants, i'll
just ruin her life" (reads as a threat against a woman; the only line in the cluster that targets a person, even a
fictional one), d045 "i'm not a homewrecker i'm a home-visitor" (cheating as the joke). Instagram's Recommendation
Guidelines exclude "sexually suggestive" content from Reels/Explore recommendations and say an account that
*repeatedly* posts it can become ineligible as a whole (sources in §8). For a 1-day-old faceless page, recommendations
to non-followers are 100% of its reach. Mental-health: d036 "my therapist said stop going back. my ex said come over.
guess who's more convincing" is fine. Song fit: zero lines reference the sound.

**Send-worthy:** d028 "he said he's not looking for anything serious. me neither. we've seen each other 9 days in a
row" (sent to *him*, or to the friend who is watching it happen), d018 "my friends: he's toxic / me, already wearing
his hoodie: and?" (sent to the friends), d036 (therapist/ex), d046 "me at 2am: you up / me at 9am: who are you",
d055 "checking if my situationship watched my story while he's in my bed". Pattern: **the contradiction stated as a
fact, addressed to the one person who can't argue with it.**

**Ten new lines (sharper, not more explicit):**
1. you've seen me 9 days in a row and said "nothing serious" 9 times. one of those numbers is lying
2. we're not exclusive, we're just both too lazy to meet anyone new. it's not love, it's efficiency
3. you hit me with "haha" and i've been drafting a reply since tuesday. this is the reply
4. to the friend who said "don't text him": i didn't. i sent him this. that's different. legally
5. the label we agreed not to put on it has been on it since august. you're the only one who hasn't read it
6. your friends know about me. my friends know about you. the only two people who don't know are us
7. if you leave before i wake up again i'm keeping the hoodie. these are the terms and conditions
8. i'm not over it. i'm just two songs further down the playlist than you are
9. we both said "who are you" at 9am. we both still answer at 2am. the math is the math
10. "wyd" at midnight has never once meant "what are you doing". you know it. i know it. the uber knows it

---

## 5. @dining.hall.philosopher (notes_college)

**Verdict: rethink the bank, keep the handle. The handle is the best in the cluster and the bank does not deliver it:
it is a college-hookup page, not a dining-hall philosopher. Biggest lever: rewrite toward deadpan dorm/dining-hall
observation (which also solves its recommendation risk and its overlap with date/her).**

**Numbers.** 1 published (2026-11-26 13:23 UTC), 2 duplicate failures, 3 queued; 4 recipes (tall face 3 of 4: the
only page where BarlowCondensed is common; black ink 2). No metrics.

**Content audit.** Same card; `#college #collegelife #relatable #dormlife` good. 2/day first week right. Caption first
lines ("tuition well spent", "the real education", "pray for my transcript") are the most on-voice of the five
caption files, and "the real education" quietly rhymes with the album title EDUCATION, which nothing else in the
cluster does: there is a whole page in that pun (every card a "lesson", the song as the soundtrack to a semester).

**Bank review (52 lines).** Voice: consistent, but it is the date.txt voice on a campus: 34 of 52 lines are
hookup/party ("freshman 15 guys in one semester", "body count speedrun", "bought condoms and ramen in the same trip",
"plan B and a plan C for the 10am quiz", "my roommate and i shared a hookup"). The best lines are the observational
ones the handle promises: c052 "the dining hall omelet guy knows more about my love life than my mom", c023 "the RA
asked if everything's ok in our room. ma'am no", c035 "woke up with a sharpie mustache and a 2.1 gpa", c010 "group
project went from zoom call to cracking real quick" (half), c038 "the parking ticket was the most committed thing
anyone did for me this semester", c049 "the dining hall food does to me is worse than any guy". Specificity: mixed.
Clichés: "villain origin story", "hits different", "hot girl summer", "era" x2, "sugar daddy". Asks: none. Risk:
c003, c021, c024, c027, c045 (plan B) are the lines a reviewer would flag as sexually suggestive; c003 also stacks
"freshman 15" (weight) with promiscuity, close to the bank's own "no jokes about anyone's body" rule. Real people/
schools: none, good. Song fit: zero lines reference the sound.

**Send-worthy:** c052 (omelet guy), c011 "college is paying $50k to make out with people from your hometown's rival
school", c033 "we met at a party, hooked up, now we sit next to each other in organic chemistry" (sent to that
person), c025 "my roommate's boyfriend has been 'visiting' since september" (sent to the roommate), c012 "your entire
biology lecture with filters". Pattern: **a shared institution (the dining hall, the lecture, the RA, the roommate)
plus one true detail.**

**Ten new lines (the philosopher, not the party):**
1. the omelet guy knows your order, your ex and your midterm grade. he is the only consistent man on campus
2. you've been "at the library" since 4. the library closed at 2. i can see your location. hi
3. one couch, three roommates and a guy who's been "visiting" since september. he pays for nothing. he gets the couch
4. the dining hall has a "build your own" bar and it is the closest thing to free will this semester
5. group project: you did the slides, i did the talking, he said "looks good". we got an a. nobody learned anything
6. you say "quick pregame". i say "i have an 8am". we both know where this goes and it isn't the 8am
7. the thing about the 2am walk back from the library is you're not sad, you're just outside
8. my roommate's alarm is my alarm. i have never set one. we are both late
9. laundry day is the only day i look like i have my life together, because i'm wearing the last clean thing
10. to the one who still sits next to me in orgo after everything: we're adults. pass the notes

---

## 6. The renderer, against the top text pages of 2025-2026

What the format looks like at the top of the niche (from the research in §8 and the formats visible on Reels
through 2025-2026; the cloud session cannot open instagram.com, so this is from secondary coverage plus the
formats Later and others describe):

- **Backgrounds:** the two dominant looks are (a) the Instagram "Create mode" wash (exactly `rainbow`/`citrus`,
  which text_video already has) and (b) a *screenshot of the iPhone Notes app* or a plain black/paper card with
  system type. (a) is what most people's own text stories look like, so it reads as "a person", not "a page".
- **Type:** system-looking sans (SF/Helvetica-ish, i.e. Figtree is right; Montserrat ExtraBold reads "meme page").
  Lower case, left-aligned or centred, 10-20 words. Under 15 words is the meme-page rule of thumb quoted in the
  research; the banks' medians are 12-14 words, maximums 19-27: the long ones (n003, n027, h008, m057, c011) should
  be two-beat cards or cut.
- **Motion:** the ones that get watched to the end are **two-beat**: setup on frame 0, the punchline lands 2-4 s
  later (often on the beat, often with a small zoom or a second line typing in). A one-beat card is read in ~3 s and
  swiped at 3.5 s, which is a completion of ~30% on an 11 s video and the worst possible `done` score in
  `learn.py`. The banks already contain two- and three-beat blocks (n033-n044, m098, d018, d046); the renderer shows
  all rows at once from frame 0, throwing that structure away.
- **Length:** 5-8 s and loop-clean, so a re-read counts as a second loop (completion > 1 in learn.py's own terms).
  11 s is long for one sentence.
- **Audio credit:** top pages run a sound that is *recognisable* or that they own; the audio label is what people
  tap. "Use audio" from the reel's audio page is the discovery path that costs the viewer nothing. Nobody puts "link
  in bio to stream" in a text-page caption; the better pages put the thought itself as the caption's first line
  (searchable, and shown under the DM share preview), then the credit.
- **Posting rate:** 1-3 a day on established pages; new pages are not 5/day on day two.
- **Saves and sends:** sends come from "this is you" lines (named relationship), saves from lists / "how to" / lines
  you want as a caption later. Mosseri's Jan 2025 guidance names watch time, likes per reach and **sends per reach**
  as the three signals, with sends the strongest predictor of reaching non-followers.

Against that, text_video.py: static text from frame 0 (good cover, bad retention), 11 s cap (too long for one beat),
gradient breathing of +3.5% on the kick (invisible on a phone: the sheets show no difference across 320 frames),
no two-beat reveal, no loop seam, looks shared by all five pages, caption first line wasted on a generic tag,
"stream X: link in bio" CTA on every post, `#createmode` hashtag. The typographic quality is good; the behaviour is
a still.

---

## 7. Five near-identical accounts: is it a risk, and would two beat five?

Risk, in order:

1. **Synchronised, templated posting from one network.** The three 5/day pages post at :41, :44 and :47 of the same
   hours, the two 2/day pages at :18 and :22, all with the same caption template, same first comment, same
   `audio_name`, same looks, created from one Meta account (her/him via iPhone Mirroring inside the existing
   account) and connected to one app. Instagram does not publish a "same owner" penalty and multi-account ownership
   is allowed, but its 2026 originality rules only recommend one of several identical pieces of content, and the
   network-reach advice from practitioners is that "repeated creative packaging, newly created or cold accounts,
   synchronized posting" is what drops reach across a batch (TokPortal, §8). The cards are different lines, so they
   are not identical media; the *packaging* is identical. Quick fix: stagger `slot_offset_min` by hours not minutes,
   give each page its own caption shape and first-comment wording, and its own looks (today her/him/college all draw
   citrus/rainbow/meadow).
2. **Bank exhaustion = self-reposting.** At today's rates the banks last 16 (lines), 14 (her), 21 (him), 27 (date),
   26 (college) nights; after that `fresh_line` serves "the longest-unused half again", i.e. the page starts
   reposting its own text, which is the one thing a text page must not do. Five banks at 5/day need ~125 new lines a
   week to stay fresh; two pages at 3/day need ~40.
3. **Recommendation eligibility.** date.txt and college.txt (and her.txt's second half) are sexually suggestive by
   Instagram's recommendation standard; a page that repeatedly posts it can lose recommendation eligibility for the
   whole account, and those pages have no followers to fall back on.
4. **Dilution of the learner.** Even with metrics fixed, five pages x ~8 knobs x 5/day is five thin experiments
   instead of one deep one; nothing transfers between campaigns in `weights.json`.

**Two strong voices beat five thin ones.** Keep the two with a real identity and a distinct audience:
**@grip.tape.thoughts** (skate, male, the only page whose hashtag is a community; make the bank 100% skate and keep
the meta "thumbs tired from pushing" voice) and **@moth.ate.my.notes** (the notes-app confessional that is openly
about the sound: fold the best of lines/her/date into it as moods, and keep the song lines). Keep
**@dining.hall.philosopher** only if someone will write the deadpan dorm bank the handle deserves (it is the one
handle that rhymes with EDUCATION); pause **@situationship.notes** and **@crying.in.trader.joes** (or merge:
trader.joes gets her.txt h001-h045 and the clean date lines, situationship pauses). Pausing is cheap
(`paused: true`, `per_night: 0`), and the lines are not lost.

---

## 8. Research and sources

- Mosseri, Jan 2025: the three signals are watch time, likes per reach and sends per reach; sends correlate most with
  reaching non-followers. Buffer's guide: https://buffer.com/resources/instagram-algorithms/ ; Uppbeat on sends and
  carousels: https://uppbeat.io/blog/creator-news/whats-working-on-instagram-right-now-carousels-and-sends-says-adam-mosseri ;
  SEJ on sends: https://www.searchenginejournal.com/instagram-algorithm-shift-why-sends-matter-more-than-ever/521389/ ;
  Social Media Today on the 2025 guidance (watermarks, engagement bait and reposts hurt reach; Reels over 90 s hurt):
  https://www.socialmediatoday.com/news/instagram-shares-algorithm-2025/738034/
- Posting frequency and trial reels (Mosseri: more posts generally more reach, no fixed number; trial reels show
  small creators to non-followers): https://routenote.com/blog/how-often-you-should-post-on-instagram/ ,
  https://www.socialmediatoday.com/news/instagram-chief-shares-algorithm-insights-and-posting-tips/831326/
- Originality: Instagram recommends only one of several identical pieces of content; accounts that repeatedly
  post unoriginal content are removed from recommendations (extended to photos/carousels April 2026):
  https://creators.instagram.com/recommendations-and-originality ,
  https://techcrunch.com/2026/04/30/instagram-restricts-reach-of-content-aggregators-in-new-crackdown/ ,
  https://petapixel.com/2026/04/30/new-instagram-policies-target-reposted-content/ ,
  https://www.socialmediatoday.com/news/instagram-algorithm-prioritize-original-emerging-creators/714777/
- Multi-account networks (practitioner guidance: repeated packaging, cold accounts, synchronised posting drop
  reach across a batch; change caption, first-frame text, cover, posting time per page):
  https://www.tokportal.com/learn/duplicate-reels-across-multiple-instagram-accounts ,
  https://www.tokportal.com/learn/instagram-reels-reach-dropped-cross-posting
- Recommendation Guidelines (sexually suggestive content is not recommended to non-followers; repeated posting can
  make the whole account ineligible): https://help.instagram.com/313829416281232 ,
  https://help.instagram.com/613868662393739 ,
  https://creators.instagram.com/blog/instagram-recommendations-eligibility-tips-creators ,
  https://about.fb.com/news/2026/11/an-update-on-the-content-we-recommend-on-instagram-in-india/
- Text-on-screen formats and length (under ~15 words; setup/punchline on a sound; relatable "this is so me" drives
  sends): https://later.com/blog/instagram-reels-trends/ , https://getreelyze.com/guides/increase-reel-shares ,
  https://www.rickyspears.com/instagram/grow-meme-page-instagram/
- Audio: original audio on a public account can be reused via "Use audio"; the audio page lists every reel on the
  sound; Instagram's Audio tab for discovery: https://help.instagram.com/iphone-app/329208821595430 ,
  https://diymusician.cdbaby.com/releasing-music/instagram-reels-music/ ,
  https://musicinafrica.net/node/166952
- Error (#10) on insights: Supermetrics/Dataslayer tie it to the missing insights permission on the connection:
  https://docs.supermetrics.com/docs/how-to-fix-instagram-insights-failure-errors ,
  https://support.dataslayer.ai/instagram-insights-how-to-solve-the-error-10-application-does-not-have-permission-for-this-action

Note: creators.instagram.com, buffer.com, uppbeat.io, socialmediatoday.com and tokportal.com could not be fetched
from this session (not in the allowed network); their content above is from search summaries and should be
re-read before being quoted further.

---

## 9. Recommendations, ranked by expected impact

1. **Fix insights for the Page-less accounts (quick, operator + 1 small PR).** Print `scopes` from debug_token in
   ig-check; add `instagram_business_manage_insights` to the Unified-login configuration if missing and re-connect
   all seven accounts; else try `graph.instagram.com` for insights. Make metrics notify when an account's every post
   is refused. Measure: posts.json gains `metrics`, weights.json `posts` > 0. Nothing else can be measured until
   this is done.
2. **Two-beat cards (medium, text_video.py).** Rows before the first blank line appear on frame 0; the rest land on
   the first downbeat after 2.0-2.5 s (the `beat` grid is already loaded), with a 6-frame fade/rise. Knob
   `reveal: {none, beat}`; the learner measures it through `done` (completion) and skip rate. Blocks without a blank
   line get a reveal point before their last clause when a `/` is present in the bank (add `/` to existing one-liners
   where the punchline is obvious: "he said he'd change and he did. / his number").
3. **Shorter and loop-clean (medium).** `MAX_SEC` 11 -> 7 for one-beat cards, 9 for two-beat; last 9 frames fade the
   gradient back to frame 0 (the other renderers already do this). Measure: completion > 1 appearing in learn.py.
4. **Caption = the line (quick, captions.txt / nightly).** First caption line is the card's own text (or its first
   beat), then "🎧 {name} – @close__quarters" and 3-4 real hashtags; drop `#createmode`; drop "stream X: link in bio"
   from the CTA on text pages (`cta_every: 0` for these campaigns, or a softer "this is {name} by @close__quarters"
   as the only credit line). Keep the first comment. Measure: comments/sends per reach, profile visits if available.
5. **Song lines in every bank (quick, banks).** 15-20% of each bank refers to the sound in the page's voice ("if this
   is playing in the car we're going to the spot"); nightly could prefer a song line for the first post of the day.
   This is the only place where the format and the band's goal are the same thing. Measure: sends per reach of
   song lines vs others (needs the `line` knob grouped into `kind: song|friend|self` so the learner can see it).
6. **Un-synchronise the network (quick, config).** `slot_offset_min` spread across the hour and different
   `start_hour`s (moth 9-23, trader.joes 11-24, grip.tape 15-01 for the skate crowd); each page its own caption
   shape and first-comment wording; each page its own LOOK_W with no overlap (moth dusk/orchid, trader.joes
   rainbow/citrus, grip.tape meadow/lagoon + a new dark "asphalt" look, college a paper/cream look that reads like
   a notes app).
7. **Cadence (quick).** 5/day on 2-day-old Page-less accounts is the one thing every source agrees against. 2/day
   until an account has 14 days of metrics, then step to 3; keep `MIN_GAP` 60 min. Measure: median views per post
   week 1 vs week 2.
8. **Consolidate to two (or three) voices (quick, config; medium, banks).** Pause notes_date and notes_her, merge the
   best of their banks into lines.txt/college.txt as described in §7, keep grip.tape and moth as the two deep
   experiments. Add ~40 lines a week to the live banks (ids appended).
9. **Clean the banks (quick).** Remove or rewrite: d032, d050, d045, d004, d015, d040, d043; c003, c021, c024, c027,
   c045; h046-h070 as a block (move the clean ones); m093, m094, m102, m106 ("would you rather"), m045, m055; the
   caption "not a cry for help. a little bit". De-duplicate across banks (list in §10). Retire the 2022-23 slang
   lines (girl math, it's giving, roman empire, i'm literally so back, villain origin story, hits different).
10. **A notes-app look (medium, renderer).** One look that is literally a notes-app card (cream page, system-type,
    a timestamp line like "today 2:14 am", the handle as the note's title) would give moth.ate.my.notes the identity
    its handle promises and separate it visually from the others; knob `look: notes`. Measure against the gradients.
11. **Learner granularity (medium, learn.py/nightly).** Add a `kind` knob derived from the bank (song / friend /
    self / list / two-beat) so something about the *writing* can be learned even though each line is single-use;
    group `cut` into the two lengths that actually exist for this style.
12. **Trial reels (quick, accounts.yaml).** `trial_reels: true` on the two kept pages once insights work: the
    non-follower test is exactly what a faceless text page needs and `trial_graduation` is already configured.

## 10. Cross-bank duplicates (ratio > 0.6, difflib on normalised text)

- her#51 "my standards are high but my willpower at 1am is on the floor" = date#51 (0.78)
- her#62 "he said i'm not looking for anything serious bestie neither was i" = date#28 (0.70)
- lines#19 "i don't want a relationship i want someone to send me songs" = her#61 "...share fries with" (0.69)
- lines#2 / him#7 "my toxic trait is ..." (0.65); him#41 / college#40 / her#3 "i don't need a X i need someone to ..." (0.62-0.64)
- him#53 "walk of shame is just cardio with a story" = date#39 "bop era is just cardio with plot" = date#7 (0.59-0.62)
- her#50 / date#2 / him#47 "he/she said come over and i was already..." (0.59-0.62)
- her#8 / him#40 / him#76 "nothing humbles you like ..." (0.57-0.63; him#40 and him#76 are also a within-bank pair)
- lines#23 / him#13 / her#2 / date#29 / him#86 "my love language is ..." (0.55-0.61)
- lines#45 / him#11 / her#44 "i'm not ignoring you/the text i'm just ..." (0.57-0.62)

## 11. Risks (summary)

- Learner blind and nobody alarmed (§0): fix first.
- Recommendation-guideline exposure on notes_date, notes_college and half of notes_her (sexually suggestive); one
  line reads as a threat (d050).
- Four comment-ask cards in him.txt ("would you rather") and one self-harm-adjacent caption in notes_app.
- Synchronised templated posting from one network at 5/day on brand-new Page-less accounts; bank exhaustion leading
  to self-reposts in two to three weeks.
- No copyrighted footage, no band footage, no real people: clean on those rules.
