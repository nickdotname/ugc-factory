import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { parseBank, serializeBank } from "../lib/bank.js";
import { campaignFiles, slugify } from "../lib/template.js";
import { replaceTop, setList, setScalar } from "../lib/yamledit.js";

const SAMPLE = `# top comment
slug: demo

posting:
  # how often
  posts_per_day: 4      # was 12
  paused: true
  dry_run: true

composition:
  music_volume: 0.10          # flat
  nested:
    deep: 1

funnel:
  name: "Old"
  cta:
    - "one"
    - "two"
  cta_every: 1

notify:
  on: [failure, digest,
       queue_empty]
  webhook_secret: HOOK
`;

test("a scalar is changed in place and its comment survives", () => {
  const out = setScalar(SAMPLE, ["posting", "posts_per_day"], 6);
  assert.ok(out.includes("  posts_per_day: 6  # was 12"));
  assert.ok(out.includes("# how often"));
  assert.equal(out.split("\n").length, SAMPLE.split("\n").length);
});

test("only the key inside the named section is touched", () => {
  const twice = `a:\n  paused: false\nposting:\n  paused: true\n`;
  assert.equal(setScalar(twice, ["posting", "paused"], false), `a:\n  paused: false\nposting:\n  paused: false\n`);
  // A same-named key deeper in a sibling block is not a direct child.
  const deep = `x:\n  y:\n    name: inner\n  name: outer\n`;
  assert.equal(setScalar(deep, ["x", "name"], "new"), `x:\n  y:\n    name: inner\n  name: "new"\n`);
});

test("a missing key is added at the end of its section", () => {
  const out = setScalar(SAMPLE, ["posting", "start_hour"], 11);
  assert.ok(out.includes("  dry_run: true\n  start_hour: 11\n\ncomposition:"));
});

test("a missing section is created", () => {
  const out = setScalar("slug: a\n", ["overlay", "size"], 0.07);
  assert.equal(out, "slug: a\n\noverlay:\n  size: 0.07\n");
});

test("strings are quoted so they cannot be misread", () => {
  const out = setScalar(SAMPLE, ["funnel", "name"], 'Yes: "No" #1');
  assert.ok(out.includes('  name: "Yes: \\"No\\" #1"'));
});

test("a quoted value containing # is replaced whole", () => {
  const out = setScalar('f:\n  name: "a # b"  # note\n', ["f", "name"], "c");
  assert.equal(out, 'f:\n  name: "c"  # note\n');
});

test("a block list is replaced, neighbours untouched", () => {
  const out = setList(SAMPLE, ["funnel", "cta"], ["new line"]);
  assert.ok(out.includes('  cta:\n    - "new line"\n  cta_every: 1'));
  assert.ok(!out.includes('"two"'));
});

test("a wrapped flow list is replaced whole", () => {
  const out = setList(SAMPLE, ["notify", "on"], ["failure"]);
  assert.ok(out.includes('  on:\n    - "failure"\n  webhook_secret: HOOK'));
  assert.ok(!out.includes("queue_empty"));
});

test("an empty list is written as []", () => {
  assert.ok(setList(SAMPLE, ["funnel", "cta"], []).includes("  cta: []\n  cta_every"));
});

test("a top-level block is replaced or appended", () => {
  const out = replaceTop(SAMPLE, "composition", "composition:\n  clip_volume: 0.0");
  assert.ok(out.includes("composition:\n  clip_volume: 0.0\n\nfunnel:"));
  assert.ok(!out.includes("nested"));
  assert.ok(replaceTop("slug: a\n", "creatives", "creatives:\n  - name: x").endsWith("creatives:\n  - name: x\n"));
});

test("editing the real configs changes one line each", () => {
  for (const slug of ["clubs", "closequarters"]) {
    const text = readFileSync(new URL(`../../campaigns/${slug}/config.yaml`, import.meta.url), "utf8");
    const out = setScalar(text, ["posting", "posts_per_day"], 9);
    const changed = out.split("\n").filter((line, i) => line !== text.split("\n")[i]);
    assert.equal(out.split("\n").length, text.split("\n").length, slug);
    assert.equal(changed.length, 1, slug);
    assert.match(changed[0], /^\s+posts_per_day: 9/);
  }
});

test("caption banks round-trip", () => {
  const text = "# notes\n# more\n\noverlay: a | b\ntitle: T\nline one\n\nline three\n---\njust a caption\n";
  const bank = parseBank(text);
  assert.equal(bank.header, "# notes\n# more");
  assert.deepEqual(bank.records, [
    { overlay: "a | b", title: "T", body: "line one\n\nline three" },
    { overlay: "", title: "", body: "just a caption" },
  ]);
  assert.equal(serializeBank(bank), text);
});

test("the real banks survive a round trip with every record intact", () => {
  for (const path of ["clubs/captions.txt", "clubs/captions/youtube.txt", "closequarters/captions.txt"]) {
    const text = readFileSync(new URL(`../../campaigns/${path}`, import.meta.url), "utf8");
    const once = parseBank(text);
    assert.ok(once.records.length > 2, path);
    assert.deepEqual(parseBank(serializeBank(once)).records, once.records, path);
  }
});

test("empty records are dropped on save", () => {
  assert.equal(serializeBank({ header: "", records: [{ body: " " }, { body: "x", overlay: "o" }] }), "overlay: o\nx\n");
});

test("slugs are safe names", () => {
  assert.equal(slugify("Close Quarters — Vol. 2!"), "close_quarters_vol_2");
  assert.equal(slugify("2 Fast"), "c_2_fast");
});

test("a new campaign starts switched off", () => {
  const files = campaignFiles({
    slug: "demo", kind: "music", title: 'My "Song"', link: "", timezone: "America/New_York",
    postsPerDay: 3, startHour: 11, endHour: 23, accounts: ["a_tt"],
    primary: { api_key_secret: "BUFFER_API_KEY", channel_id: "c1", network: "tiktok" },
  });
  const config = files.find((f) => f.path === "campaigns/demo/config.yaml").text;
  assert.ok(config.includes("paused: true") && config.includes("dry_run: true"));
  assert.ok(config.includes('name: "My \\"Song\\""'));
  assert.deepEqual(files.map((f) => f.path).sort(), [
    "campaigns/demo/captions.txt", "campaigns/demo/config.yaml",
    "campaigns/demo/creatives/default/LICENSES.md", "campaigns/demo/lineup.yaml",
  ]);
});
