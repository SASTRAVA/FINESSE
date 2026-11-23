"""Tenant-bound SCIM 2.0 user and role-group provisioning endpoints."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import re
import secrets
import time
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..auth.rbac import ROLES
from ..auth.users import User, users
from ..db.storage import storage
from ..audit.pg_audit import audit_log

router = APIRouter(tags=["SCIM 2.0"])
_bearer = HTTPBearer(auto_error=False)
SCIM_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
SCIM_LIST_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
_INDEX_TENANT = "__system__"
_FILTER = re.compile(r'^userName\s+eq\s+"([^"]{1,320})"$', re.IGNORECASE)


def _scim_error(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, media_type="application/scim+json",
                        content={"schemas": ["urn:ietf:params:scim:api:messages:2.0:Error"],
                                 "status": str(status), "detail": detail})


def scim_context(request: Request,
                 credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)
                 ) -> tuple[str, dict]:
    authorization = ("Bearer " + credentials.credentials
                     if isinstance(credentials, HTTPAuthorizationCredentials) else
                     request.headers.get("authorization", ""))
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "SCIM bearer token required",
                            headers={"WWW-Authenticate": "Bearer"})
    raw = authorization[7:].strip()
    if len(raw) < 32 or len(raw) > 256:
        raise HTTPException(401, "invalid SCIM bearer token")
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    index = storage.get("scim_token_index", _INDEX_TENANT, digest)
    if not index or not hmac.compare_digest(str(index.get("token_hash", "")), digest):
        raise HTTPException(401, "invalid SCIM bearer token")
    tenant_id, token_id = index.get("target_tenant_id"), index.get("token_id")
    record = storage.get("scim_tokens", str(tenant_id), str(token_id))
    now = time.time()
    if (not record or record.get("revoked_at") or record.get("expires_at", 0) <= now
            or not hmac.compare_digest(str(record.get("token_hash", "")), digest)):
        raise HTTPException(401, "invalid or revoked SCIM bearer token")
    record["last_used_at"] = now
    storage.put("scim_tokens", str(tenant_id), str(token_id), record)
    return str(tenant_id), record


def _user_resource(user: User) -> dict:
    return {
        "schemas": [SCIM_SCHEMA], "id": user.email, "userName": user.email,
        "displayName": user.name, "active": bool(user.active),
        "name": {"formatted": user.name}, "groups": [{"display": user.role}],
        "meta": {"resourceType": "User", "lastModified": user.created,
                 "location": f"/scim/v2/Users/{user.email}"},
    }


def _user(email: str, tenant_id: str) -> User:
    result = users.get(unquote(email).lower(), tenant_id)
    if result is None:
        raise HTTPException(404, "SCIM user not found")
    return result


def _role_from_groups(groups) -> str | None:
    if not isinstance(groups, list):
        raise HTTPException(400, "groups must be an array")
    for group in groups:
        display = group.get("display") if isinstance(group, dict) else None
        if display in ROLES and display != "CEO":
            return display
    return None


async def _revoke_user_sessions(tenant_id: str, email: str) -> int:
    count = 0
    for jti, session in storage.list_items("auth_sessions", tenant_id, limit=1000):
        if session.get("sub", "").casefold() != email.casefold():
            continue
        if session.get("status") == "REVOKED":
            continue
        session["status"] = "REVOKED"
        storage.put("auth_sessions", tenant_id, jti, session)
        storage.put("revoked_sessions", tenant_id, jti, {
            "status": "REVOKED", "sub": email,
            "expires_at": session.get("expires_at", int(time.time())),
        })
        count += 1
    return count


async def _audit(tenant_id: str, action: str, actor: str, subject: str) -> None:
    await asyncio.to_thread(audit_log.append, tenant_id, {
        "action": action, "actor": actor, "subject": subject,
    })


@router.get("/scim/v2/ServiceProviderConfig", dependencies=[Depends(scim_context)])
async def service_provider_config(request: Request):
    scim_context(request)
    return {"schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
            "patch": {"supported": True}, "filter": {"supported": True, "maxResults": 1000},
            "changePassword": {"supported": False}, "sort": {"supported": False},
            "etag": {"supported": False}, "authenticationSchemes": [
                {"type": "oauthbearertoken", "name": "Tenant SCIM bearer token"}]}


@router.get("/scim/v2/Schemas", dependencies=[Depends(scim_context)])
async def schemas(request: Request):
    scim_context(request)
    return {"schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
            "totalResults": 1, "startIndex": 1, "itemsPerPage": 1,
            "Resources": [{"id": SCIM_SCHEMA, "name": "User", "description": "FINESSE user"}]}


@router.get("/scim/v2/Users", dependencies=[Depends(scim_context)])
async def list_users(request: Request, filter: str | None = None, startIndex: int = 1,
                     count: int = 100):
    tenant_id, _token = scim_context(request)
    if startIndex < 1 or count < 1 or count > 1000:
        raise HTTPException(400, "invalid SCIM pagination")
    roster = [users.get(value["email"], tenant_id)
              for value in users.all_public(tenant_id)]
    roster = [user for user in roster if user is not None]
    if filter:
        match = _FILTER.fullmatch(filter)
        if not match:
            raise HTTPException(400, "only userName eq \"value\" filters are supported")
        target = match.group(1).casefold()
        roster = [user for user in roster if user.email.casefold() == target]
    resources = [_user_resource(user) for user in roster[startIndex - 1:startIndex - 1 + count]]
    return {"schemas": [SCIM_LIST_SCHEMA], "totalResults": len(roster),
            "startIndex": startIndex, "itemsPerPage": len(resources), "Resources": resources}


@router.post("/scim/v2/Users", status_code=201, dependencies=[Depends(scim_context)])
async def create_user(request: Request):
    tenant_id, token = scim_context(request)
    body = await request.json()
    email = str(body.get("userName", "")).strip().lower()
    if not email or len(email) > 320 or "@" not in email:
        raise HTTPException(400, "userName must be a valid email address")
    name = str(body.get("displayName") or (body.get("name") or {}).get("formatted") or email)
    role = _role_from_groups(body.get("groups", [])) or "Analyst"
    try:
        user = users.create(email, name, role, secrets.token_urlsafe(36), tenant_id)
        user.external_subject = str(body.get("externalId") or email)
        user.active = bool(body.get("active", True))
        users._save_user(user)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    await _audit(tenant_id, "scim_user_created", token.get("name", "scim"), email)
    return _user_resource(user)


@router.get("/scim/v2/Users/{user_id}", dependencies=[Depends(scim_context)])
async def get_user(user_id: str, request: Request):
    tenant_id, _token = scim_context(request)
    return _user_resource(_user(user_id, tenant_id))


async def _update_user(request: Request, user_id: str, *, replace_all: bool):
    tenant_id, token = scim_context(request)
    user = _user(user_id, tenant_id)
    body = await request.json()
    if replace_all:
        if "active" in body:
            user = users.set_active(user.email, tenant_id, bool(body["active"]))
        role = _role_from_groups(body.get("groups", [])) if "groups" in body else None
        if role:
            user = users.set_role(user.email, tenant_id, role)
        if "displayName" in body:
            user.name = str(body["displayName"])[:200]
            users._save_user(user)
    else:
        operations = body.get("Operations") or body.get("operations") or []
        for operation in operations:
            op = str(operation.get("op", "replace")).casefold()
            path = str(operation.get("path", "")).casefold()
            value = operation.get("value")
            if path == "active" and op in {"replace", "add"}:
                user = users.set_active(user.email, tenant_id, bool(value))
            elif path == "groups" and op in {"replace", "add"}:
                role = _role_from_groups(value if isinstance(value, list) else [value])
                if role:
                    user = users.set_role(user.email, tenant_id, role)
            elif path == "groups" and op == "remove":
                user = users.set_role(user.email, tenant_id, "Analyst")
            elif path in {"displayname", "name.formatted"} and op in {"replace", "add"}:
                user.name = str(value)[:200]
                users._save_user(user)
            else:
                raise HTTPException(400, f"unsupported SCIM PATCH operation: {op} {path}")
    if not user.active:
        await _revoke_user_sessions(tenant_id, user.email)
    await _audit(tenant_id, "scim_user_updated", token.get("name", "scim"), user.email)
    return _user_resource(user)


@router.put("/scim/v2/Users/{user_id}", dependencies=[Depends(scim_context)])
async def replace_user(user_id: str, request: Request):
    return await _update_user(request, user_id, replace_all=True)


@router.patch("/scim/v2/Users/{user_id}", dependencies=[Depends(scim_context)])
async def patch_user(user_id: str, request: Request):
    return await _update_user(request, user_id, replace_all=False)


@router.delete("/scim/v2/Users/{user_id}", status_code=204,
               dependencies=[Depends(scim_context)])
async def delete_user(user_id: str, request: Request):
    tenant_id, token = scim_context(request)
    user = _user(user_id, tenant_id)
    try:
        users.set_active(user.email, tenant_id, False)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    await _revoke_user_sessions(tenant_id, user.email)
    await _audit(tenant_id, "scim_user_deactivated", token.get("name", "scim"), user.email)


def _groups(tenant_id: str):
    roster = [users.get(value["email"], tenant_id)
              for value in users.all_public(tenant_id)]
    roster = [user for user in roster if user is not None]
    return [{"schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
             "id": role, "displayName": role,
             "members": [{"value": user.email, "display": user.name,
                          "type": "User"} for user in roster if user.role == role]}
            for role in sorted(ROLES) if role != "CEO"]


@router.get("/scim/v2/Groups", dependencies=[Depends(scim_context)])
async def list_groups(request: Request, startIndex: int = 1, count: int = 100):
    tenant_id, _token = scim_context(request)
    groups = _groups(tenant_id)
    result = groups[startIndex - 1:startIndex - 1 + min(count, 1000)]
    return {"schemas": [SCIM_LIST_SCHEMA], "totalResults": len(groups),
            "startIndex": startIndex, "itemsPerPage": len(result), "Resources": result}


@router.get("/scim/v2/Groups/{group_id}", dependencies=[Depends(scim_context)])
async def get_group(group_id: str, request: Request):
    tenant_id, _token = scim_context(request)
    for group in _groups(tenant_id):
        if group["id"] == unquote(group_id):
            return group
    raise HTTPException(404, "SCIM group not found")


@router.patch("/scim/v2/Groups/{group_id}", dependencies=[Depends(scim_context)])
async def patch_group(group_id: str, request: Request):
    tenant_id, token = scim_context(request)
    role = unquote(group_id)
    if role not in ROLES or role == "CEO":
        raise HTTPException(404, "SCIM group not found")
    body = await request.json()
    for operation in body.get("Operations") or body.get("operations") or []:
        op = str(operation.get("op", "add")).casefold()
        path = str(operation.get("path", "members"))
        path_match = re.fullmatch(
            r'members(?:\[value\s+eq\s+"([^"]{1,320})"\])?', path, re.IGNORECASE)
        if not path_match:
            raise HTTPException(400, "SCIM group PATCH path must target members")
        value = operation.get("value", [])
        if path_match.group(1) and not value:
            value = {"value": path_match.group(1)}
        members = value if isinstance(value, list) else [value]
        for member in members:
            email = str(member.get("value", "") if isinstance(member, dict) else member)
            if not email:
                raise HTTPException(400, "SCIM group PATCH requires members values")
            user = _user(email, tenant_id)
            new_role = role if op in {"add", "replace"} else "Analyst"
            user = users.set_role(user.email, tenant_id, new_role)
            await _revoke_user_sessions(tenant_id, user.email)
            await _audit(tenant_id, "scim_group_membership_changed",
                         token.get("name", "scim"), user.email)
    return await get_group(group_id, request)


@router.post("/api/v1/admin/scim/tokens")
async def create_scim_token(request: Request,
                            credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)):
    # This control-plane route is intentionally authenticated with the app JWT.
    from ..auth.security import decode_token
    principal = decode_token(credentials.credentials) if credentials else None
    if not principal or principal.get("tier", 0) < 4 or "mfa" not in principal.get("amr", []):
        raise HTTPException(403, "MFA-authenticated L4 administrator required")
    tenant_id = str(principal["tenant_id"])
    raw = "fsc_" + secrets.token_urlsafe(40)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    token_id = secrets.token_urlsafe(12)
    try:
        body = await request.json()
    except Exception:
        body = {}
    record = {"token_hash": digest, "name": str(body.get("name", "SCIM integration"))[:100],
              "scopes": ["Users:read", "Users:write", "Groups:read", "Groups:write"],
              "created_by": principal["sub"], "created_at": time.time(),
              "expires_at": time.time() + 365 * 24 * 3600, "last_used_at": None,
              "revoked_at": None}
    if not storage.put_if_absent("scim_tokens", tenant_id, token_id, record):
        raise HTTPException(503, "could not create SCIM credential")
    if not storage.put_if_absent("scim_token_index", _INDEX_TENANT, digest, {
            "token_hash": digest, "target_tenant_id": tenant_id, "token_id": token_id}):
        storage.delete("scim_tokens", tenant_id, token_id)
        raise HTTPException(503, "could not index SCIM credential")
    return JSONResponse(status_code=201, content={"id": token_id, "token": raw,
                                                 "expires_at": record["expires_at"]})


@router.delete("/api/v1/admin/scim/tokens/{token_id}",
               dependencies=[Depends(_bearer)])
async def revoke_scim_token(token_id: str, request: Request,
                            credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)):
    from ..auth.security import decode_token
    principal = decode_token(credentials.credentials) if credentials else None
    if not principal or principal.get("tier", 0) < 4 or "mfa" not in principal.get("amr", []):
        raise HTTPException(403, "MFA-authenticated L4 administrator required")
    tenant_id = str(principal["tenant_id"])
    record = storage.get("scim_tokens", tenant_id, token_id)
    if not record:
        raise HTTPException(404, "SCIM token not found")
    record["revoked_at"] = time.time()
    storage.put("scim_tokens", tenant_id, token_id, record)
    return {"revoked": True, "id": token_id}
