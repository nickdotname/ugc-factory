// The caption bank format, both directions (mirrors src/descriptions.py).
//
// Records are separated by a line of ---. A record may open with
// `overlay:` (drawn on the video) and `title:` (YouTube) lines, in either
// order; the rest is the caption. Comment lines are ignored by the engine;
// the block of them at the top of the file is kept when saving.

const SEPARATOR = /^-{3,}\s*$/m;

export function parseBank(text) {
  const lines = text.split("\n");
  let cut = 0;
  while (cut < lines.length && (!lines[cut].trim() || lines[cut].trim().startsWith("#"))) cut += 1;
  const header = lines.slice(0, cut).join("\n").trim();
  const body = lines.slice(cut).join("\n");
  const blocks = SEPARATOR.test(body) ? body.split(new RegExp(SEPARATOR.source, "m")) : body.split("\n\n");

  const records = [];
  for (const block of blocks) {
    const kept = block.trim().split("\n").filter((ln) => !ln.trim().startsWith("#"));
    if (!kept.join("").trim()) continue;
    const record = { overlay: "", title: "", body: "" };
    while (kept.length) {
      const overlay = /^overlay:\s*(.*)$/i.exec(kept[0].trim());
      const title = /^title:\s*(.*)$/i.exec(kept[0].trim());
      if (overlay && !record.overlay) record.overlay = overlay[1].trim();
      else if (title && !record.title) record.title = title[1].trim();
      else break;
      kept.shift();
    }
    record.body = kept.join("\n").trim();
    if (record.body) records.push(record);
  }
  return { header, records };
}

export function serializeBank({ header, records }) {
  const parts = records
    .filter((r) => (r.body || "").trim())
    .map((r) => [
      (r.overlay || "").trim() ? `overlay: ${r.overlay.trim().replace(/\n+/g, " | ")}` : "",
      (r.title || "").trim() ? `title: ${r.title.trim().replace(/\n+/g, " ")}` : "",
      // A caption line of only dashes would be read as a separator.
      r.body.trim().split("\n").map((ln) => (/^-{3,}\s*$/.test(ln) ? "—" : ln)).join("\n"),
    ].filter(Boolean).join("\n"));
  return `${header ? `${header}\n\n` : ""}${parts.join("\n---\n")}\n`;
}
