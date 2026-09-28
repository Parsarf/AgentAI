import fs from "node:fs";
import crypto from "node:crypto";
import net from "node:net";

export const MODEL = "jev-1.13.0";
export const PRICE = 0.042 / 1_000_000;
const CHUNK = 2400;
const MAX_CHARS = 16000;
const LOGIN = /(?:^|[/-])(login|signin|sign-in|account|billing|payment|checkout)(?:[/?#-]|$)/i;
const SUSPECT = /ignore (?:all |prior |previous )?instructions|instruction for ai|ai agents|send private|change (?:your )?tool policy|create a cron|remember this rule/i;
const MD_LINK = /\[([^\]]{1,120})\]\((https?:\/\/[^\s)]+)\)/g;

export function publicUrl(raw) {
  try {
    const u = new URL(raw);
    if (!["http:", "https:"].includes(u.protocol) || u.username || u.password) return false;
    const h = u.hostname.toLowerCase();
    if (["localhost", "0.0.0.0"].includes(h) || h.endsWith(".local") || h.endsWith(".internal") || h.endsWith(".localhost")) return false;
    if (LOGIN.test(u.pathname)) return false;
    if (net.isIP(h)) {
      if (h.includes(":")) return false; // conservative: IPv6 remains baseline
      const n = h.split(".").map(Number);
      if (n[0] === 10 || n[0] === 127 || n[0] === 0 || n[0] >= 224 || n[0] === 169 && n[1] === 254 || n[0] === 172 && n[1] >= 16 && n[1] <= 31 || n[0] === 192 && n[1] === 168 || n[0] === 100 && n[1] >= 64 && n[1] <= 127 || n[0] === 198 && n[1] >= 18 && n[1] <= 19) return false;
    }
    return true;
  } catch { return false; }
}

export function pageChunks(content) {
  const out = [];
  for (let i = 0; i < content.length; i += CHUNK) {
    const text = content.slice(i, i + CHUNK);
    out.push({ id: `c${String(out.length).padStart(2, "0")}_${crypto.createHash("sha256").update(text).digest("hex").slice(0, 10)}`, text });
  }
  return out;
}

export function links(content, pageUrl) {
  const out = [], seen = new Set();
  for (const m of content.matchAll(MD_LINK)) {
    const url = new URL(m[2], pageUrl).href;
    if (seen.has(url) || !publicUrl(url) || new URL(url).protocol !== new URL(pageUrl).protocol) continue;
    seen.add(url);
    out.push({ id: `l${String(out.length).padStart(2, "0")}`, label: m[1], url });
    if (out.length >= 20) break;
  }
  return out;
}

function number01(x) { return typeof x === "number" && Number.isFinite(x) && x >= 0 && x <= 1; }
function validNoul(x) { if (x?.type !== "noul" || !number01(x.noul)) throw Error("invalid_noul"); return x.noul; }
function validDistribution(probs, ids) {
  if (!probs || typeof probs !== "object" || Object.keys(probs).length !== ids.length || ids.some(id => !number01(probs[id]))) throw Error("invalid_distribution");
  if (Math.abs(ids.reduce((v, id) => v + probs[id], 0) - 1) > 0.03) throw Error("invalid_distribution_sum");
}
function validScore(x, rubric) {
  const ids = rubric.map((_, i) => String(i));
  if (x?.type !== "score" || typeof x.score !== "number" || !Number.isFinite(x.score) || x.score < 0 || x.score > rubric.length - 1 || !number01(x.confidence)) throw Error("invalid_score");
  validDistribution(x.probabilities, ids);
  if (ids.some((id, i) => x.legend?.[id] !== rubric[i])) throw Error("invalid_score_legend");
}
function validChoice(x, ids) {
  if (x?.type !== "choice" || !ids.includes(x.choice) || !number01(x.confidence)) throw Error("invalid_choice");
  validDistribution(x.probabilities, ids);
}

export function buildRequest(content, question, pageUrl) {
  const chunks = pageChunks(content);
  const candidates = links(content, pageUrl);
  const rubric = ["poor: unsupported or off-topic", "mixed: partial support", "strong: primary, direct support"];
  const questions = {
    relevant: { type: "noul", instructions: `Does this public page contain information answering: ${question}?` },
    source_quality: { type: "score", instructions: "Rate the page's evidence quality for this question.", criteria: rubric },
  };
  if (chunks.length > 1) for (const chunk of chunks) questions[`chunk_${chunk.id}`] = { type: "noul", instructions: `Is chunk ${chunk.id} useful for answering: ${question}?` };
  if (candidates.length) {
    const criteria = Object.fromEntries(candidates.map(x => [x.id, `${x.label}: ${x.url}`]));
    criteria.none = "No offered link is likely to answer the question";
    for (let i = 1; i <= Math.min(3, candidates.length); i++) questions[`link_${i}`] = { type: "choice", instructions: `Which offered link is the #${i} most useful follow-up for: ${question}?`, criteria };
  }
  return { request: { model: MODEL, state: content, questions }, chunks, candidates, rubric };
}

export function applyAnswer(built, answer, pageUrl) {
  if (answer?.model !== MODEL || !answer.answers || Object.keys(answer.answers).length !== Object.keys(built.request.questions).length) throw Error("answer_mismatch");
  if (Object.keys(built.request.questions).some(id => !(id in answer.answers))) throw Error("missing_answer");
  const a = answer.answers;
  const relevance = validNoul(a.relevant);
  validScore(a.source_quality, built.rubric);
  const selected = built.chunks.filter(c => built.chunks.length === 1 || validNoul(a[`chunk_${c.id}`]) >= 0.5 || SUSPECT.test(c.text));
  const picks = [];
  const ids = [...built.candidates.map(x => x.id), "none"];
  for (let i = 1; i <= Math.min(3, built.candidates.length); i++) {
    const response = a[`link_${i}`];
    validChoice(response, ids);
    if (response.choice !== "none" && !picks.includes(response.choice)) picks.push(response.choice);
  }
  if (!Number.isInteger(answer.usage?.input_tokens) || answer.usage.input_tokens < 0) throw Error("missing_usage");
  const cost = answer.usage.input_tokens * PRICE;
  let content;
  if (relevance <= 0.10 && !SUSPECT.test(built.request.state)) {
    content = `${pageUrl}\n[Page dropped by Jev: high-confidence irrelevant; P(relevant)=${relevance.toFixed(3)}.]`;
  } else {
    content = (selected.length ? selected : built.chunks).map(x => x.text).join("\n");
    if (picks.length) content += "\n\n[Jev-ranked follow-up links; researcher chooses whether to fetch]\n" + picks.map(id => built.candidates.find(x => x.id === id).url).join("\n");
  }
  const decisions = [{ question: "relevant", answer: relevance, confidence: null }, { question: "source_quality", answer: a.source_quality.score, confidence: a.source_quality.confidence, probabilities: a.source_quality.probabilities }];
  for (const c of built.chunks) if (built.chunks.length > 1) decisions.push({ question: `chunk_${c.id}`, answer: a[`chunk_${c.id}`].noul, confidence: null });
  for (let i = 1; i <= Math.min(3, built.candidates.length); i++) decisions.push({ question: `link_${i}`, answer: a[`link_${i}`].choice, confidence: a[`link_${i}`].confidence, probabilities: a[`link_${i}`].probabilities });
  return { content, cost, decisions };
}

export function eligible(event, ctx, registry) {
  if (ctx.agentId !== "researcher" || event.toolName !== "web_fetch") return null;
  const task = registry?.[ctx.sessionId];
  const url = event.args?.url;
  if (!task || !Array.isArray(task.urls) || !task.urls.includes(url) || typeof task.question !== "string" || !task.question.trim() || !publicUrl(url)) return null;
  if (event.isError || !Array.isArray(event.result?.content) || event.result.content.length !== 1 || event.result.content[0]?.type !== "text") return null;
  const content = event.result.content[0].text;
  if (typeof content !== "string" || !content || content.length > MAX_CHARS || content.length + task.question.length > MAX_CHARS) return null;
  return { task, url, content };
}

export async function transform(event, ctx, deps) {
  const original = event.result;
  const log = row => deps.log?.({ timestamp: new Date().toISOString(), task_id: ctx.sessionId, url: event.args?.url, model: MODEL, ...row });
  if (!deps.enabled()) { log({ fallback: true, reason: "toggle_off", cost_usd: null }); return original; }
  const entry = eligible(event, ctx, deps.registry());
  if (!entry) { log({ fallback: true, reason: "privacy_or_shape", cost_usd: null }); return original; }
  if (!deps.budgetOk()) { log({ fallback: true, reason: "budget", cost_usd: null }); return original; }
  const started = performance.now();
  try {
    const built = buildRequest(entry.content, entry.task.question, entry.url);
    const answer = await deps.evaluate(built.request, 2000);
    const { content, cost, decisions } = applyAnswer(built, answer, entry.url);
    for (const d of decisions) log({ ...d, fallback: false, latency_ms: Math.round(performance.now() - started), cost_usd: d.question === "relevant" ? cost : null });
    return { ...original, content: [{ ...original.content[0], text: content }] };
  } catch (error) {
    log({ fallback: true, reason: String(error?.message || error).slice(0, 80), latency_ms: Math.round(performance.now() - started), cost_usd: null });
    return original;
  }
}

const STATE = "/home/node/.openclaw/jev-research";
function readJson(path, fallback) { try { return JSON.parse(fs.readFileSync(path, "utf8")); } catch { return fallback; } }
function appendLog(row) { fs.appendFileSync(`${STATE}/decisions.jsonl`, JSON.stringify(row) + "\n", { mode: 0o600 }); }
async function evaluate(request, timeoutMs) {
  const key = fs.readFileSync("/run/secrets/phase4a-jev-eval.key", "utf8").trim();
  const r = await fetch("http://litellm:4000/typesafe/v1/systemone", {
    method: "POST",
    headers: { "Authorization": `Bearer ${key}`, "Content-Type": "application/json" },
    body: JSON.stringify(request),
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (!r.ok) throw Error(`jev_http_${r.status}`);
  return await r.json();
}

export default {
  id: "jev-research",
  register(api) {
    api.registerAgentToolResultMiddleware(async (event, ctx) => {
      const result = await transform(event, ctx, {
        enabled: () => readJson(`${STATE}/config.json`, { enabled: false }).enabled === true,
        registry: () => readJson(`${STATE}/public-tasks.json`, {}),
        budgetOk: () => fs.existsSync("/run/secrets/phase4a-jev-eval.key"),
        evaluate,
        log: appendLog,
      });
      return result === event.result ? undefined : { result };
    }, { runtimes: ["openclaw"], matcher: ["web_fetch"] });
  },
};
