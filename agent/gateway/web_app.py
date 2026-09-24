"""The dashboard: signup, login, chat, usage, approvals, settings.

Session auth via core.auth (opaque token in an HttpOnly cookie), CSRF tokens
on forms, security headers, rate-limited auth routes. The chat view submits
task.requested exactly like Telegram does and streams progress over SSE fed
by the event bus, filtered to the logged-in user's own tasks.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import stripe
from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from core import approvals, auth, billing, db, events, secrets_vault
from core import skills as skills_core
from core.config import ConfigError, settings
from core.logging import get_logger
from gateway import account_linking

logger = get_logger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

COOKIE = "agent_session"
_RATE: dict[str, list[float]] = {}

app = FastAPI(docs_url=None, redoc_url=None)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _rate_limited(key: str, limit: int = 20, window: float = 3600.0) -> bool:
    import time as _time

    now = _time.monotonic()
    stamps = _RATE.setdefault(key, [])
    _RATE[key] = [t for t in stamps if now - t < window]
    if len(_RATE[key]) >= limit:
        return True
    _RATE[key].append(now)
    return False


async def current_user(request: Request) -> db.User | None:
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    user_id = await auth.verify_session(token)
    if user_id is None:
        return None
    return await db.get_user(user_id)


def require_user(user: db.User | None) -> db.User:
    if user is None:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return user


def _csrf_token(user_id: str) -> str:
    import hashlib

    return hashlib.sha256(f"{user_id}:{settings.secrets.session_secret}".encode()).hexdigest()[:32]


def _check_csrf(user_id: str, token: str) -> None:
    if not token or token != _csrf_token(user_id):
        raise HTTPException(status_code=403, detail="bad CSRF token")


def _render(request: Request, template: str, user: db.User | None, **ctx: Any) -> HTMLResponse:
    ctx.update(
        request=request,
        user=user,
        csrf=_csrf_token(str(user.id)) if user else "",
        base_url=settings.secrets.base_url,
    )
    return templates.TemplateResponse(request, template, ctx)


def _secure_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE,
        token,
        max_age=int(auth.SESSION_TTL.total_seconds()),
        httponly=True,
        samesite="lax",
        secure=settings.secrets.base_url.startswith("https"),
        path="/",
    )


# --------------------------------------------------------------------------- #
# auth routes
# --------------------------------------------------------------------------- #


@app.get("/", response_class=HTMLResponse)
async def home(request: Request, user: db.User | None = Depends(current_user)):
    if user:
        return RedirectResponse("/chat", status_code=303)
    return _render(request, "index.html", None)


@app.get("/signup", response_class=HTMLResponse)
async def signup_form(request: Request):
    return _render(request, "signup.html", None, error="")


@app.post("/signup")
async def signup(request: Request, email: str = Form(...), password: str = Form(...)):
    if _rate_limited(f"signup:{request.client.host if request.client else '?'}"):
        return _render(request, "signup.html", None, error="Too many attempts — try later.")
    try:
        await auth.signup(email, password)
    except auth.AuthError as exc:
        return _render(request, "signup.html", None, error=str(exc))
    return _render(request, "check_inbox.html", None, next_action="log in")


@app.get("/verify", response_class=HTMLResponse)
async def verify(request: Request, token: str = ""):
    try:
        await auth.verify_email(token)
        return _render(request, "verified.html", None)
    except auth.AuthError as exc:
        return _render(request, "verify_failed.html", None, error=str(exc))


@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    return _render(request, "login.html", None, error="")


@app.post("/login")
async def login(request: Request, response: Response, email: str = Form(...), password: str = Form(...)):
    ip = request.client.host if request.client else "-"
    if _rate_limited(f"login:{email.lower()}:{ip}"):
        return _render(request, "login.html", None, error="Too many attempts — try later.")
    try:
        result = await auth.login(email, password, ip=ip)
    except auth.AuthError as exc:
        return _render(request, "login.html", None, error=str(exc))
    response = RedirectResponse("/chat", status_code=303)
    _secure_cookie(response, result.token)
    return response


@app.post("/logout")
async def logout(request: Request, user: db.User | None = Depends(current_user)):
    token = request.cookies.get(COOKIE) or ""
    if token:
        await auth.logout(token)
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(COOKIE)
    return response


@app.get("/reset", response_class=HTMLResponse)
async def reset_form(request: Request):
    return _render(request, "reset.html", None, sent=False, error="")


@app.post("/reset")
async def reset(request: Request, email: str = Form(...)):
    if _rate_limited(f"reset:{email.lower()}"):
        return _render(request, "reset.html", None, sent=False, error="Too many attempts.")
    await auth.request_password_reset(email)
    return _render(request, "reset.html", None, sent=True, error="")


@app.post("/reset-confirm")
async def reset_confirm(token: str = Form(...), password: str = Form(...)):
    try:
        await auth.reset_password(token, password)
        return RedirectResponse("/login", status_code=303)
    except auth.AuthError as exc:
        return HTMLResponse(str(exc), status_code=400)


# --------------------------------------------------------------------------- #
# chat / tasks
# --------------------------------------------------------------------------- #


@app.get("/chat", response_class=HTMLResponse)
async def chat(request: Request, user: db.User | None = Depends(current_user)):
    user = require_user(user)
    tasks = await db.list_tasks(user.id, limit=30)
    return _render(request, "chat.html", user, tasks=tasks)


@app.post("/tasks")
async def create_task(
    request: Request,
    user: db.User | None = Depends(current_user),
    request_text: str = Form(...),
    csrf: str = Form(""),
):
    user = require_user(user)
    _check_csrf(str(user.id), csrf)
    request_text = request_text.strip()
    if not request_text:
        raise HTTPException(status_code=400, detail="empty task")
    from core import orchestrator

    if not orchestrator.accepting():
        raise HTTPException(status_code=503, detail="service is shutting down")
    task = await db.create_task(user.id, request_text, source="user")
    await events.publish(
        events.TASK_REQUESTED,
        {"user_id": str(user.id), "task_id": str(task.id), "request": request_text, "source": "user"},
    )
    return RedirectResponse(f"/tasks/{task.id}", status_code=303)


@app.get("/tasks/{task_id}", response_class=HTMLResponse)
async def task_view(task_id: str, request: Request, user: db.User | None = Depends(current_user)):
    user = require_user(user)
    task = await db.get_task(user.id, _uuid(task_id))
    if task is None:
        raise HTTPException(status_code=404, detail="no such task")
    return _render(request, "task.html", user, task=task)


@app.get("/tasks/{task_id}/events")
async def task_events(task_id: str, user: db.User | None = Depends(current_user)):
    """SSE stream of this user's task progress (own tasks only)."""
    user = require_user(user)
    task = await db.get_task(user.id, _uuid(task_id))
    if task is None:
        raise HTTPException(status_code=404, detail="no such task")
    uid, tid = str(user.id), str(task.id)
    queue: asyncio.Queue[dict | None] = asyncio.Queue()

    async def handler(payload: dict) -> None:
        if payload.get("user_id") == uid and payload.get("task_id") == tid:
            queue.put_nowait(payload)

    for name in (events.TASK_PROGRESS, events.TASK_FINISHED):
        await events.subscribe(name, handler)

    async def stream():
        try:
            if task.status in ("done", "failed", "cancelled"):
                yield f'data: {{"status": "{task.status}", "done": true}}\n\n'
                return
            while True:
                payload = await asyncio.wait_for(queue.get(), timeout=300)
                body = {
                    "status": payload.get("status"),
                    "note": payload.get("note") or payload.get("summary") or "",
                    "done": bool(payload.get("status") in ("done", "failed", "cancelled")),
                }
                yield f"data: {_json(body)}\n\n"
                if body["done"]:
                    return
        except TimeoutError:
            yield 'data: {"status": "timeout", "done": true}\n\n'
        finally:
            for name in (events.TASK_PROGRESS, events.TASK_FINISHED):
                await events.unsubscribe(name, handler)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


def _json(payload: dict) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False)


# --------------------------------------------------------------------------- #
# approvals inbox
# --------------------------------------------------------------------------- #


@app.get("/approvals", response_class=HTMLResponse)
async def approvals_inbox(request: Request, user: db.User | None = Depends(current_user)):
    user = require_user(user)
    rows = await db._require_pool().fetch(
        "SELECT * FROM approvals WHERE user_id = $1 ORDER BY created_at DESC LIMIT 50",
        user.id,
    )
    pending = [r for r in rows if r["status"] == "pending"]
    past = [r for r in rows if r["status"] != "pending"]
    return _render(request, "approvals.html", user, pending=pending, past=past)


@app.post("/approvals/{approval_id}/decide")
async def decide_approval(
    approval_id: str,
    request: Request,
    user: db.User | None = Depends(current_user),
    decision: str = Form(...),
    csrf: str = Form(""),
):
    user = require_user(user)
    _check_csrf(str(user.id), csrf)
    approved = decision == "approve"
    ok = await approvals.decide(str(user.id), approval_id, approved)
    if not ok:
        raise HTTPException(status_code=409, detail="not pending or not yours")
    return RedirectResponse("/approvals", status_code=303)


# --------------------------------------------------------------------------- #
# settings: quiet hours, approval overrides, telegram link code, vault stub
# --------------------------------------------------------------------------- #


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    user: db.User | None = Depends(current_user),
    link_code: str | None = None,
):
    user = require_user(user)
    sites = await secrets_vault.list_sites(str(user.id))
    chats = await db.get_chats_for_user(user.id)
    jobs = await db.list_jobs(user.id)
    skills = await skills_core.list_skills(str(user.id))
    purchase_policy = await db.get_purchase_policy(user.id)
    purchase_connection = await db.get_purchase_connection(user.id)
    model_key_saved = await secrets_vault.has_model_api_key(str(user.id))
    return _render(
        request,
        "settings.html",
        user,
        user_settings=user.settings_json or {},
        user_limits=user.user_limits_json or {},
        sites=sites,
        chats=chats,
        jobs=jobs,
        skills=skills,
        purchase_policy=purchase_policy,
        purchase_connection=purchase_connection,
        model_key_saved=model_key_saved,
        operator_model_key_available=bool(settings.secrets.anthropic_api_key),
        link_code=link_code or "",
        saved=request.query_params.get("saved") == "1",
    )


@app.post("/settings/model-key")
async def save_model_key(
    request: Request,
    user: db.User | None = Depends(current_user),
    api_key: str = Form(...),
    csrf: str = Form(""),
):
    user = require_user(user)
    _check_csrf(str(user.id), csrf)
    try:
        await secrets_vault.store_model_api_key(str(user.id), api_key.strip())
    except secrets_vault.VaultError:
        return HTMLResponse("could not save the Anthropic API key", status_code=400)
    return RedirectResponse("/settings?saved=1", status_code=303)


@app.post("/settings/model-key/delete")
async def delete_model_key(
    request: Request,
    user: db.User | None = Depends(current_user),
    csrf: str = Form(""),
):
    user = require_user(user)
    _check_csrf(str(user.id), csrf)
    await secrets_vault.delete_model_api_key(str(user.id))
    return RedirectResponse("/settings?saved=1", status_code=303)


@app.post("/settings/purchases")
async def save_purchase_settings(
    request: Request,
    user: db.User | None = Depends(current_user),
    per_transaction_cap_usd: str = Form("0"),
    monthly_cap_usd: str = Form("0"),
    merchant_allowlist: str = Form(""),
    csrf: str = Form(""),
):
    """Save draft limits only. Without a hosted provider connection no user
    can opt in, and these settings cannot authorize a purchase."""
    from decimal import Decimal, InvalidOperation

    user = require_user(user)
    _check_csrf(str(user.id), csrf)
    try:
        tx = Decimal(per_transaction_cap_usd)
        month = Decimal(monthly_cap_usd)
        if (
            not tx.is_finite()
            or not month.is_finite()
            or tx < 0
            or month < 0
            or tx.as_tuple().exponent < -2
            or month.as_tuple().exponent < -2
            or tx > Decimal("9999999999.99")
            or month > Decimal("9999999999.99")
            or tx > month
        ):
            raise ValueError
    except (InvalidOperation, ValueError):
        return HTMLResponse("invalid purchase caps", status_code=400)
    hosts = [item.strip().lower() for item in merchant_allowlist.splitlines() if item.strip()]
    if len(hosts) > 50 or any(
        len(host) > 200 or not host or "." not in host or any(c in host for c in "/@\\?# :") for host in hosts
    ):
        return HTMLResponse("invalid merchant allowlist", status_code=400)
    await db.save_purchase_policy(user.id, tx, month, sorted(set(hosts)))
    return RedirectResponse("/settings?saved=1", status_code=303)


@app.post("/settings/purchases/opt-in")
async def opt_in_purchases(
    request: Request,
    user: db.User | None = Depends(current_user),
    confirm: str = Form(""),
    csrf: str = Form(""),
):
    """Explicit purchase opt-in. Requires a valid connection AND an explicit
    confirmation — neither alone is enough. There is no provider yet, so this
    route is fail-closed until one exists."""
    user = require_user(user)
    _check_csrf(str(user.id), csrf)
    connection = await db.get_purchase_connection(user.id)
    if connection is None or connection["status"] != "active":
        return HTMLResponse(
            "opt-in requires a connected payment connection (none is available)",
            status_code=409,
        )
    if confirm != "yes":
        return HTMLResponse("opt-in requires the explicit confirmation checkbox", status_code=400)
    await db.set_purchase_opt_in(user.id, True)
    logger.info("purchase opt-in", extra={"user_id": str(user.id)})
    return RedirectResponse("/settings?saved=1", status_code=303)


@app.post("/settings/purchases/opt-out")
async def opt_out_purchases(
    request: Request,
    user: db.User | None = Depends(current_user),
    csrf: str = Form(""),
):
    """Opt out AND disconnect: revokes the connection record and bumps its
    version, so any in-flight purchase bound to the old version can no longer
    claim (the claim re-checks the version before every execution)."""
    user = require_user(user)
    _check_csrf(str(user.id), csrf)
    await db.set_purchase_opt_in(user.id, False)
    await db.revoke_purchase_connection(user.id)
    logger.info("purchase opt-out + disconnect", extra={"user_id": str(user.id)})
    return RedirectResponse("/settings?saved=1", status_code=303)


@app.post("/settings/vault")
async def add_credential(
    request: Request,
    user: db.User | None = Depends(current_user),
    site: str = Form(...),
    username: str = Form(""),
    password: str = Form(""),
    csrf: str = Form(""),
):
    """Store the user's own credential. Values post straight into the vault;
    nothing is ever echoed back (not even on error)."""
    import json as _json

    user = require_user(user)
    _check_csrf(str(user.id), csrf)
    site = site.strip().lower()
    if not site or "/" in site or len(site) > 200:
        return HTMLResponse("invalid site (use a hostname like example.com)", status_code=400)
    if not password:
        return HTMLResponse("password is required", status_code=400)
    value = _json.dumps({"username": username.strip(), "password": password})
    try:
        await secrets_vault.store_credential(str(user.id), site, value)
    except secrets_vault.VaultError:
        return HTMLResponse("could not store the credential", status_code=400)
    return RedirectResponse("/settings", status_code=303)


@app.post("/settings/vault/delete")
async def delete_credential(
    request: Request,
    user: db.User | None = Depends(current_user),
    site: str = Form(...),
    csrf: str = Form(""),
):
    user = require_user(user)
    _check_csrf(str(user.id), csrf)
    await secrets_vault.delete_credential(str(user.id), site.strip().lower())
    return RedirectResponse("/settings", status_code=303)


@app.post("/settings")
async def save_settings(
    request: Request,
    user: db.User | None = Depends(current_user),
    quiet_hours_start: str = Form("22:00"),
    quiet_hours_end: str = Form("08:00"),
    timezone: str = Form("UTC"),
    limits_json: str = Form("{}"),
    csrf: str = Form(""),
):
    import json as _json

    user = require_user(user)
    _check_csrf(str(user.id), csrf)
    try:
        overrides = _json.loads(limits_json) if limits_json.strip() else {}
    except _json.JSONDecodeError:
        return HTMLResponse("limits_json is not valid JSON", status_code=400)
    if overrides and not isinstance(overrides, dict):
        return HTMLResponse("limits_json must be an object", status_code=400)
    try:
        from zoneinfo import ZoneInfo

        ZoneInfo(timezone)
    except Exception:
        return HTMLResponse("unknown timezone (IANA name expected, e.g. Europe/Berlin)", status_code=400)
    # Plan floor is enforced at check-time in core.approvals; here we only
    # sanity-check the shape. Tightening is always allowed.
    await db.update_user(
        user.id,
        settings_json={"quiet_hours": {"start": quiet_hours_start, "end": quiet_hours_end}},
        user_limits_json=overrides or None,
        timezone=timezone,
    )
    return RedirectResponse("/settings?saved=1", status_code=303)


@app.post("/settings/jobs/{job_id}/pause")
async def pause_job_route(
    job_id: str,
    request: Request,
    user: db.User | None = Depends(current_user),
    csrf: str = Form(""),
):
    """Pause the user's OWN job (someone else's id is a no-op 404)."""
    user = require_user(user)
    _check_csrf(str(user.id), csrf)
    job = await db.get_job(user.id, _uuid(job_id))
    if job is None:
        raise HTTPException(status_code=404, detail="no such job")
    await db.update_job(user.id, job.id, active=False)
    await events.publish(
        events.JOB_CHANGED,
        {"user_id": str(user.id), "job_id": str(job.id), "change": "paused"},
    )
    return RedirectResponse("/settings", status_code=303)


@app.post("/settings/jobs/{job_id}/delete")
async def delete_job_route(
    job_id: str,
    request: Request,
    user: db.User | None = Depends(current_user),
    csrf: str = Form(""),
):
    user = require_user(user)
    _check_csrf(str(user.id), csrf)
    job = await db.get_job(user.id, _uuid(job_id))
    if job is None:
        raise HTTPException(status_code=404, detail="no such job")
    if job.check_script_path:
        skills_core.delete_check_script(str(user.id), str(job.id))
    await db.delete_job(user.id, job.id)
    await events.publish(
        events.JOB_CHANGED,
        {"user_id": str(user.id), "job_id": str(job.id), "change": "deleted"},
    )
    return RedirectResponse("/settings", status_code=303)


@app.post("/settings/link-code")
async def new_link_code(
    request: Request,
    user: db.User | None = Depends(current_user),
    csrf: str = Form(""),
):
    user = require_user(user)
    _check_csrf(str(user.id), csrf)
    code = await account_linking.generate_link_code(user.id)
    return RedirectResponse(f"/settings?link_code={code}", status_code=303)


# --------------------------------------------------------------------------- #
# usage and Stripe-hosted billing
# --------------------------------------------------------------------------- #


@app.get("/usage", response_class=HTMLResponse)
async def usage(request: Request, user: db.User | None = Depends(current_user)):
    user = require_user(user)
    await billing.rollup(user.id)
    summary = await billing.usage_this_period(user.id)
    plan = settings.plan_for(summary.plan_tier)
    check = await billing.check_within_limit(user.id)
    pct = float(summary.total_cost / plan.hard_cap_usd * 100) if plan.hard_cap_usd > 0 else 0.0
    offers = {
        tier: value
        for tier, value in settings.plans.tiers.items()
        if tier != summary.plan_tier and value.stripe_price_id
    }
    return _render(
        request,
        "usage.html",
        user,
        summary=summary,
        plan=plan,
        pct=round(min(pct, 100), 1),
        reserved=check.reserved_usd,
        billing_enabled=settings.billing.enabled,
        offers=offers,
        checkout_key=str(uuid4()),
    )


@app.post("/usage/checkout")
async def usage_checkout(
    user: db.User | None = Depends(current_user),
    plan_tier: str = Form(...),
    operation_key: str = Form(...),
    csrf: str = Form(""),
):
    user = require_user(user)
    _check_csrf(str(user.id), csrf)
    try:
        key = str(UUID(operation_key))
        url = await billing.start_checkout(user.id, plan_tier, key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ConfigError as exc:
        raise HTTPException(status_code=503, detail="billing setup is unavailable") from exc
    except stripe.StripeError as exc:
        logger.warning("Stripe checkout failed", extra={"user_id": str(user.id)})
        raise HTTPException(status_code=502, detail="billing provider unavailable") from exc
    return RedirectResponse(url, status_code=303)


@app.post("/usage/portal")
async def usage_portal(
    user: db.User | None = Depends(current_user),
    csrf: str = Form(""),
):
    user = require_user(user)
    _check_csrf(str(user.id), csrf)
    try:
        url = await billing.create_portal_session(user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ConfigError as exc:
        raise HTTPException(status_code=503, detail="billing setup is unavailable") from exc
    except stripe.StripeError as exc:
        logger.warning("Stripe portal failed", extra={"user_id": str(user.id)})
        raise HTTPException(status_code=502, detail="billing provider unavailable") from exc
    return RedirectResponse(url, status_code=303)


@app.get("/usage/success")
async def usage_success(user: db.User | None = Depends(current_user)):
    require_user(user)
    # A Checkout redirect is never proof of a paid subscription. /usage
    # displays only the last verified provider state from the webhook.
    return RedirectResponse("/usage", status_code=303)


@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    if not settings.billing.enabled:
        raise HTTPException(status_code=503, detail="billing is disabled")
    try:
        event = stripe.Webhook.construct_event(
            await request.body(),
            request.headers.get("stripe-signature"),
            settings.require("stripe_webhook_secret"),
        )
    except (ValueError, stripe.SignatureVerificationError) as exc:
        raise HTTPException(status_code=400, detail="invalid Stripe signature") from exc
    await billing.handle_stripe_webhook(event)
    return JSONResponse({"received": True})


@app.get("/healthz")
async def healthz():
    return JSONResponse({"ok": True})


@app.get("/readyz")
async def readyz():
    from core import orchestrator

    if not orchestrator.accepting() or not await db.healthcheck():
        return JSONResponse({"ok": False}, status_code=503)
    return JSONResponse({"ok": True})


def _uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="bad id") from exc
