#!/usr/bin/env node
// Fixed read helper for the owner dashboard (Phase 8B §1).
// Invoked with fixed argv by the dashboard: `node workread.mjs list|read <rel> [maxBytes]`.
// Containment: every path component is lstat-walked (symlinks refused); the
// final open uses O_NOFOLLOW; size is taken from the open descriptor; reads
// are hard-capped. The relative path is the only caller input.
import fs from "node:fs";
const ROOT = process.env.WR_ROOT || "/home/node/.openclaw/work";
const [, , mode, rel, maxArg] = process.argv;
const out = (o) => process.stdout.write(JSON.stringify(o));
function components(p) {
  if (typeof p !== "string" || p.startsWith("/")) return null;
  if (p === "") return []; // the allowlisted root itself
  const parts = p.split("/").filter((x) => x !== "" && x !== ".");
  if (parts.length === 0 || parts.some((x) => x === ".." || x.startsWith("."))) return null;
  if (parts.some((x) => /[^\w\-. ]/.test(x) || x.length > 120)) return null;
  return parts;
}
function walkNoSymlink(parts) {
  let cur = ROOT;
  for (const part of parts) {
    cur = `${cur}/${part}`;
    const st = fs.lstatSync(cur); // throws on missing; does not follow
    if (st.isSymbolicLink()) throw Error("symlink_refused");
    if (!st.isDirectory() && part !== parts[parts.length - 1]) throw Error("not_a_directory");
  }
  return cur;
}
try {
  const parts = components(rel ?? "");
  if (!parts) { out({ ok: false, reason: "path_rejected" }); process.exit(0); }
  const target = walkNoSymlink(parts);
  if (mode === "list") {
    const st = fs.lstatSync(target);
    if (!st.isDirectory()) { out({ ok: false, reason: "not_a_directory" }); process.exit(0); }
    const entries = fs.readdirSync(target).map((name) => {
      const full = `${target}/${name}`;
      let e = { name, dir: false, link: false, size: 0, mtimeMs: 0 };
      try {
        const s = fs.lstatSync(full);
        e.dir = s.isDirectory(); e.link = s.isSymbolicLink();
        e.size = s.size; e.mtimeMs = Math.round(s.mtimeMs);
      } catch { e = { ...e, unreadable: true }; }
      return e;
    });
    entries.sort((a, b) => (a.dir !== b.dir ? (a.dir ? -1 : 1) : a.name.localeCompare(b.name)));
    out({ ok: true, entries });
  } else if (mode === "read") {
    const max = Math.min(Number(maxArg) || 2_000_000, 4_000_000);
    const fd = fs.openSync(target, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
    try {
      const st = fs.fstatSync(fd); // stat the open descriptor, not the path
      if (!st.isFile()) { out({ ok: false, reason: "not_a_regular_file" }); process.exit(0); }
      if (st.size > max) { out({ ok: false, reason: "too_large", size: st.size }); process.exit(0); }
      const buf = Buffer.alloc(st.size);
      let off = 0;
      while (off < st.size) off += fs.readSync(fd, buf, off, st.size - off, off);
      out({ ok: true, size: st.size, content: buf.toString("utf8") });
    } finally { fs.closeSync(fd); }
  } else out({ ok: false, reason: "bad_mode" });
} catch (e) {
  out({ ok: false, reason: String(e?.message || e).slice(0, 120) });
}
