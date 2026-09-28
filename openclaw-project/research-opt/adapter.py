"""Fail-open Jev decisions for an already completed public web_fetch result.

This is a host-side adapter, not a fetcher.  A caller must supply trusted
provenance for both the web_fetch result and a public research question.
The installed OpenClaw tool-result middleware does not supply the latter;
do not attach this adapter to arbitrary sessions until that is solved.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping
from urllib.parse import urljoin, urlsplit

MODEL = "jev-1.13.0"
PRICE_PER_INPUT_TOKEN = 0.042 / 1_000_000
MAX_STATE_CHARS = 16000
MAX_LINKS = 20
CHUNK_SIZE = 2400
SUSPECT = re.compile(
    r"ignore (?:all |prior |previous )?instructions|"
    r"instruction for ai|ai agents|send private|change (?:your )?tool policy|"
    r"create a cron|remember this rule",
    re.I,
)
LINK = re.compile(r"\[([^\]]{1,120})\]\((https?://[^\s)]+)\)")
LOGIN = re.compile(r"(?:^|[/-])(login|signin|sign-in|account|billing|payment|checkout)(?:[/?#-]|$)", re.I)


@dataclass(frozen=True)
class PublicFetch:
    task_id: str
    url: str
    final_url: str
    content: str
    question: str
    origin: str
    question_origin: str
    authenticated: bool = False
    connector_seen: bool = False


@dataclass(frozen=True)
class Decision:
    content: str
    fallback: bool
    reason: str
    cost_usd: float | None
    latency_ms: int | None


def public_url(raw: str) -> bool:
    try:
        u = urlsplit(raw)
        host = u.hostname
        if u.scheme not in ("http", "https") or not host or u.username or u.password:
            return False
        if host.lower() in ("localhost",) or host.lower().endswith((".local", ".internal", ".localhost")):
            return False
        if LOGIN.search(u.path):
            return False
        try:
            if not ipaddress.ip_address(host).is_global:
                return False
        except ValueError:
            pass
        return True
    except ValueError:
        return False


def eligible(page: PublicFetch) -> bool:
    return (
        page.origin == "web_fetch"
        and page.question_origin == "host_public_task"
        and not page.authenticated
        and not page.connector_seen
        and bool(page.task_id and page.question.strip())
        and public_url(page.url)
        and public_url(page.final_url)
        and urlsplit(page.url).scheme == urlsplit(page.final_url).scheme
    )


def chunks(content: str) -> list[tuple[str, str]]:
    if len(content) <= CHUNK_SIZE:
        return [("c00_" + hashlib.sha256(content.encode()).hexdigest()[:10], content)]
    out = []
    for n, start in enumerate(range(0, len(content), CHUNK_SIZE)):
        part = content[start : start + CHUNK_SIZE]
        out.append((f"c{n:02d}_" + hashlib.sha256(part.encode()).hexdigest()[:10], part))
    return out


def candidates(page: PublicFetch) -> list[tuple[str, str, str]]:
    scheme = urlsplit(page.final_url).scheme
    seen: set[str] = set()
    out = []
    for label, href in LINK.findall(page.content):
        target = urljoin(page.final_url, href)
        if target in seen or not public_url(target) or urlsplit(target).scheme != scheme:
            continue
        seen.add(target)
        out.append((f"l{len(out):02d}", label, target))
        if len(out) >= MAX_LINKS:
            break
    return out


def _valid_noul(answer: object) -> float:
    if not isinstance(answer, dict) or answer.get("type") != "noul":
        raise ValueError("invalid_noul")
    value = answer.get("noul")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("invalid_noul_probability")
    return float(value)


def _valid_choice(answer: object, offered: set[str]) -> tuple[str, float, Mapping[str, float]]:
    if not isinstance(answer, dict) or answer.get("type") != "choice":
        raise ValueError("invalid_choice")
    chosen, probs, confidence = answer.get("choice"), answer.get("probabilities"), answer.get("confidence")
    if chosen not in offered or not isinstance(probs, dict) or set(probs) != offered:
        raise ValueError("out_of_list")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 1 for v in probs.values()):
        raise ValueError("invalid_probabilities")
    if abs(sum(probs.values()) - 1) > 0.03:
        raise ValueError("probability_sum")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError("invalid_confidence")
    return chosen, float(confidence), probs


def _valid_score(answer: object, criteria: list[str]) -> tuple[object, float, Mapping[str, float]]:
    if not isinstance(answer, dict) or answer.get("type") != "score":
        raise ValueError("invalid_score")
    # TypeSafe uses zero-based numeric Score levels in the HTTP response.
    score = answer.get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or score < 0 or score > 2:
        raise ValueError("invalid_score_level")
    probs = answer.get("probabilities")
    expected = {str(i) for i in range(len(criteria))}
    if not isinstance(probs, dict) or set(probs) != expected:
        raise ValueError("invalid_score_distribution")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 1 for v in probs.values()):
        raise ValueError("invalid_score_probabilities")
    if abs(sum(probs.values()) - 1) > 0.03:
        raise ValueError("score_probability_sum")
    if answer.get("legend") != {str(i): criterion for i, criterion in enumerate(criteria)}:
        raise ValueError("score_legend_mismatch")
    conf = answer.get("confidence")
    if isinstance(conf, bool) or not isinstance(conf, (int, float)) or not math.isfinite(conf) or not 0 <= conf <= 1:
        raise ValueError("invalid_score_confidence")
    return score, float(conf), probs


def _log(path: Path | None, row: dict) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as out:
        out.write(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n")


def decide(
    page: PublicFetch,
    transport: Callable[[dict, float], dict],
    *,
    enabled: bool,
    budget_ok: Callable[[], bool],
    log_path: Path | None = None,
    timeout_s: float = 2.0,
) -> Decision:
    """Return the original content object exactly on every unsafe/error path."""
    started = time.monotonic()
    base = {"timestamp": time.time(), "task_id": page.task_id, "url": page.url, "model": MODEL}

    def fallback(reason: str, latency_ms: int | None = None, cost: float | None = None) -> Decision:
        _log(log_path, {**base, "fallback": True, "reason": reason, "latency_ms": latency_ms, "cost_usd": cost})
        return Decision(page.content, True, reason, cost, latency_ms)

    if not enabled:
        return fallback("toggle_off")
    if not eligible(page):
        return fallback("privacy_ineligible")
    if not budget_ok():
        return fallback("budget")
    if len(page.content) > MAX_STATE_CHARS or len(page.content) + len(page.question) > MAX_STATE_CHARS:
        return fallback("state_limit")

    parts = chunks(page.content)
    links = candidates(page)
    questions: dict[str, dict] = {
        "relevant": {"type": "noul", "instructions": f"Does this public page contain information answering: {page.question}?"},
        "source_quality": {"type": "score", "instructions": "Rate the page's evidence quality for this question.", "criteria": ["poor: unsupported or off-topic", "mixed: partial support", "strong: primary, direct support"]},
    }
    if len(parts) > 1:
        for cid, _ in parts:
            questions["chunk_" + cid] = {"type": "noul", "instructions": f"Is chunk {cid} useful for answering: {page.question}?"}
    if links:
        criteria = {lid: f"{label}: {url}" for lid, label, url in links}
        criteria["none"] = "No offered link is likely to answer the question"
        for rank in range(1, min(3, len(links)) + 1):
            questions[f"link_{rank}"] = {"type": "choice", "instructions": f"Which offered link is the #{rank} most useful follow-up for: {page.question}?", "criteria": criteria}

    request = {"model": MODEL, "state": page.content, "questions": questions}
    try:
        response = transport(request, timeout_s)
        elapsed = int((time.monotonic() - started) * 1000)
        if response.get("model") != MODEL or set(response.get("answers", {})) != set(questions):
            raise ValueError("model_or_question_mismatch")
        answers = response["answers"]
        relevance = _valid_noul(answers["relevant"])
        score, score_conf, score_probs = _valid_score(answers["source_quality"], questions["source_quality"]["criteria"])
        selected = []
        for cid, part in parts:
            if len(parts) == 1 or _valid_noul(answers["chunk_" + cid]) >= 0.5 or SUSPECT.search(part):
                selected.append((cid, part))
        ranked = []
        rank_rows = []
        allowed = {lid for lid, _, _ in links} | {"none"}
        for rank in range(1, min(3, len(links)) + 1):
            pick, conf, probs = _valid_choice(answers[f"link_{rank}"], allowed)
            if pick != "none" and pick not in ranked:
                ranked.append(pick)
            rank_rows.append({**base, "question": f"link_{rank}", "answer": pick, "confidence": conf, "probabilities": probs, "fallback": False, "latency_ms": elapsed, "cost_usd": None})
        usage = response.get("usage", {})
        tokens = usage.get("input_tokens")
        if isinstance(tokens, bool) or not isinstance(tokens, int) or tokens < 0:
            raise ValueError("missing_usage")
        cost = tokens * PRICE_PER_INPUT_TOKEN
        for row in rank_rows:
            _log(log_path, row)
        if relevance <= 0.10 and not SUSPECT.search(page.content):
            content = f"{page.final_url}\n[Page dropped by Jev: high-confidence irrelevant; P(relevant)={relevance:.3f}.]"
        else:
            if not selected:
                selected = parts
            content = "\n".join(part for _, part in selected)
            if ranked:
                lookup = {lid: url for lid, _, url in links}
                content += "\n\n[Jev-ranked follow-up links; researcher chooses whether to fetch]\n"
                content += "\n".join(lookup[lid] for lid in ranked)
        _log(log_path, {**base, "question": "relevant", "answer": relevance, "confidence": None, "fallback": False, "latency_ms": elapsed, "cost_usd": cost})
        _log(log_path, {**base, "question": "source_quality", "answer": score, "confidence": score_conf, "probabilities": score_probs, "fallback": False, "latency_ms": elapsed, "cost_usd": None})
        for cid, _ in parts:
            if len(parts) > 1:
                _log(log_path, {**base, "question": "chunk_" + cid, "answer": answers["chunk_" + cid]["noul"], "confidence": None, "fallback": False, "latency_ms": elapsed, "cost_usd": None})
        return Decision(content, False, "accepted", cost, elapsed)
    except Exception as exc:
        return fallback(type(exc).__name__ + ":" + str(exc)[:80], int((time.monotonic() - started) * 1000))
