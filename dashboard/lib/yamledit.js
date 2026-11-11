// Small, comment-preserving edits to a YAML file.
//
// The campaign configs are written for people — most of their value is in
// the comments explaining why a number is what it is. Parsing a file and
// writing it back out would delete every one of them, so the settings forms
// change values in place instead: find the line, replace what is after the
// colon, leave everything else exactly as it was.
//
// Deliberately handles only the shapes the configs use: nested mappings
// indented with spaces, scalar values, and lists of scalars.

const KEY = (name) => new RegExp(`^(\\s*)${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}:(.*)$`);
const indentOf = (line) => line.match(/^\s*/)[0].length;
const isBlank = (line) => !line.trim() || line.trim().startsWith("#");

/** A string as a YAML scalar that cannot be misread. */
export function yamlString(value) {
  return JSON.stringify(String(value));
}

/** Format a JS value as a YAML scalar. */
export function scalar(value) {
  if (typeof value === "boolean" || typeof value === "number") return String(value);
  return yamlString(value);
}

// Lines [start, end) that belong to the mapping whose key line is at `at`.
function blockEnd(lines, at) {
  const base = indentOf(lines[at]);
  let end = at + 1;
  let lastContent = at;
  while (end < lines.length) {
    const line = lines[end];
    if (!isBlank(line)) {
      if (indentOf(line) <= base) break;
      lastContent = end;
    }
    end += 1;
  }
  // Trailing blank lines and comments belong to whatever comes next.
  return lastContent + 1;
}

// Find the key line for `path`, searching only inside its parents.
// Returns { at, parentAt, depth } — `at` is -1 when the last key is missing,
// and depth is how many leading keys were found.
function locate(lines, path) {
  let from = 0;
  let to = lines.length;
  let indent = -1;
  let parentAt = -1;
  for (let depth = 0; depth < path.length; depth += 1) {
    let found = -1;
    let childIndent = null;
    for (let i = from; i < to; i += 1) {
      const line = lines[i];
      if (isBlank(line)) continue;
      const here = indentOf(line);
      if (here <= indent) break;
      if (childIndent === null) childIndent = here;
      // Only direct children: deeper lines belong to a sibling's block.
      if (here !== childIndent) continue;
      if (KEY(path[depth]).test(line)) { found = i; break; }
    }
    if (found === -1) return { at: -1, parentAt, depth, childIndent };
    parentAt = found;
    indent = indentOf(lines[found]);
    from = found + 1;
    to = blockEnd(lines, found);
    if (depth === path.length - 1) return { at: found, parentAt, depth: depth + 1 };
  }
  return { at: -1, parentAt, depth: 0 };
}

// Split "value   # comment" without being fooled by a # inside quotes.
function splitComment(rest) {
  let quote = "";
  for (let i = 0; i < rest.length; i += 1) {
    const ch = rest[i];
    if (quote) {
      if (ch === "\\" && quote === '"') i += 1;
      else if (ch === quote) quote = "";
    } else if (ch === '"' || ch === "'") quote = ch;
    else if (ch === "#" && (i === 0 || /\s/.test(rest[i - 1]))) {
      return [rest.slice(0, i).trimEnd(), rest.slice(i)];
    }
  }
  return [rest.trimEnd(), ""];
}

function insertUnder(lines, path, located, rendered) {
  // Create any missing parents, then the key itself, at the end of the
  // deepest parent that does exist.
  const missing = path.slice(located.depth);
  let indent;
  let at;
  if (located.parentAt === -1) {
    indent = 0;
    at = lines.length;
    while (at > 0 && !lines[at - 1].trim()) at -= 1;
  } else {
    const parentIndent = indentOf(lines[located.parentAt]);
    indent = located.childIndent != null && located.childIndent > parentIndent
      ? located.childIndent : parentIndent + 2;
    at = blockEnd(lines, located.parentAt);
    // A parent written as `key: {}` or `key:` with nothing under it.
    const m = KEY(path[located.depth - 1]).exec(lines[located.parentAt]);
    if (m && /^\s*(\{\s*\}|\[\s*\])\s*(#.*)?$/.test(m[2])) {
      lines[located.parentAt] = `${m[1]}${path[located.depth - 1]}:`;
    }
  }
  const out = [];
  missing.forEach((key, i) => {
    const pad = " ".repeat(indent + i * 2);
    out.push(i === missing.length - 1 ? rendered(pad, key) : `${pad}${key}:`);
  });
  if (located.parentAt === -1 && at > 0) out.unshift("");
  lines.splice(at, 0, ...out.flat());
}

/** Set `a.b.c` to a scalar, keeping the line's comment. Adds it if missing. */
export function setScalar(text, path, value) {
  const lines = text.split("\n");
  const located = locate(lines, path);
  const rendered = scalar(value);
  if (located.at === -1) {
    insertUnder(lines, path, located, (pad, key) => `${pad}${key}: ${rendered}`);
    return lines.join("\n");
  }
  const m = KEY(path[path.length - 1]).exec(lines[located.at]);
  const [, comment] = splitComment(m[2]);
  lines[located.at] = `${m[1]}${path[path.length - 1]}: ${rendered}${comment ? `  ${comment}` : ""}`;
  return lines.join("\n");
}

/** Set `a.b` to a list of scalars, written one per line. Adds it if missing. */
export function setList(text, path, items) {
  const lines = text.split("\n");
  const located = locate(lines, path);
  const key = path[path.length - 1];
  const render = (pad) => (items.length
    ? [`${pad}${key}:`, ...items.map((item) => `${pad}  - ${scalar(item)}`)]
    : [`${pad}${key}: []`]);
  if (located.at === -1) {
    insertUnder(lines, path, located, (pad) => render(pad));
    return lines.join("\n");
  }
  const m = KEY(key).exec(lines[located.at]);
  const [inline] = splitComment(m[2]);
  let end;
  if (inline.trim().startsWith("[")) {
    // A flow list, possibly wrapped over several lines.
    end = located.at;
    while (end < lines.length && !splitComment(lines[end])[0].includes("]")) end += 1;
    end += 1;
  } else if (inline.trim()) {
    end = located.at + 1;
  } else {
    end = blockEnd(lines, located.at);
  }
  lines.splice(located.at, end - located.at, ...render(m[1]));
  return lines.join("\n");
}

/** Replace a whole top-level block (`key:` and everything under it). */
export function replaceTop(text, key, block) {
  const lines = text.split("\n");
  const located = locate(lines, [key]);
  const fresh = block.replace(/\n+$/, "").split("\n");
  if (located.at === -1) {
    while (lines.length && !lines[lines.length - 1].trim()) lines.pop();
    return [...lines, "", ...fresh, ""].join("\n");
  }
  const m = KEY(key).exec(lines[located.at]);
  const [inline] = splitComment(m[2]);
  const end = inline.trim() && !inline.trim().startsWith("[") ? located.at + 1
    : inline.trim().startsWith("[")
      ? (() => { let e = located.at; while (e < lines.length && !lines[e].includes("]")) e += 1; return e + 1; })()
      : blockEnd(lines, located.at);
  lines.splice(located.at, end - located.at, ...fresh);
  return lines.join("\n");
}
