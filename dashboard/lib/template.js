// The files a new campaign starts with.
import { yamlString } from "./yamledit.js";

export function slugify(name) {
  const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 40);
  return /^[a-z]/.test(slug) ? slug : `c_${slug}`.replace(/_+$/, "");
}

const POST_TYPE = { instagram: "reel", tiktok: "post", youtube: "short" };

/**
 * kind: "music" (the song is the content: clips silent, track loud) or
 *       "talk"  (clips carry a voice; music is a quiet bed underneath)
 * primary: one account from accounts.yaml — the campaign's nominal channel.
 * accounts: account names to post to; empty = every account.
 */
export function campaignFiles({ slug, kind, title, link, timezone, postsPerDay, startHour, endHour, accounts, primary }) {
  const music = kind === "music";
  const ask = music
    ? ['"full song: {name} — link in bio"', '"{name} is out now. link in bio"']
    : ['"get {name} — link in bio"', '"try {name} free. link in bio"'];
  const config = `# ${title} — created from the dashboard.
# Every setting here can be changed from the dashboard's Setup tab.

slug: ${slug}
timezone: ${timezone}

creatives:
  - name: default

posting:
  posts_per_day: ${postsPerDay}
  start_hour: ${startHour}
  end_hour: ${endHour}
  max_buffer_queue: 10
  max_backlog_days: 1
  fan_out: true
  # A new campaign starts switched off. Go live from the dashboard once a
  # test run looks right.
  paused: true
  dry_run: true
${accounts.length ? `
accounts:
  mode: allow
  names:
${accounts.map((a) => `    - ${a}`).join("\n")}
` : ""}
video:
  width: 1080
  height: 1920
  fps: 30
  crf: 21
  preset: veryfast
  min_duration_sec: 5
  max_duration_sec: 60
  max_file_mb: 100

composition:
  bodies_per_video: ${music ? 0 : 1}
  loop_to_min: ${music}
  music_volume: ${music ? "1.0" : "0.1"}
  clip_volume: ${music ? "0.0" : "1.0"}
  music_cleared: ${music}
  music_fade_in_sec: ${music ? "0.05" : "0.5"}
  music_fade_out_sec: ${music ? "0.4" : "1.5"}
  music_random_start: true
  music_segment_sec: 15

variation:
  enabled: true
  per_account: true
  per_account_vary:
    - clip
    - caption
    - cue
  speed_max: 0.0
  music_tempo_max: 0.0
  music_tilt_db: 0.0

funnel:
  name: ${yamlString(title)}
  link: ${yamlString(link || "")}
  cta:
    - ${ask.join("\n    - ")}
  cta_every: 1
  first_comment:
    - "{name} — link in bio"
  end_card: ${music ? '"{name} | full song on Spotify"' : '"{name} | link in bio"'}
  end_card_sec: 2.0

selection:
  dedupe_on: [hook, ${music ? "" : "body, "}music, caption]
  caption_cooldown_days: 0
  hook_cooldown_days: 0
  min_runway_days: 7
  auto_fill: true

buffer:
  api_key_secret: ${primary.api_key_secret}
  channel_id: ${primary.channel_id}
  post_type: ${primary.post_type || POST_TYPE[primary.network]}
  service: ${primary.network}
${primary.organization_id ? `  organization_id: ${primary.organization_id}\n` : ""}  title_strategy: derive

notify:
  webhook_secret: DISCORD_WEBHOOK
  on: [failure, queue_empty, quota_high, license_missing, dedupe_relaxed,
       queue_stale, distribution_lost, schedule_gap, digest]
`;

  const captions = `# Captions for ${title}. Edit these from the dashboard's Content tab.

overlay: ${music ? "this part. | every single time." : "wait for it"}
title: ${title}
${title}
${music ? "out now everywhere" : "link in bio"}
---
overlay: ${music ? "pov: you found it first" : "nobody told me about this"}
title: ${title}
${music ? `${title} — streaming now` : `this is ${title}`}
`;

  const base = `campaigns/${slug}`;
  return [
    { path: `${base}/config.yaml`, text: config },
    { path: `${base}/captions.txt`, text: captions },
    { path: `${base}/lineup.yaml`, text: "# Hand-picked posts. Edit from the dashboard's Plan tab.\nposts: []\n" },
    { path: `${base}/creatives/default/LICENSES.md`, text: `# Music licences — ${slug} / default\n\nOne line per track: filename, source, licence.\n\n| file | source | licence |\n|---|---|---|\n` },
  ];
}
