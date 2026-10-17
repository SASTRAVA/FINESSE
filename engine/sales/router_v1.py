"""Authenticated, tenant-scoped, sandbox-first sales and platform APIs."""
from __future__ import annotations

import time
import re
import hashlib
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..auth.security import decode_token, make_token
from ..auth.users import users
from ..db.storage import storage
from ..knowledge.universal_catalog import REPOSITORY_SEEDS, certify_candidate
from ..mcp.base import mcp
from ..orchestra.langgraph_conjunction import conjunction_engine
from ..orchestra.jobs import jobs
from ..rag.store import store as vector_store
from ..security.toolchain import create_target_challenge, verify_target_challenge
from ..security.toolchain import safe_scan_profile
from ..safety_state import activate_emergency_stop, emergency_stop_active
from .analytics import funnel
from .command_parser import parse_sales_command
from .email_engine import generate_email_draft
from .lead_engine import generate_sandbox_leads
from .models import (
    AgentCommandIn, CampaignCreateIn, CampaignPlanIn, ConsentIn, EmailDraftIn,
    LeadGenerateIn, LoginIn, MemoryPatternIn, VoiceCallIn,
)
from .services_catalog import SERVICES, get_service
from .voice_engine import prepare_voice_call

router = APIRouter(prefix="/api/v1", tags=["enterprise-platform"])
_bearer = HTTPBearer(auto_error=False)
_CAMPAIGN_ROLES = {"CEO", "COO", "Sales Manager", "sales_manager", "admin"}
_READ_ROLES = {"CEO", "COO", "Sales Manager", "Sales Representative", "Analyst",
               "sales_manager", "sales_rep", "analyst", "admin"}


def current_sales_user(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)):
    if credentials is None:
        raise HTTPException(401, "missing token")
    user = decode_token(credentials.credentials)
    if not user:
        raise HTTPException(401, "invalid or expired token")
    return user


def _tenant(user: dict) -> str:
    return str(user.get("tenant_id") or "default")


def _require_role(user: dict, allowed: set[str]) -> None:
    if user.get("role") not in allowed and user.get("tier", 0) < 4:
        raise HTTPException(403, "role is not authorized for this sales action")


def _require_not_stopped() -> None:
    if emergency_stop_active():
        raise HTTPException(503, "platform emergency stop is active")


@router.get("/services")
async def list_services(_user: dict = Depends(current_sales_user)):
    return {"services": list(SERVICES)}


@router.post("/auth/login")
async def sales_login(body: LoginIn):
    from ..main import login_throttle
    account = login_throttle.normalize_account(body.email)
    if not login_throttle.allowed(account=account):
        raise HTTPException(429, "too many login attempts for this account")
    account_user = users.authenticate(body.email, body.password)
    if account_user is None:
        login_throttle.failed(account=account)
        raise HTTPException(401, "bad credentials")
    login_throttle.succeeded(account=account)
    return {"access_token": make_token(account_user.email, account_user.role,
                                       account_user.tier, account_user.tenant_id),
            "token_type": "bearer", "user": account_user.public()}


@router.post("/auth/refresh")
async def refresh_sales_token(user: dict = Depends(current_sales_user)):
    return {"access_token": make_token(user["sub"], user["role"], user.get("tier", 1),
                                       user.get("tenant_id", "default")),
            "token_type": "bearer"}


@router.post("/auth/logout")
async def logout_sales(_user: dict = Depends(current_sales_user)):
    return {"logged_out": True, "detail": "JWT expires according to configured lifetime."}


@router.get("/users/me")
async def sales_user_profile(user: dict = Depends(current_sales_user)):
    record = users.get(user["sub"])
    if record is None:
        raise HTTPException(404, "user not found")
    return record.public()


@router.get("/services/{service_id}")
async def service_details(service_id: str, _user: dict = Depends(current_sales_user)):
    service = get_service(service_id)
    if service is None:
        raise HTTPException(404, "service not found")
    return service


@router.get("/icps")
async def list_icps(_user: dict = Depends(current_sales_user)):
    return {"icps": []}


@router.post("/agent/commands")
async def agent_command(body: AgentCommandIn, user: dict = Depends(current_sales_user)):
    _require_not_stopped()
    _require_role(user, _READ_ROLES)
    parsed = parse_sales_command(body.command, tainted=body.tainted)
    if parsed["status"] != "parsed":
        return parsed
    if parsed["action"] == "lead_generation":
        _require_role(user, _CAMPAIGN_ROLES | {"Sales Representative", "sales_rep"})
        leads = generate_sandbox_leads(
            service_id=parsed["service_id"], geography=parsed["geography"],
            tenant_id=_tenant(user))
        for lead in leads:
            storage.put("leads", _tenant(user), lead["id"], lead)
        return {"status": "completed", "sandbox": True, "leads": leads}
    return {"status": "awaiting_approval", "sandbox": True, **parsed}


@router.post("/orchestra/conjunction")
async def run_conjunction(body: AgentCommandIn, user: dict = Depends(current_sales_user)):
    _require_not_stopped()
    state = await conjunction_engine.run(
        directive=body.command, actor_sub=user["sub"], actor_role=user["role"],
        tenant_id=_tenant(user), allowed_lanes=[user.get("role", "general")],
        sensitivity=body.sensitivity, tainted=body.tainted)
    return dict(state)


@router.post("/memory/patterns")
async def learn_memory_pattern(body: MemoryPatternIn,
                               user: dict = Depends(current_sales_user)):
    _require_role(user, _READ_ROLES)
    if not body.human_confirmed:
        raise HTTPException(400, "explicit human confirmation is required")
    from ..auth.rbac import role_of
    from ..orchestra.memory import shared_memory
    lane = role_of(user["role"]).lane
    confidence = await shared_memory.learn_pattern(
        pattern=body.pattern, role=user["role"], actor=user["sub"],
        user_id=user["sub"], lane=lane, sensitivity=body.sensitivity,
        tenant_id=_tenant(user), tainted=False)
    return {"recorded": True, "confidence": confidence, "tainted": False}


@router.post("/leads/generate")
async def generate_leads_route(body: LeadGenerateIn,
                               user: dict = Depends(current_sales_user)):
    _require_not_stopped()
    _require_role(user, _CAMPAIGN_ROLES | {"Sales Representative", "sales_rep"})
    leads = generate_sandbox_leads(
        service_id=body.service_id, geography=body.geography, industry=body.industry,
        count=body.count, tenant_id=_tenant(user))
    for lead in leads:
        storage.put("leads", _tenant(user), lead["id"], lead)
    return {"sandbox": True, "leads": leads}


@router.post("/campaigns/plan")
async def plan_campaign(body: CampaignPlanIn, user: dict = Depends(current_sales_user)):
    _require_role(user, _CAMPAIGN_ROLES | {"Sales Representative", "sales_rep"})
    leads = generate_sandbox_leads(
        service_id=body.service_id, geography=body.geography, industry=body.industry,
        count=body.count, tenant_id=_tenant(user))
    return {"status": "draft", "sandbox": True, "name": body.name,
            "service_id": body.service_id, "lead_preview": leads}


@router.post("/campaigns")
async def create_campaign(body: CampaignCreateIn, user: dict = Depends(current_sales_user)):
    _require_role(user, _CAMPAIGN_ROLES | {"Sales Representative", "sales_rep"})
    if get_service(body.service_id) is None:
        raise HTTPException(400, "unknown service")
    for lead_id in body.lead_ids:
        lead = storage.get("leads", _tenant(user), lead_id)
        if lead is None:
            raise HTTPException(404, "campaign contains an unknown lead")
        if lead.get("service_id") != body.service_id:
            raise HTTPException(400, "campaign lead does not match service")
    campaign_id = str(time.time_ns())
    campaign = {"id": campaign_id, "tenant_id": _tenant(user), "name": body.name,
                "service_id": body.service_id, "lead_ids": body.lead_ids,
                "status": "draft", "delivery_enabled": False,
                "created_by": user["sub"]}
    storage.put("campaigns", _tenant(user), campaign_id, campaign)
    return campaign


@router.get("/campaigns")
async def list_campaigns(user: dict = Depends(current_sales_user)):
    _require_role(user, _READ_ROLES)
    return {"campaigns": storage.list("campaigns", _tenant(user), limit=1000)}


@router.get("/campaigns/{campaign_id}")
async def get_campaign(campaign_id: str, user: dict = Depends(current_sales_user)):
    campaign = storage.get("campaigns", _tenant(user), campaign_id)
    if campaign is None:
        raise HTTPException(404, "campaign not found")
    return campaign


def _campaign_transition(user: dict, campaign_id: str, target: str,
                         allowed: set[str]) -> dict:
    campaign = storage.get("campaigns", _tenant(user), campaign_id)
    if campaign is None:
        raise HTTPException(404, "campaign not found")
    if campaign["status"] not in allowed:
        raise HTTPException(409, f"campaign cannot move from {campaign['status']} to {target}")
    campaign["status"] = target
    campaign["updated_at"] = time.time()
    storage.put("campaigns", _tenant(user), campaign_id, campaign)
    return campaign


@router.post("/campaigns/{campaign_id}/approve")
async def approve_campaign(campaign_id: str, user: dict = Depends(current_sales_user)):
    _require_role(user, _CAMPAIGN_ROLES)
    return _campaign_transition(user, campaign_id, "approved", {"draft", "paused"})


@router.post("/campaigns/{campaign_id}/pause")
async def pause_campaign(campaign_id: str, user: dict = Depends(current_sales_user)):
    _require_role(user, _CAMPAIGN_ROLES)
    return _campaign_transition(user, campaign_id, "paused", {"approved", "dry_run_queued"})


@router.post("/campaigns/{campaign_id}/resume")
async def resume_campaign(campaign_id: str, user: dict = Depends(current_sales_user)):
    _require_role(user, _CAMPAIGN_ROLES)
    return _campaign_transition(user, campaign_id, "approved", {"paused"})


@router.post("/campaigns/{campaign_id}/cancel")
async def cancel_campaign(campaign_id: str, user: dict = Depends(current_sales_user)):
    _require_role(user, _CAMPAIGN_ROLES)
    return _campaign_transition(
        user, campaign_id, "cancelled", {"draft", "approved", "paused", "dry_run_queued"})


@router.post("/campaigns/{campaign_id}/match-services")
async def match_campaign_services(campaign_id: str, user: dict = Depends(current_sales_user)):
    campaign = storage.get("campaigns", _tenant(user), campaign_id)
    if campaign is None:
        raise HTTPException(404, "campaign not found")
    service = get_service(campaign["service_id"])
    return {"campaign_id": campaign_id, "matches": [service] if service else []}


@router.get("/leads")
async def list_leads(user: dict = Depends(current_sales_user)):
    _require_role(user, _READ_ROLES)
    return {"leads": storage.list("leads", _tenant(user), limit=1000)}


@router.get("/leads/search")
async def search_leads(q: str, user: dict = Depends(current_sales_user)):
    _require_role(user, _READ_ROLES)
    query = q.casefold().strip()
    rows = storage.list("leads", _tenant(user), limit=1000)
    return {"leads": [lead for lead in rows if query in
                      f"{lead.get('company', '')} {lead.get('industry', '')} "
                      f"{lead.get('geography', '')}".casefold()]}


@router.post("/leads/bulk-import")
async def bulk_import_leads(body: dict, user: dict = Depends(current_sales_user)):
    _require_role(user, _CAMPAIGN_ROLES | {"Sales Representative", "sales_rep"})
    if not body.get("authorization_confirmed"):
        raise HTTPException(403, "authorization to import the supplied records is required")
    records = body.get("leads")
    if not isinstance(records, list) or len(records) > 500:
        raise HTTPException(422, "leads must be a list of at most 500 records")
    imported, seen = [], set()
    for item in records:
        if not isinstance(item, dict):
            raise HTTPException(422, "each lead record must be an object")
        domain = str(item.get("domain", "")).strip().casefold()
        if not re.fullmatch(r"[a-z0-9.-]{1,253}", domain):
            raise HTTPException(422, "each lead requires a valid domain")
        if domain in seen:
            continue
        seen.add(domain)
        lead_id = hashlib.sha256(f"{_tenant(user)}:{domain}".encode()).hexdigest()[:20]
        lead = {
            "id": lead_id, "tenant_id": _tenant(user),
            "company": str(item.get("company", ""))[:200],
            "domain": domain, "name": str(item.get("name", ""))[:120],
            "email": str(item.get("email", ""))[:320],
            "service_id": str(item.get("service_id", ""))[:80],
            "status": "discovered", "fit_score": 0,
            "source_metadata": {"provider": "authorized_user_import",
                                "verified": False, "record_type": "unverified"},
            "eligible_for_outreach": False,
        }
        storage.put("leads", _tenant(user), lead_id, lead)
        imported.append(lead_id)
    return {"imported": len(imported), "lead_ids": imported}


@router.get("/leads/export")
async def export_leads(include_contact_data: bool = False,
                       user: dict = Depends(current_sales_user)):
    _require_role(user, _CAMPAIGN_ROLES)
    if include_contact_data and user.get("tier", 0) < 3:
        raise HTTPException(403, "contact-data export is restricted to executives")
    fields = ("id", "company", "domain", "service_id", "status", "fit_score")
    if include_contact_data:
        fields += ("name", "email")
    records = storage.list("leads", _tenant(user), limit=1000)
    return {"leads": [{key: item.get(key) for key in fields} for item in records]}


@router.get("/leads/{lead_id}")
async def get_lead(lead_id: str, user: dict = Depends(current_sales_user)):
    lead = storage.get("leads", _tenant(user), lead_id)
    if lead is None:
        raise HTTPException(404, "lead not found")
    return lead


@router.post("/leads/{lead_id}/enrich")
async def enrich_lead(lead_id: str, user: dict = Depends(current_sales_user)):
    _require_role(user, _CAMPAIGN_ROLES | {"Sales Representative", "sales_rep"})
    lead = storage.get("leads", _tenant(user), lead_id)
    if lead is None:
        raise HTTPException(404, "lead not found")
    return {"status": "source_only", "enriched": False,
            "detail": "No external enrichment provider is configured."}


@router.post("/leads/{lead_id}/verify")
async def verify_lead(lead_id: str, user: dict = Depends(current_sales_user)):
    _require_role(user, _CAMPAIGN_ROLES | {"Sales Representative", "sales_rep"})
    lead = storage.get("leads", _tenant(user), lead_id)
    if lead is None:
        raise HTTPException(404, "lead not found")
    return {"verified": False, "status": "unknown",
            "detail": "Synthetic sandbox contact data is intentionally unverified."}


@router.post("/leads/{lead_id}/score")
async def rescore_lead(lead_id: str, user: dict = Depends(current_sales_user)):
    lead = storage.get("leads", _tenant(user), lead_id)
    if lead is None:
        raise HTTPException(404, "lead not found")
    return {"score": lead.get("fit_score", 0), "components": lead.get("score_components", {})}


@router.post("/leads/{lead_id}/approve")
async def approve_lead(lead_id: str, user: dict = Depends(current_sales_user)):
    _require_role(user, _CAMPAIGN_ROLES)
    lead = storage.get("leads", _tenant(user), lead_id)
    if lead is None:
        raise HTTPException(404, "lead not found")
    if lead.get("source_metadata", {}).get("verified") is not True:
        raise HTTPException(409, "unverified sandbox leads cannot be approved for outreach")
    lead["eligible_for_outreach"] = True
    lead["status"] = "eligible"
    storage.put("leads", _tenant(user), lead_id, lead)
    return lead



@router.post("/email/generate")
async def draft_email(body: EmailDraftIn, user: dict = Depends(current_sales_user)):
    _require_not_stopped()
    _require_role(user, _CAMPAIGN_ROLES | {"Sales Representative", "sales_rep"})
    lead = storage.get("leads", _tenant(user), body.lead_id)
    if lead is None:
        raise HTTPException(404, "lead not found")
    try:
        draft = generate_email_draft(lead, body.service_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    message_id = f"{body.lead_id}:{body.service_id}"
    storage.put("email_messages", _tenant(user), message_id,
                {"id": message_id, "lead_id": body.lead_id, **draft})
    return {"id": message_id, **draft}


@router.get("/email/templates")
async def email_templates(user: dict = Depends(current_sales_user)):
    _require_role(user, _READ_ROLES)
    return {"templates": [{"service_id": service["id"], "template": service["template"]}
                          for service in SERVICES]}


@router.post("/email/generate-batch")
async def generate_email_batch(body: dict, user: dict = Depends(current_sales_user)):
    _require_role(user, _CAMPAIGN_ROLES | {"Sales Representative", "sales_rep"})
    campaign = storage.get("campaigns", _tenant(user), str(body.get("campaign_id", "")))
    if campaign is None:
        raise HTTPException(404, "campaign not found")
    messages = []
    for lead_id in campaign["lead_ids"]:
        lead = storage.get("leads", _tenant(user), lead_id)
        if lead is None:
            continue
        draft = generate_email_draft(lead, campaign["service_id"])
        message_id = f"{campaign['id']}:{lead_id}"
        record = {"id": message_id, "campaign_id": campaign["id"],
                  "lead_id": lead_id, **draft}
        storage.put("email_messages", _tenant(user), message_id, record)
        messages.append(record)
    return {"status": "draft", "messages": messages}


@router.post("/email/campaigns/{campaign_id}/start")
async def start_email_campaign(campaign_id: str, user: dict = Depends(current_sales_user)):
    _require_not_stopped()
    _require_role(user, _CAMPAIGN_ROLES)
    campaign = storage.get("campaigns", _tenant(user), campaign_id)
    if campaign is None:
        raise HTTPException(404, "campaign not found")
    if campaign.get("status") != "approved":
        raise HTTPException(409, "campaign approval is required")
    campaign["status"] = "dry_run_queued"
    campaign["delivery_enabled"] = False
    storage.put("campaigns", _tenant(user), campaign_id, campaign)
    return {"status": campaign["status"], "sent": False, "dry_run": True}


@router.post("/email/unsubscribe")
async def unsubscribe_email(body: dict, user: dict = Depends(current_sales_user)):
    contact_id = str(body.get("contact_id", ""))
    if not contact_id:
        raise HTTPException(422, "contact_id is required")
    from .compliance import suppress_contact
    suppress_contact(_tenant(user), contact_id, reason="unsubscribe")
    return {"unsubscribed": True, "suppressed": True}


@router.post("/webhooks/email/events")
async def email_event(body: dict, user: dict = Depends(current_sales_user)):
    _require_role(user, _READ_ROLES)
    event_id, message_id = str(body.get("event_id", "")), str(body.get("message_id", ""))
    event = str(body.get("event", ""))
    if not event_id or not message_id:
        raise HTTPException(422, "event_id and message_id are required")
    if event not in {"sent", "delivered", "bounced", "replied", "complained"}:
        raise HTTPException(422, "unknown email event")
    if storage.get("email_events", _tenant(user), event_id):
        return {"accepted": True, "duplicate": True}
    message = storage.get("email_messages", _tenant(user), message_id)
    if message is None:
        raise HTTPException(404, "message not found")
    rank = {"draft": 0, "sent": 1, "delivered": 2, "replied": 3,
            "bounced": 3, "complained": 4}
    if rank[event] >= rank.get(message["status"], 0):
        message["status"] = event
        storage.put("email_messages", _tenant(user), message_id, message)
    storage.put("email_events", _tenant(user), event_id,
                {"id": event_id, "message_id": message_id, "event": event})
    return {"accepted": True, "duplicate": False}


@router.post("/email/preview")
async def preview_email(body: EmailDraftIn, user: dict = Depends(current_sales_user)):
    return await draft_email(body, user)


@router.get("/email/messages")
async def list_email_messages(user: dict = Depends(current_sales_user)):
    _require_role(user, _READ_ROLES)
    return {"messages": storage.list("email_messages", _tenant(user), limit=1000)}


@router.get("/email/messages/{message_id}")
async def get_email_message(message_id: str, user: dict = Depends(current_sales_user)):
    message = storage.get("email_messages", _tenant(user), message_id)
    if message is None:
        raise HTTPException(404, "message not found")
    return message


@router.post("/webhooks/email/replies")
async def receive_email_reply(body: dict, user: dict = Depends(current_sales_user)):
    event_id = str(body.get("event_id", ""))
    if not event_id:
        raise HTTPException(422, "event_id is required")
    if storage.get("email_events", _tenant(user), event_id):
        return {"accepted": True, "duplicate": True}
    storage.put("email_events", _tenant(user), event_id, {
        "id": event_id, "event": "replied", "tainted": True,
        "content_received": bool(body.get("body")),
    })
    return {"accepted": True, "tainted": True, "campaign_triggered": False}


@router.post("/email/send")
async def send_email_dry_run(body: dict, user: dict = Depends(current_sales_user)):
    _require_not_stopped()
    _require_role(user, _CAMPAIGN_ROLES)
    if body.get("tainted"):
        raise HTTPException(400, "untrusted context cannot initiate email delivery")
    return {"status": "dry_run_only", "sent": False,
            "detail": "No live email provider is configured by this safe-foundations build."}


@router.post("/voice/calls")
async def voice_call(body: VoiceCallIn, user: dict = Depends(current_sales_user)):
    _require_not_stopped()
    _require_role(user, _CAMPAIGN_ROLES)
    lead = storage.get("leads", _tenant(user), body.lead_id)
    if lead is None:
        raise HTTPException(404, "lead not found")
    parsed = parse_sales_command(body.command)
    if (parsed.get("status") != "parsed" or parsed.get("action") != "voice_call"
            or parsed.get("service_id") != body.service_id):
        raise HTTPException(400, "a matching explicit voice command is required")
    try:
        result = prepare_voice_call(
            lead=lead, service_id=body.service_id, tenant_id=_tenant(user),
            authorized_role=True, explicit_command=True, confirmed=body.confirmed,
            consent_confirmed=body.consent_confirmed, approved_script=body.approved_script,
            handoff_requested=body.handoff_requested, local_hour=datetime.now().hour)
    except (PermissionError, ValueError) as exc:
        raise HTTPException(403, str(exc)) from exc
    call_id = f"{lead['id']}:{time.time_ns()}"
    storage.put("calls", _tenant(user), call_id, {"id": call_id, **result})
    return {"id": call_id, **result}


@router.post("/voice/commands")
async def voice_command(body: AgentCommandIn, user: dict = Depends(current_sales_user)):
    _require_role(user, _CAMPAIGN_ROLES)
    parsed = parse_sales_command(body.command, tainted=body.tainted)
    if parsed.get("action") != "voice_call" or parsed["status"] != "parsed":
        return parsed if parsed["status"] != "parsed" else {
            "status": "rejected", "reason": "an explicit voice command is required"}
    return {"status": "awaiting_confirmation", "call_started": False, **parsed}


@router.post("/voice/campaigns/{campaign_id}/start")
async def start_voice_campaign(campaign_id: str, body: dict,
                               user: dict = Depends(current_sales_user)):
    _require_not_stopped()
    _require_role(user, _CAMPAIGN_ROLES)
    campaign = storage.get("campaigns", _tenant(user), campaign_id)
    if campaign is None:
        raise HTTPException(404, "campaign not found")
    parsed = parse_sales_command(str(body.get("command", "")),
                                 tainted=bool(body.get("tainted")))
    if (parsed.get("status") != "parsed" or parsed.get("action") != "voice_call"
            or not body.get("confirmed")):
        return {"status": "awaiting_confirmation", "calls_started": 0}
    return {"status": "dry_run_only", "calls_started": 0,
            "detail": "Live telephony is not configured in the safe-foundations build."}


@router.get("/voice/calls/{call_id}")
async def get_voice_call(call_id: str, user: dict = Depends(current_sales_user)):
    record = storage.get("calls", _tenant(user), call_id)
    if record is None:
        raise HTTPException(404, "call not found")
    return record


@router.post("/voice/calls/{call_id}/hangup")
async def hangup_voice_call(call_id: str, user: dict = Depends(current_sales_user)):
    _require_role(user, _CAMPAIGN_ROLES)
    record = storage.get("calls", _tenant(user), call_id)
    if record is None:
        raise HTTPException(404, "call not found")
    record["status"] = "cancelled"
    record["call_placed"] = False
    storage.put("calls", _tenant(user), call_id, record)
    return record


@router.post("/voice/calls/{call_id}/transfer")
async def transfer_voice_call(call_id: str, body: dict,
                              user: dict = Depends(current_sales_user)):
    _require_role(user, _CAMPAIGN_ROLES)
    record = storage.get("calls", _tenant(user), call_id)
    if record is None:
        raise HTTPException(404, "call not found")
    record["human_handoff"] = "requested"
    storage.put("calls", _tenant(user), call_id, record)
    activity_id = f"{call_id}:handoff"
    storage.put("activities", _tenant(user), activity_id, {
        "id": activity_id, "type": "human_handoff", "actor_sub": user["sub"],
        "notes": str(body.get("notes", ""))[:500]})
    return {"transferred": True, "call_placed": False, "activity_id": activity_id}


@router.post("/voice/calls/{call_id}/summarize")
async def summarize_voice_call(call_id: str, body: dict,
                               user: dict = Depends(current_sales_user)):
    record = storage.get("calls", _tenant(user), call_id)
    if record is None:
        raise HTTPException(404, "call not found")
    record["summary"] = str(body.get("summary", ""))[:2000]
    record["summary_tainted"] = True
    storage.put("calls", _tenant(user), call_id, record)
    return {"id": call_id, "summary_tainted": True}


@router.post("/webhooks/voice/events")
async def voice_event(body: dict, user: dict = Depends(current_sales_user)):
    event_id = str(body.get("event_id", ""))
    if not event_id:
        raise HTTPException(422, "event_id is required")
    if storage.get("email_events", _tenant(user), "voice:" + event_id):
        return {"accepted": True, "duplicate": True}
    storage.put("email_events", _tenant(user), "voice:" + event_id,
                {"id": "voice:" + event_id, "type": "voice_event",
                 "event": str(body.get("event", ""))[:60]})
    return {"accepted": True, "duplicate": False}


@router.post("/webhooks/voice/transcripts")
async def voice_transcript(body: dict, user: dict = Depends(current_sales_user)):
    transcript = str(body.get("transcript", ""))
    return {"received": bool(transcript), "tainted": True, "campaign_triggered": False}


@router.post("/webhooks/voice/recordings")
async def voice_recording(_body: dict, _user: dict = Depends(current_sales_user)):
    raise HTTPException(501, "recording ingestion is disabled in the safe-foundations build")


@router.get("/voice/sessions")
async def voice_sessions(user: dict = Depends(current_sales_user)):
    return {"sessions": storage.list("calls", _tenant(user), limit=500)}


@router.get("/analytics/funnel")
async def analytics_funnel(user: dict = Depends(current_sales_user)):
    _require_role(user, _READ_ROLES)
    return funnel(_tenant(user))


@router.get("/analytics/overview")
async def analytics_overview(user: dict = Depends(current_sales_user)):
    _require_role(user, _READ_ROLES)
    return {"funnel": funnel(_tenant(user)),
            "campaigns": len(storage.list("campaigns", _tenant(user), limit=1000))}


@router.get("/analytics/campaigns/{campaign_id}")
async def campaign_analytics(campaign_id: str, user: dict = Depends(current_sales_user)):
    campaign = storage.get("campaigns", _tenant(user), campaign_id)
    if campaign is None:
        raise HTTPException(404, "campaign not found")
    return {"campaign_id": campaign_id, "status": campaign["status"],
            "lead_count": len(campaign.get("lead_ids", [])),
            "delivery_enabled": False}


@router.get("/audit-logs")
async def audit_logs(user: dict = Depends(current_sales_user)):
    _require_role(user, _READ_ROLES)
    return {"audit_logs": storage.list("audit_logs", _tenant(user), limit=1000)}


@router.get("/jobs/dlq")
async def list_dead_letter_jobs(user: dict = Depends(current_sales_user)):
    _require_role(user, _CAMPAIGN_ROLES)
    return {"queue": [record for record in storage.list("jobs", _tenant(user), limit=1000)
                      if record.get("status") == "dead_letter"]}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, user: dict = Depends(current_sales_user)):
    job = jobs.get(_tenant(user), job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return job.__dict__


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, user: dict = Depends(current_sales_user)):
    try:
        return jobs.cancel(_tenant(user), job_id).__dict__
    except KeyError as exc:
        raise HTTPException(404, "job not found") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/calendar/slots")
async def calendar_slots(_user: dict = Depends(current_sales_user)):
    return {"available": False, "slots": [],
            "detail": "No calendar provider is configured."}


@router.get("/calendar/meetings")
async def calendar_meetings(user: dict = Depends(current_sales_user)):
    return {"meetings": storage.list("meetings", _tenant(user), limit=1000)}


@router.post("/compliance/check")
async def compliance_check(body: dict, user: dict = Depends(current_sales_user)):
    contact_id = str(body.get("contact_id", ""))
    consent = storage.get("consent_records", _tenant(user), contact_id)
    suppressed = storage.get("suppression_entries", _tenant(user), contact_id)
    return {"eligible": bool(consent and consent.get("consented") and not suppressed),
            "consented": bool(consent and consent.get("consented")),
            "suppressed": bool(suppressed)}


@router.get("/suppression-list")
async def suppression_list(user: dict = Depends(current_sales_user)):
    return {"items": storage.list("suppression_entries", _tenant(user), limit=1000)}


@router.get("/catalog/repositories")
async def catalog_repositories(user: dict = Depends(current_sales_user)):
    _require_role(user, _READ_ROLES)
    return {"repositories": list(REPOSITORY_SEEDS)}


@router.post("/catalog/repositories/certify")
async def certify_repository(body: dict, user: dict = Depends(current_sales_user)):
    _require_role(user, {"CEO", "Security Auditor"})
    name = str(body.get("full_name", ""))
    if not re.fullmatch(
            r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}", name):
        raise HTTPException(422, "full_name must use owner/repository syntax")
    evidence = body.get("evidence", {})
    if not isinstance(evidence, dict):
        raise HTTPException(422, "evidence must be an object")
    result = certify_candidate(evidence)
    storage.put("catalog_repositories", _tenant(user), name,
                {"full_name": name, **result})
    return {"full_name": name, **result}


@router.get("/memory/patterns")
async def memory_patterns(user: dict = Depends(current_sales_user)):
    owner = user["sub"]
    macros = [tool.name for tool in mcp.all()
              if tool.name.startswith("learned_macro_")
              and getattr(tool, "tenant_id", None) == _tenant(user)
              and (getattr(tool, "owner_sub", None) == owner
                   or user.get("role") in {"CEO", "COO"})]
    return {"learned_macro_tools": macros, "items": []}


@router.post("/security/verify-target")
async def security_verify_target(body: dict, user: dict = Depends(current_sales_user)):
    _require_role(user, _CAMPAIGN_ROLES | {"Security Auditor"})
    domain = str(body.get("domain", ""))
    observed = body.get("observed_value")
    if not observed:
        challenge = create_target_challenge(domain)
        storage.put("gatekeeper_approvals", _tenant(user), "target:" + challenge["domain"], {
            "id": "target:" + challenge["domain"], "domain": challenge["domain"],
            "challenge": challenge, "verified": False,
        })
        return {"challenge": challenge, "verified": False}
    challenge = body.get("challenge")
    if not isinstance(challenge, dict):
        raise HTTPException(422, "challenge object is required")
    source = body.get("source", "")
    verified = verify_target_challenge(challenge, str(observed), source=source)
    if verified and challenge.get("domain") == domain.rstrip(".").lower():
        storage.put("gatekeeper_approvals", _tenant(user), "target:" + domain.lower(), {
            "id": "target:" + domain.lower(), "domain": domain.lower(),
            "verified": True, "expires_at": int(challenge["issued_at"]) + 900,
        })
    return {"verified": verified}


@router.post("/security/scans")
async def prepare_security_scan(body: dict, user: dict = Depends(current_sales_user)):
    _require_not_stopped()
    _require_role(user, {"CEO", "COO", "Security Auditor"})
    domain = str(body.get("domain", "")).rstrip(".").lower()
    authorization = storage.get(
        "gatekeeper_approvals", _tenant(user), "target:" + domain) if domain else None
    if (not body.get("authorization_confirmed") or not authorization
            or not authorization.get("verified")
            or authorization.get("expires_at", 0) < time.time()):
        raise HTTPException(403, "verified target ownership and written authorization are required")
    if not body.get("safe_harbor_attested") or not body.get("rfc9116_attested"):
        raise HTTPException(403, "safe-harbor and RFC 9116 attestations are required")
    tool_name = str(body.get("tool", "nuclei"))
    try:
        args = safe_scan_profile(tool_name, list(body.get("args", [])))
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc)) from exc
    scan_id = str(time.time_ns())
    scan = {"id": scan_id, "status": "AUTHORIZED_DRY_RUN_PLAN", "executed": False,
            "registered_tools": 16, "tool": tool_name, "args": args, "dry_run": True}
    storage.put("scan_tasks", _tenant(user), scan_id, scan)
    return scan


@router.get("/security/tools")
async def security_tools(user: dict = Depends(current_sales_user)):
    _require_role(user, {"CEO", "COO", "Security Auditor"})
    from ..security.toolchain import SECURITY_TOOLS
    return {"tools": [tool.__dict__ for tool in SECURITY_TOOLS]}


@router.post("/admin/emergency-stop")
async def emergency_stop(user: dict = Depends(current_sales_user)):
    _require_role(user, {"CEO"})
    activate_emergency_stop()
    return {"active": True}


@router.post("/privacy/consent")
async def record_consent(body: ConsentIn, user: dict = Depends(current_sales_user)):
    record = {"contact_id": body.contact_id, "purpose": body.purpose,
              "consented": body.consented, "actor_sub": user["sub"],
              "evidence_reference": body.evidence_reference,
              "recorded_at": time.time()}
    storage.put("consent_records", _tenant(user), body.contact_id, record)
    if not body.consented:
        from .compliance import suppress_contact
        suppress_contact(_tenant(user), body.contact_id, reason="consent_withdrawn")
    return {"recorded": True, "consented": record["consented"]}


@router.delete("/privacy/tenant-data")
async def erase_tenant_data(body: dict, user: dict = Depends(current_sales_user)):
    _require_role(user, {"CEO", "COO"})
    if body.get("confirm_tenant_id") != _tenant(user):
        raise HTTPException(400, "explicit matching tenant confirmation is required")
    if user.get("sub") != body.get("actor_sub"):
        raise HTTPException(403, "requesting actor confirmation did not match")
    deleted = storage.delete_tenant(_tenant(user))
    vectors_deleted = await vector_store.delete_tenant(_tenant(user))
    return {"deleted_records": deleted, "deleted_vectors": vectors_deleted,
            "tenant_id": _tenant(user)}
