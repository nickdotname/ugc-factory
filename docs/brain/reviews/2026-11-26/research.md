# Research playbook: how music gets discovered through faceless niche Instagram pages (2025-2026)

Cluster: `research`. Written 2026-11-26. Album EDUCATION released 2026-11-13 (13 days ago).

Method and limits. Everything below came from web search (WebSearch, standard + extended). This cloud session cannot
open `help.instagram.com`, `creators.instagram.com`, `about.instagram.com`, `support.fuga.com` or
`developers.facebook.com` directly (hosts are outside the allowed network), so Meta's own wording is quoted as relayed
by search snippets and by secondary outlets that quote it. Where a primary URL is given, it is the page the claim
comes from; where only a secondary URL is given, treat the exact wording as unverified. Nothing in this file was
checked against the repo's own data; the reviewers do that.

Each section is split into three evidence tiers:

- **[META]** documented by Instagram / Meta (help center, creators blog, developer docs, newsroom, Mosseri on record).
- **[PRACT]** documented by credible practitioners (trade press such as Billboard / MBW, research houses such as
  Luminate / MIDiA, analytics vendors with a stated dataset, scheduler vendors' help centers describing observed
  API behaviour).
- **[FOLK]** folk wisdom / unverified (marketing blogs, SEO content, forum anecdotes, anything with no dataset or
  no primary source).

---

## 1. Instagram's own published ranking guidance for Reels, 2025-2026

### [META] documented by Instagram / Meta

**The three named signals (Jan 2025, repeated since).** In a January 2025 ranking video series Mosseri said the
signals that matter most for Reels ranking are **watch time, likes and sends**, and told creators to track
*average watch time, likes per reach and sends per reach* (ratios, not counts). Likes are "slightly more important"
for connected (follower) reach; sends are "slightly more important" for unconnected (non-follower) reach.
- https://www.socialmediatoday.com/news/instagram-shares-algorithm-2025/738034/
- https://t3n.de/news/reels-instagram-bewerten-mosseri-1744320/ (Mosseri AMA clip: rates matter more than counts;
  sends per reach correlate more with overall reach than anything else)
- Tracker that separates Mosseri's wording from blog inflation: https://keywordseverywhere.com/news/instagram-algorithm-updates/
  (notes the widely repeated "sends weigh 3-5x likes" is NOT Mosseri's wording; he said "slightly more important").

**Watch time is both relative and absolute.** Secondary summaries of the same series say the ranker weighs the
share of the video watched and the seconds watched.
- https://www.fanpagekarma.com/insights/instagram-reels-algorithm/

**Views became the primary metric (Aug 2024).** Instagram replaced "Plays" with "Views" across Reels, photos,
carousels and Stories. This is an analytics/reporting change, not a stated ranking input.
- https://socialmediatoday.com/news/instagram-updates-metrics-to-focus-creators-on-views/723645/
- https://petapixel.com/2024/08/08/reels-stories-carousels-likes-followers-instagram-will-now-focus-on-views-in-metrics-for-photos

**The 2023 "Instagram Ranking Explained" post** (Mosseri, 31 May 2023, still the canonical explainer) describes
Reels inputs as: your activity (reels liked, saved, reshared, commented on), information about the reel
("signals about the content within the video, such as the audio track or visuals, as well as popularity"), and
information about the poster. It also states watermarked / low-resolution / muted / bordered / mostly-text reels get
less reach.
- https://about.instagram.com/blog/announcements/instagram-ranking-explained
- Coverage: https://www.socialmediatoday.com/news/instagram-shares-new-explainer-on-how-its-feed-reels-and-stories-algorithm/651705/
- The 2021 predecessor listed the Reels predictions as "how likely you are to watch a reel all the way through,
  like it, say it was entertaining or funny, and go to the audio page" (the audio-page prediction is relevant to music
  pages; it has not been restated since 2023). https://about.instagram.com/blog/announcements/shedding-more-light-on-how-instagram-works

**How recommendation testing works, in Instagram's words.** The creators-site originality page says eligible
content (original, no visible watermark, meets Recommendation Guidelines) "is shown to a small audience that
Instagram thinks will be interested" and expands from there.
- https://creators.instagram.com/recommendations-and-originality (relayed via
  https://marketing4ecommerce.net/en/instagram-changes-its-algorithm-and-will-stop-recommending-duplicated-content/)

**Trial reels (Dec 2024; widened 2025).** Shown to non-followers first; not on the follower feed or grid (they can
still surface via DM shares and on audio/location/filter pages); insights after ~24h; can auto-share to followers
after 72h if opted in. Expanded in 2025 to all public accounts with 1,000+ followers (reports of 200+ for
professional accounts). Cap reported as 20 trial reels/day.
- https://creators.instagram.com/blog/instagram-trial-reels
- https://about.fb.com/news/2024/12/trial-reels-try-content-non-followers/
- https://techcrunch.com/2024/12/10/instagram-rolls-out-trial-reels-that-arent-shown-to-a-creators-followers
- https://socialmediatoday.com/news/instagram-expands-access-trial-reels/752895/
- https://socialmediatoday.com/news/instagram-trial-reels-increase-reach-tests/750121/ (20/day; Instagram quote that
  80% of creators who posted more often saw non-follower reach rise, Instagram's own number)

**Reels length.** Cap raised from 90 s to 3 min in Jan 2025; Instagram had been saying (through early Jan 2025)
that reels under 90 s perform better. Reels over 3 min "won't be recommended to new audiences" (in-app warning).
- https://www.socialmediatoday.com/news/instagram-officially-expands-reels-length-to-3-minutes/737766/
- https://buffer.com/resources/instagram-reels-length (2.7M-reel dataset; quotes the in-app warning)

**Originality / aggregator policies.**
- 2021: Reels with TikTok watermarks and "visibly recycled" content made less discoverable.
  https://tubefilter.com/2021/02/10/instagram-reels-with-tiktok-watermark-less-discoverable/
- 2024: Instagram starts replacing reposted reels with the original in recommendations and labelling reposts with a
  link to the original creator; aggregators that mostly repost become ineligible for recommendations, regain
  eligibility after 30 days of mostly-original posting.
  https://creators.instagram.com/blog/rewarding-original-creators-on-instagram
  https://www.socialmediatoday.com/news/instagram-algorithm-prioritize-original-emerging-creators/714777/
- Jul 2025 (Facebook side): "Combating unoriginal content": repeat reposters lose monetization for a period and get
  reduced distribution; duplicates shown to fewer people; "low-value edits" (borders, captions, watermarks) don't
  count as original. https://creators.facebook.com/blog/combating-unoriginal-content
  https://techcrunch.com/2025/07/14/following-youtube-meta-announces-crackdown-on-unoriginal-facebook-content
- Apr 30 2026: Instagram extends the aggregator rule from Reels to photos and carousels, platform-wide. "When we find
  two or more identical pieces of content on Instagram, we will only recommend the original one." Edited third-party
  material ("materially edited", adds an element that "enhances the content") still counts as original.
  https://creators.instagram.com/recommendations-and-originality
  https://techcrunch.com/2026/04/30/instagram-restricts-reach-of-content-aggregators-in-new-crackdown/
  https://tubefilter.com/2026/04/30/instagram-removes-algorithm-recommendations-repost-content-aggregator
  https://engadget.com/2160560/instagrams-recommendation-algorithm-will-penalize-unoriginal-photo-and-carousel-posts

**Recommendation Guidelines (help center).** Reels that are "muted, blurry, or low-resolution", carry "borders, logos
or watermarks", or are "not the creator's own original videos" are recommended less; content that breaks the
guidelines still reaches followers. Repeated violations can make the whole account ineligible for recommendation for
a period. Account Status shows this.
- https://help.instagram.com/313829416281232
- https://creators.instagram.com/blog/instagram-recommendations-eligibility-tips-creators
- https://help.instagram.com/613868662393739 (why posts don't appear in Explore/search)

**Hashtags.** Mosseri said in Feb and May 2025 that hashtags do not increase reach (they help describe the post);
Instagram capped hashtags at 5 per post from Dec 2025.
- https://www.socialmediatoday.com/news/threads-hides-hashtags-on-cross-posts-instagram/761552/
- https://keywordseverywhere.com/news/instagram-algorithm-updates/

**Posting frequency.** Mosseri's 2025 answer: no single right number; some succeed posting monthly, some posting
five reels a day; more posts generally means more reach, with burnout the cost.
- https://routenote.com/blog/how-often-you-should-post-on-instagram/
- https://www.inman.com/2025/03/07/head-of-instagram-reveals-secrets-to-social-media-success/ (carousels get a
  "second chance" if not swiped; sends favoured)

**Reposts feature (Aug 2025).** Public reels and feed posts can be reposted; reposts are recommended to the
reposter's friends/followers and sit in a Reposts tab. Relevant as a legitimate cross-account amplification path
(the band account reposting a niche page's reel) that does not create a duplicate upload.
- https://about.fb.com/news/2025/08/new-instagram-features/
- https://petapixel.com/2025/08/06/instagram-adds-a-reposts-tab-to-users-profiles-similar-to-tiktok/

**"Your Algorithm" controls (Dec 2025)** let viewers edit the interests Reels ranks on; no stated creator impact.
- https://keywordseverywhere.com/news/instagram-algorithm-updates/

**AI-generated content labelling.**
- "AI info" label (renamed from "Made with AI" in 2024 after false positives) is applied per post when C2PA/SynthID
  signals or self-disclosure are present; Instagram says it does not reduce recommendations.
  https://workos.com/blog/instagram-ai-generated-profile-label
- Mosseri, weekly Q&A: "We do not throttle the reach of AI content just for being AI content."
  https://socialmediatoday.com/news/instagram-chief-says-stronger-ai-slop-prevention-is-needed/833416
- May 2026: voluntary "AI creator" profile label tested; ranking unchanged during the test.
  https://hypebeast.com/2026/5/instagram-tests-voluntary-ai-creator-label-on-profiles
  https://www.socialmediatoday.com/news/instagram-adds-ai-creator-labels/819267/
- Aug 31 2026: renamed "AI-generated profile"; accounts whose *persona* is AI and who skip the label become
  non-recommendable (Reels/Explore) until labelled or appealed. Using AI to edit, generate graphics or polish captions
  does NOT require the label. Procedurally generated / rendered visuals set to a real band's music are not an
  "AI persona" and are not covered.
  https://techcrunch.com/2026/08/31/instagram-puts-new-limits-on-undisclosed-ai-profiles/
  https://engadget.com/2246914/instagram-will-demote-ai-generated-influencers-if-they-dont-clearly-label-their-account/
- Mosseri's year-end Threads essay: AI has "shattered the visual trust", Instagram will label AI content more clearly
  and show more account context. https://www.engadget.com/social-media/instagram-chief-ai-is-so-ubiquitous-it-will-be-more-practical-to-fingerprint-real-media-than-fake-media-202620080.html

**Meta Content Distribution Guidelines (apply to Facebook and Instagram).** Engagement bait (asking for votes,
shares, comments, tags, likes) and watchbait (withholding information, sensationalising, misleading viewers into
watching) get reduced distribution; repeat watchbait reduces a Page's overall distribution. Note Meta REMOVED the
"Low Quality Videos" and "Pages Posting Unoriginal Videos" guidelines in 3/2024 and removed fourteen more guidelines
in 7/2025; the unoriginal-content rules now live in the creators-blog policies above, not in the CDGs.
- https://transparency.meta.com/features/approach-to-ranking/content-distribution-guidelines/engagement-bait/
- https://transparency.meta.com/features/approach-to-ranking/cdgs-changes-corrections/
- https://transparency.meta.com/enforcement/taking-action/lowering-distribution-of-problematic-content/
- https://www.mediapost.com/publications/article/372470/meta-warns-against-using-watchbait.html

### [PRACT] credible practitioners
- Buffer (2.7M reels): 90 s-3 min reels got the most reach and engagement in their sample; >3 min not recommended.
  https://buffer.com/resources/instagram-reels-length
- Kapwing trial-reel study: trial reels usually yield higher reach but not more engagement or conversions.
  https://www.kapwing.com/resources/instagram-trial-reels-study-what-we-learned-after-a-trial-reel-hit-1-million-views/

### [FOLK] folk wisdom / unverified
- "Sends are weighted 3-5x likes", "October 2026 comment-ranking statement", dated monthly "algorithm updates"
  (SocialPilot, Sprout, Pulse Advertising 2026 pieces conflict with each other). Not Mosseri's words.
  https://keywordseverywhere.com/news/instagram-algorithm-updates/ (debunks)
- "Reels with trending audio get 38% more reach" (no named study). https://www.octupie.com/blog/trending-audio-instagram-reels

---

## 2. How independent artists actually spread songs via sound pages / faceless networks, 2024-2026

### [META] documented
- Instagram's own framing is that the song's **audio page** (tap the audio name on a reel) is the discovery hub, and
  that any public account's original audio can be reused by anyone ("When you post a reel on a public account, anyone
  on Instagram can record a reel using your original audio"). https://help.instagram.com/iphone-app/329208821595430
- Trial reels can appear on audio pages even though they are hidden from followers.
  https://creators.instagram.com/blog/instagram-trial-reels

### [PRACT] credible practitioners
**Billboard, Aug 2025: "Burner Pages and Volume Posting: Inside Music's Hottest New TikTok Marketing Strategy".**
Labels, managers and firms (Chaotic Good, Floodify; Warner Records in-house under SVP viral marketing Will Morrow,
since ~2023) run "hundreds or thousands" of small, newly created or anonymous TikTok pages whose job is to put a song
in the background of posts. Pages are themed (meme pages, country/trucks/ATV pages, sports clips, love quotes, fan
pages that pose as ordinary fans reposting concert footage). Also called flooding, seeding, volume posting, "trend
simulation" (Chaotic Good's term). Two managers were quoted ~$5,000 per song, firms promising a view target. The
tactic rose because top-creator fees climbed and trends fragmented. Billboard did not publish posts/day per page.
- https://www.billboard.com/pro/music-hottest-tiktok-marketing-strategy-burner-pages-volume/
- https://www.billboard.com/wp-content/uploads/2025/08/august-20-2025-billboard-bulletin.pdf
- https://www.billboard-japan.com/d_news/detail/152890/2 (Japanese translation with the $5k quotes)
- https://www.billboard.com/music/features/music-marketing-on-tiktok-not-working-2024-1235857662/ (2024: why
  influencer-led TikTok marketing stopped working, context for the shift to volume)
- Secondary explainers of the same tactic: https://www.unhurdmusic.com/blog/tiktok-burner-accounts-for-musicians ,
  https://www.makeinfluence.com/en/academy/how-record-labels-use-tiktok-sound-seeding-to-launch-a-song ,
  https://dynamoi.com/learn/tiktok-music-promotion (notes TikTok periodically purges inauthentic accounts)

What this means for an Instagram engine: the documented playbook is TikTok-first; the Instagram equivalent
("edit pages", "theme pages", seeding on niche pages) exists as a paid service but no trade-press case study with
numbers was found. Artist Influence sells placement on "edit, fan and culture" niche Instagram pages:
https://www.artistinfluence.com/services/instagram-seeding (vendor claim, no results published).

**Pay-per-view "clipping" (2025-2026).** Marketplaces (Clipster, Content Rewards/Whop, ClippingCulture, Lumina)
pay creators $0.15-$3.00 per 1,000 validated views to post clips with a song; music campaigns start around
$1,000-$2,000. Vendor-reported results only (one claims 190K Spotify streams for <$1,000; another median $0.36 CPM
across 94 campaigns). No independent verification of stream lift.
- https://www.clipster.com/music , https://contentrewards.com/articles/how-to-promote-a-song-on-tiktok ,
  https://nysos.io/en/campagnes-clipping , https://luminaclippers.com/blog/clipping-vs-influencer-marketing-vs-ugc

**Virality does not equal fandom (MIDiA, 16 Sep 2025, 10,000 consumers).** The assumed funnel
virality -> streams -> fandom breaks down; under a quarter of TikTok users have engaged with artists' pre-release
teasers; song discovery translates less into artist discovery for 16-24s. Implication: the audio tag / first-comment
credit has to carry the artist name, not just the song, and the band account must be the obvious next tap.
- https://www.midiaresearch.com/blog/all-eyes-no-ears-new-midia-data-shows-why-virality-is-not-building-fandom
- https://www.midiaresearch.com/reports/all-eyes-no-ears-why-virality-is-not-building-fandom (free report)

**Discovery share of short-form video (Luminate).** 36% of weekly US rock listeners discovered music via short-form
video in 2025 (+20% y/y); 53% of 18-24s discover via short-form social video, on par with streaming services (55%).
Meta-commissioned Luminate study (Apr 2026) places Instagram second to YouTube (83%) for superfan engagement and
claims "strong evidence" Instagram programs drive off-platform streaming (commissioned, treat accordingly).
- https://theideafarm.com/markets/annual-reports/luminate-releases-2025-year-end-music-report/
- https://www.emarketer.com/content/social-video-beats-tv-advertising-entertainment-discovery-among-young-adults
- https://www.musicbusinessworldwide.com/files/2026/04/Meta-IG-Music-Impact-Report-FINAL.pdf
- https://www.tubefilter.com/2026/04/01/meta-instagram-music-fan-study-luminate-data/

**Crediting the song: audio tag vs text.** No study compares the two. What is documented: the audio tag is the
only path to the audio page and to "Use audio"; a text/caption credit is searchable (Mosseri: caption keywords
matter more than hashtags) but not tappable. Practitioner consensus (sound-page guides) is that the audio page count
is the metric to watch weekly. https://musicpromotoday.com/blog/instagram-algorithm-music-budget-wasted ,
https://playlist-promotion.com/instagram-music-promotion/ (both marketing sites, no data).

**Does an Instagram audio page exist for original audio uploaded via the API?** Yes, by vendor observation: when
Instagram does not recognise an uploaded track it creates a new "Original audio - @username" entry and the reel
lives on that page; a reel can take 10-20 minutes to appear on its audio page; the page name can be set once via
the API (`audio_name`) or later from the audio page. See section 3 for sources.

### [FOLK] folk wisdom / unverified
- "A song with 800 artist-page followers and 40 creator reels will beat a 50K-follower page posting into the void"
  (no data). https://musicpromotoday.com/blog/instagram-algorithm-music-budget-wasted
- Posting cadence of burner networks ("3-10 posts/day per page") appears only in vendor blogs, not in Billboard.
- Anecdotal breakouts via Reels in 2025 (Isha Malviya "Shaky", 350M+ views, #1 Billboard India) show Reels can
  break a song but give no account-level playbook. https://en.wikipedia.org/wiki/Shaky_(song)

---

## 3. Technical: audio tags, original audio, ISRC matching, distributor delivery

### [META] documented
**Content Publishing API, Reels container parameters.** `audio_name` (optional) renames the default "Original
Audio" for original audio the user owns (added Jun 2023). Reading a media object returns `media_audio_type` =
`MUSIC` or `ORIGINAL_SOUND`.
- https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/media
- https://developers.facebook.com/blog/post/2023/06/12/introducing-new-features-and-expanded-user-types-to-the-instagram-content-publishing-api/
- https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media.md

**Instagram Audio API (attach licensed or original audio at publish time).** Search `/audio` (returns `audio_id`,
`audio_type` music|original_sound, title, duration_in_ms, preview URL; trending when no query), then pass
`audio_configuration` with the `audio_id` on the media container. Requires Facebook Login (not Instagram Login),
`instagram_basic` + `instagram_content_publish`. Reels with attached audio cannot be previewed via API.
- https://developers.facebook.com/docs/instagram-platform/content-publishing/audio-api/
So: **a Reel published through the Graph API CAN carry a licensed music tag**, provided the track is in Instagram's
library and the account type is allowed to use it (see the business-account caveat below).

**Automatic re-attribution of baked-in audio.** Help center: "When we detect the audio you recorded or uploaded
uses licensed audio, we'll automatically change attribution from Original Audio to the artist and song title"; the
reel is then listed on the song's audio page; a wrong match can be removed with "Remove From Audio Page".
- https://help.instagram.com/iphone-app/329208821595430
Instagram's spoken caveat for a *pre-release* reel: if you upload licensed audio as original audio the description
may change to the artist's name and song.

**Business accounts and the music library.** In the app, Business accounts see Meta's royalty-free Sound Collection
(14,000+ tracks, cleared for commercial use), not the full licensed catalogue; Creator and personal accounts see the
full library. The Audio API docs do not say whether a Business IG user can attach `audio_type=music`; test it on one
account rather than assume.
- https://help.instagram.com/ipad-app/402084904469945 (Sound Collection)
- https://www.soundstripe.com/blogs/instagram-music-library , https://manychat.com/blog/how-to-use-trendy-songs-with-an-instagram-business-account
- https://musicbusinessworldwide.com/meta-offers-royalty-free-music-library-to-instagram-reels-advertisers

**DDEX / ISRC.** Meta's Music Rights Manager DDEX docs require an ISRC in `SoundRecordingId` for every sound
recording delivered. https://developers.secure.facebook.com/docs/music-rights-manager/ddex-documentation/

**Content Publishing rate limit.** Meta's guide now says 100 API-published posts per rolling 24 h per IG account
(carousel = 1), enforced at `media_publish`; `GET /{ig-user-id}/content_publishing_limit` reports usage. Older
sentences in the same doc family still say 50; the 2021 launch figure was 25. The docs do not say whether Reels and
Stories count; query the endpoint on each account.
- https://developers.facebook.com/docs/instagram-platform/content-publishing/
- https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/content_publishing_limit
- https://developers.facebook.com/blog/post/2021/01/26/introducing-instagram-content-publishing-api/ (25 in 2021)
- Third-party notes on the 50/100 conflict: https://bundle.social/blog/instagram-api-rate-limits ,
  https://adaptlypost.com/blog/instagram-api-100-posts-per-24-hours-limit , https://www.blotato.com/blog/instagram-posting-api

**Graph API call limits.** Instagram Graph API uses Business Use Case limits reported in
`X-Business-Use-Case-Usage`; the commonly cited 200 calls/hour is per app-user pair (per connected account), so
many accounts on one app each get their own budget. https://developers.facebook.com/docs/graph-api/overview/rate-limiting/

### [PRACT] credible practitioners (scheduler vendors observing API behaviour)
- **Original-audio page from an API-published reel**: "when Instagram doesn't recognise the uploaded track it creates
  a new 'Original audio - @username' entry"; recognised tracks link to the existing song page.
  https://help.skedsocial.com/how-audio-selection-works-on-instagram-reels-when-you-upload-a-video-edited-on-desktop-or-inside-sked
- Reel appears on the audio page 10-20 min after publish; Audio API needs Facebook Login.
  https://support.sproutsocial.com/hc/en-us/articles/47805679724429-Adding-Trending-Audio-to-Instagram-Reels
- Default name is "Original Audio"; can be renamed once via `audioName` or from the audio page.
  https://www.ayrshare.com/blog/the-instagram-api-just-went-to-11.md
- Agorapulse, Later, Publer, Metricool document the same attach-audio flow.
  https://support.agorapulse.com/en/articles/16020547-how-to-add-audio-to-instagram-reels ,
  https://help.later.com/hc/en-us/articles/42098148094871-Add-Audio-to-Instagram-Reels
- **Pre-release -> licensed attribution workflow (FUGA, distributor docs).** Artist posts the reel with the track as
  Original Audio, renames it "<Title> - Pre-Release" (one rename only); after the release is delivered to Meta,
  "Instagram will typically attempt to attribute the Reel to the official licensed audio automatically"; FUGA
  tracks Original Audio/Reel URL, ISRC, territory rights and timestamp; on success, tapping the audio on the original
  reel redirects to the licensed Music Library page.
  https://support.fuga.com/hc/en-us/articles/48757500160916-Managing-Meta-Pre-Release-Campaigns-in-the-FUGA-Platform
  https://support.fuga.com/hc/en-us/articles/39647807419284-Meta-Delivery-Guide-Resolving-Missing-Audio-Tracks-on-Instagram-or-Facebook
- **Distributor delivery times to Meta.**
  CD Baby (official): tracks appear in Instagram's picker only after delivery; opt in to Facebook/Instagram
  monetization; "allow at least 30 days"; covers and public-domain recordings are NOT delivered.
  https://support.cdbaby.com/hc/en-us/articles/360029734272 , https://diymusician.cdbaby.com/releasing-music/instagram-reels-music/
  TuneCore (official): delivers to Facebook/Instagram once approved; release can be held by the latest delivery date
  on the ISRC. https://www.tunecore.com/get-your-music-on-meta , https://support.tunecore.com/hc/en-us/articles/360001099886
  DistroKid: no official window found; third parties report DistroKid/TuneCore say 1-2 weeks, others 5-14 days or
  1-3 weeks, with Friday manual reviews slipping to Monday.
  https://www.soundverse.ai/blog/article/what-are-music-distribution-turnaround-times ,
  https://jackrighteous.com/blogs/ai-music-distribution-guide/distrokid-delivered-but-not-live ,
  https://promusicianhub.com/how-long-distrokid-upload-platforms
  LabelGrid: if ANY track on a release is ineligible, the whole release is absent from Instagram/Facebook.
  https://help.labelgrid.com/en/platforms/meta/
  Identity Music: wait 30 days before escalating; eligibility is Meta's call.
  https://identitymusic.com/blog/why-isnt-my-music-on-instagram-meta
- Meta pays music-library royalties by **number of videos using the track, not views** (Too Lost help; relayed).
  https://help.toolost.com/hc/en-us/articles/4412265577108 , https://tellingbeatzz.com/instagram-reels-monetization-music/
- Rights Manager for music: independents go through a distributor; direct application needs a Facebook Page and
  review; AI-assisted and library music are eligible, public domain and indistinct loops are not.
  https://routenote.com/radar/how-to-monetise-music-on-facebook-meta-and-instagram/ ,
  https://support.fuga.com/hc/en-us/articles/39096225095828

**Timing for EDUCATION (released 2026-11-13, 13 days ago).** By the 1-2 week estimates the tracks should be landing
in Instagram's library about now; by CD Baby's rule, allow until ~2026-12-13. Check: open Reels > Add music on a
Creator/personal account and search "Close Quarters"; and read `media_audio_type` on recent API-published reels to
see whether any baked-in audio has flipped from ORIGINAL_SOUND to MUSIC. Nothing documents how long after library
arrival the fingerprint re-attribution of *already published* reels happens; FUGA says "typically" automatic.

### [FOLK] folk wisdom / unverified
- "Switch a Business account to Creator to unlock the full music library via API" (works in-app; API not verified).
- "Meta can fingerprint your recording even when nobody selected it from the library" (RouteNote, plausible and
  consistent with the help-center sentence, but no Meta statement on recall rate or delay).
  https://routenote.com/radar/how-to-monetise-music-on-facebook-meta-and-instagram/
- "This reel contains your music" notification wording: not found in any source.

---

## 4. Benchmarks for a new faceless Reels account, weeks 1-4

### [META] documented
- Instagram publishes no numeric benchmarks. Documented mechanics: eligible content is first shown to a small
  interested audience, then expanded (section 1); trial reels report insights after ~24 h; Instagram's own claim that
  80% of creators who posted more trial reels saw non-follower reach rise.
  https://creators.instagram.com/recommendations-and-originality , https://socialmediatoday.com/news/instagram-trial-reels-increase-reach-tests/750121/

### [PRACT] credible practitioners (datasets exist, but none is new-account specific)
- Socialinsider 2026 benchmarks: Reels **skip rate** (viewers leaving in the first 3 s) 60.5%-65.5% across account
  sizes, i.e. a 3-second hold of ~35-40% is average; Reels engagement ~0.48-0.52%; Reels lead on reach for accounts
  under 50K followers. https://www.socialinsider.io/social-media-benchmarks/instagram
- Metricool (relayed): average Reel watch time ~8.5 s, roughly doubled y/y.
  https://www.upgrow.com/blog/instagram-reels-statistics-2026-views-watch-time-reach-engagement
- Non-follower share of Reels reach: 40-80% for 0-10K-follower accounts, 60-90% above 100K (StartMotionMedia,
  mid-2024 ranges); a tool vendor's target is >40%.
  https://www.startmotionmedia.com/2025/08/11/instagrambenchmarks-keyinsights/ , https://retensis.com/blog/how-to-reach-non-followers-on-instagram
- Buffer: Reels get ~36% more reach than carousels; carousels ~12% more engagement.
  https://buffer.com/resources/instagram-news-feed-algorithm/
- Kapwing: a trial reel reaching 1M views brought reach, not proportional followers.
  https://www.kapwing.com/resources/instagram-trial-reels-study-what-we-learned-after-a-trial-reel-hit-1-million-views/
- One self-reported 2025 faceless case (Stan Store): 0 -> ~15K followers in 30 days; week 1 = 2,000 followers and
  125K views with one near-100K reel; five trial reels at ~2K views each. Operator-reported.
  https://stan.store/blog/creator-strategies-case-study/

### [FOLK] folk wisdom / unverified (but the only "week 1" numbers in circulation)
- First reels on a zero-audience account: 50-500 views, mostly feed/Reels-tab sampling.
  https://360uniquizer.com/en/news/instagram-reels-no-views-new-account
- "Good" 3-second hold: 60-70%+; strong reels 78-88% in one vendor's tests; average watch time >50% of duration;
  for <30 s reels, retention at the midpoint predicts reach better than average watch time.
  https://creatorlanehq.com/blog/the-second-line-why-reels-die-at-three-seconds-2026 ,
  https://smmnut.com/blog/hook-style-affects-watch-time/ , https://virvid.ai/blog/instagram-reels-algorithm-explained-get-1m-views-2026
- "Healthy" first-3-second skip of 20-30% for new accounts. https://www.truefuturemedia.com/articles/instagram-reels-reach-2026-business-growth-guide
- "55% of Reel views come from non-followers" is repeated everywhere with no primary source.
- No source gives shares-per-reach or saves-per-reach norms; Mosseri only says to watch the ratio. A workable
  internal rule is to rank the engine's own posts by sends/reach and watch-time share against their own medians (the
  baseline file does this) rather than against any published number.

---

## 5. Formats currently over-performing for background-music discovery

### [META] documented
- Instagram does not publish format-level performance. The only format guidance on record: avoid muted, bordered,
  "mostly text" reels (2023 explainer); reels up to 3 min are recommendable; ASMR-style and vintage/nostalgia aesthetics
  appear in Instagram's trend coverage only via third parties. Audio-page visits were a stated Reels prediction in
  2021 and have not been restated.
  https://about.instagram.com/blog/announcements/instagram-ranking-explained ,
  https://about.instagram.com/blog/announcements/shedding-more-light-on-how-instagram-works

### [PRACT] credible practitioners
- Billboard's burner-page reporting names the themes labels actually run: meme pages, trucks/ATV, sports clips, love
  quotes, fan pages. All are "background music" formats where the song is not the subject.
  https://www.billboard.com/pro/music-hottest-tiktok-marketing-strategy-burner-pages-volume/
- Trend trackers (weekly, vendor-run): ASMR/satisfying close-ups (textures, pours, hands-on work) are a 2025-2026
  Reels staple; vintage/VHS/90s nostalgia edits returning in 2026; "Lately on my SD card" camera-roll dumps; format
  trends last 3-4 weeks before saturation, longer than audio trends.
  https://24fingers.co.uk/instagram-reels-trends-october-2025/ , https://napoleoncat.com/blog/instagram-reels-trends/ ,
  https://newengen.com/insights/instagram-trends/ , https://planable.io/blog/instagram-reels-trends/
- Hook-and-payoff structures raise completion (CreatorScope). https://www.creatorscope.io/blog/best-instagram-reels-content-formats-to-grow-in-2025-7

### [FOLK] folk wisdom / unverified
- No source anywhere measures which formats drive **audio taps** versus views. The closest is the music-marketing
  heuristic that the audio page count, not views, is the metric to watch
  (https://musicpromotoday.com/blog/instagram-algorithm-music-budget-wasted).
- "Watch till the end" framing sits on the edge of Meta's **watchbait** definition (withholding information to
  make people watch); it is documented as reducing distribution on Facebook Pages and the CDGs apply to Instagram.
  Treat it as a risk, not a format. https://transparency.meta.com/enforcement/taking-action/lowering-distribution-of-problematic-content/
- Math/physics visualisations, ASCII/code art and optical illusions: no coverage at all in 2025-2026 trend
  reporting. Archival/public-domain film: only as part of "nostalgia aesthetic" coverage.

---

## 6. Risks

### [META] documented
- **Duplicate content.** "When we find two or more identical pieces of content on Instagram, we will only recommend
  the original one." Low-value edits (borders, captions, credits, watermarks) do not make a copy original. Instagram
  has not said whether same-owner copies are exempt; assume they are not. Posting one rendered video to several
  niche accounts therefore leaves all but one copy recommendable only to followers. Distinct renders per account
  (different footage/knobs/text) are the documented way to stay "materially edited".
  https://creators.instagram.com/recommendations-and-originality , https://creators.facebook.com/blog/combating-unoriginal-content
- **Aggregator ineligibility** is account-level and lasts until 30 days of mostly-original posting; appeal via Account
  Status. https://creators.instagram.com/blog/rewarding-original-creators-on-instagram
- **Recommendation Guidelines** penalties for watermarks, borders, low resolution, muted video; repeat violations make
  the account non-recommendable for a period. https://help.instagram.com/313829416281232
- **Engagement bait / watchbait** reduce distribution (already banned by CLAUDE.md rules).
  https://transparency.meta.com/features/approach-to-ranking/content-distribution-guidelines/engagement-bait/
- **Inauthentic Behaviour** (Community Standards): "a network of inauthentic assets controlled by the same individual
  or individuals" used for deception is removed outright. Openly operated themed pages are not fake accounts, but
  pages posing as independent fans (Billboard's "fan pages that pose as ordinary fans") sit close to this line.
  https://transparency.meta.com/en-gb/policies/community-standards/inauthentic-behavior/
- **Unlabelled AI persona** profiles become non-recommendable (Aug 2026); AI-assisted visuals without a synthetic
  "person" are not covered. https://techcrunch.com/2026/08/31/instagram-puts-new-limits-on-undisclosed-ai-profiles/
- **API publishing cap** 100 (or 50, docs conflict) posts per IG account per rolling 24 h; `content_publishing_limit`
  endpoint is authoritative per account. Multiple IG accounts on one Meta app is the normal, documented pattern
  (Business Manager / Facebook Login with Pages); each account has its own BUC budget. No Meta statement says one
  app or token across accounts is itself a risk.
  https://developers.facebook.com/docs/instagram-platform/content-publishing/ , https://developers.facebook.com/docs/graph-api/overview/rate-limiting/
- Reels >3 min are not recommended to non-followers (in-app warning). https://buffer.com/resources/instagram-reels-length
- Hashtag cap 5/post (Dec 2025). https://keywordseverywhere.com/news/instagram-algorithm-updates/

### [PRACT] credible practitioners
- Meta reported ~10M impersonator accounts removed and action against ~500K spam/fake-engagement accounts in H1 2025.
  https://influencermarketinghub.com/facebook-push-against-unoriginal-content/ , https://www.foxnews.com/tech/meta-deletes-10-million-facebook-accounts-year-why.amp
- Scheduler vendors' consistent observation: a reel's audio is either matched to a library track or becomes a new
  Original Audio; nothing suggests API publishing itself suppresses reach (Sked, Sprout, Later, Ayrshare, above).
- TikTok periodically purges inauthentic burner networks (Dynamo). https://dynamoi.com/learn/tiktok-music-promotion

### [FOLK] folk wisdom / unverified
- "One suspension cascades to every Meta asset sharing Business Manager / device / IP" (anecdotal, vendor blogs).
  https://www.lilachbullock.com/why-instagram-keeps-banning-business-accounts/ , https://dev.to/yashddesai/meta-business-account-ban-analysis-2026-lal ,
  https://www.socialpilot.co/blog/why-meta-flagged-your-agency-logins
- "Meta scores overall trust, not single triggers; ManyChat/API users banned in 2025 waves" (opinion pieces, forum
  threads). https://community.manychat.com/general-q-a-43/instagram-business-account-disabled-due-to-automation-10161
- "Content with AI slop is throttled" is contradicted by Mosseri on record (section 1).

---

## Summary (15 lines)

1. Mosseri's on-record Reels signals since Jan 2025 are watch time (relative and absolute), likes per reach and sends per reach; sends matter slightly more for non-follower reach. Nothing else is confirmed; "3-5x" weights and dated monthly "updates" are blog inventions.
2. Instagram says eligible content is first shown to a small interested audience and expanded; trial reels (1,000+ followers, 20/day) are the sanctioned way to test with non-followers and still land on audio pages.
3. Originality is now the dominant policy: identical content is collapsed to one recommendable copy (Apr 2026, platform-wide), low-value edits don't count, aggregator accounts lose recommendations until 30 clean days. Same-owner duplicates are not exempted anywhere in Meta's text.
4. Recommendation Guidelines still demote watermarks, borders, low resolution, muted and "mostly text" reels; engagement bait and watchbait reduce distribution; reels over 3 minutes are follower-only.
5. AI-generated visuals are not throttled "for being AI" (Mosseri); only unlabelled AI *persona* profiles lost reach in Aug 2026. Rendered sims and archival footage set to real music are outside that rule.
6. The documented industry playbook for background-music discovery is TikTok "burner/volume posting" (Billboard, Aug 2025): hundreds-to-thousands of themed anonymous pages, ~$5K/song, meme/trucks/sports/love-quote themes. No Instagram-specific case study with numbers exists in trade press.
7. MIDiA (Sep 2025) shows virality rarely converts to fandom; Luminate shows short-form video is now the top discovery channel for under-25s. Credit must name the artist and route to the band account, not just the song.
8. A Reel published through the Graph API can carry a licensed music tag via the Audio API (`audio_configuration` + `audio_id`, Facebook Login required) and can rename its original audio once (`audio_name`); unrecognised baked-in audio becomes "Original audio - @username" with its own tappable page.
9. Instagram's help center says baked-in licensed audio is auto-re-attributed to artist + title and listed on the song page; FUGA documents this working for pre-release reels after delivery. No Meta statement on delay or recall rate.
10. Distributor delivery to Meta: DistroKid/TuneCore ~1-2 weeks (third-party), CD Baby says allow 30 days; EDUCATION (13 days out) should be arriving in the library now. Verify in the music picker and via `media_audio_type` on recent reels before assuming tags.
11. Business accounts only see Sound Collection in-app; whether a Business IG user can attach `audio_type=music` via API is undocumented. Test on one account.
12. No published benchmarks exist for a new faceless account. Datasets that do exist: 3-second skip 60-65% (Socialinsider), ~8.5 s average watch (Metricool), 40-80% non-follower reach for small accounts, Reels engagement ~0.5%. Judge posts against the engine's own medians for sends/reach and watch share.
13. No source measures which formats drive audio taps rather than views; ASMR/satisfying, nostalgia/VHS and hook-payoff structures are the formats trackers report over-performing in 2025-2026; math, ASCII and illusion formats are unreported.
14. API publishing cap is 100 (docs also say 50) posts per account per 24 h, checked per account at `content_publishing_limit`; many accounts on one app is the documented norm, each with its own call budget. No Meta text says shared tokens are a risk; cascading-ban claims are anecdotal.
15. Biggest documented exposure for this engine: identical renders posted to several accounts (duplicate collapse), "watch till the end" framing (watchbait), and accounts that read as fake fans (Inauthentic Behaviour). Distinct renders per account, honest page identities and artist-named credits are the documented mitigations.
