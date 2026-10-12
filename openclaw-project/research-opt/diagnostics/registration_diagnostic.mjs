// Harmless registration diagnostic for the jev-research middleware (Phase 12).
//
// Loads the plugin through the INSTALLED OpenClaw loader (internal modules, found by
// content because bundle file names are hashed) against whatever state dir the
// environment selects, then reports whether the middleware is registered and whether
// the runner would invoke it for the "openclaw" runtime. No network, no model call,
// no config write. Pinned to the OpenClaw version it was written for; on any other
// version it reports "unsupported_version" instead of guessing.
//
// Usage: OPENCLAW_STATE_DIR=<scratch> OPENCLAW_CONFIG_PATH=<scratch>/openclaw.json \
//        node registration_diagnostic.mjs [--root <openclaw package dir>]
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";

const PINNED = "2026.9.6";
const arg = process.argv.indexOf("--root");
const require = createRequire(import.meta.url);
const root = arg > 0 ? process.argv[arg + 1] : path.dirname(require.resolve("openclaw/package.json"));
const pkg = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8"));
const out = { openclaw_version: pkg.version, pinned: PINNED, plugin_id: "jev-research" };
const finish = (extra, code = 0) => { console.log(JSON.stringify({ ...out, ...extra }, null, 1)); process.exit(code); };
if (pkg.version !== PINNED) finish({ result: "unsupported_version" }, 2);

const dist = path.join(root, "dist");
const find = (needle, prefix) => {
  const hit = fs.readdirSync(dist).filter(f => f.endsWith(".mjs") && (!prefix || f.startsWith(prefix)))
    .find(f => fs.readFileSync(path.join(dist, f), "utf8").includes(needle));
  if (!hit) finish({ result: "internal_module_not_found", needle }, 2);
  return pathToFileURL(path.join(dist, hit)).href;
};

const loader = await import(find("function loadPluginRegistryHandle", "loader-"));
const configMod = await import(pathToFileURL(path.join(dist, "config/config.js")).href);
const registry = loader.r({ config: configMod.getRuntimeConfig(), onlyPluginIds: ["jev-research"] });
const middlewares = registry.agentToolResultMiddlewares.filter(m => m.pluginId === "jev-research");
const owners = registry.agentToolResultMiddlewareOwners.filter(m => m.pluginId === "jev-research");
const errors = registry.diagnostics.filter(d => d.level === "error" || d.level === "warn")
  .map(d => ({ level: d.level, pluginId: d.pluginId, message: String(d.message).slice(0, 200) }));
const record = registry.plugins.find(p => p.id === "jev-research");
out.plugin_status = record ? { status: record.status, enabled: record.enabled, explicitlyEnabled: record.explicitlyEnabled, origin: record.origin } : null;
out.owners = owners.map(o => o.runtimes);
out.registered = middlewares.map(m => ({ runtimes: m.runtimes, scopes: m.scopes ?? null }));
out.diagnostics = errors;

// Would the runner call it? Drive a synthetic web_fetch result through the real runner
// with the toggle off, so the handler must return the original result untouched.
const runnerMod = await import(find("function createAgentToolResultMiddlewareRunner"));
const handlers = middlewares.map(m => m.handler);
const runner = runnerMod.t({ runtime: "openclaw", agentId: "researcher", sessionId: "diag-session" }, handlers);
const original = { content: [{ type: "text", text: "diagnostic page body" }] };
const result = await runner.applyToolResultMiddleware({ toolCallId: "diag-1", toolName: "web_fetch",
  args: { url: "https://example.com/" }, result: original });
out.runner_handlers = handlers.length;
out.passthrough_with_toggle_off = JSON.stringify(result.content) === JSON.stringify(original.content);
const ok = middlewares.length > 0 && owners.length > 0 && out.passthrough_with_toggle_off && errors.every(e => e.level !== "error");
finish({ result: ok ? "registered" : "not_registered" }, ok ? 0 : 1);
