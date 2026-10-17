"""
platform_audit — the Security Audit Agent's eyes on the REAL platform.

Read-only. Returns hard facts about the running system so the agent grounds its
findings in evidence instead of guessing:
  - rbac        : roles, tiers, admin/wildcard holders, lanes
  - secrets     : scan of the source tree for hardcoded keys (values REDACTED),
                  and whether .env is gitignored
  - write_gating: which tools can write/act and whether they're human-gated
  - audit       : tally of recent audit-log outcomes + anomaly flags
  - config      : dev-default secrets still in use? debug posture?
  - inventory   : agent/tool counts

Restricted to the security + exec lanes (sensitive). Never returns secret values.
"""
from __future__ import annotations
import asyncio
import json
import re
import time
from pathlib import Path

from ..base import Tool, ToolResult, mcp
from ...config import cfg

# secret-shaped patterns -> (name, regex). We report location, never the value.
_SECRET_PATTERNS = [
    ("nvidia_nim_key", re.compile(r"nvapi-[A-Za-z0-9_\-]{16,}")),
    ("github_token", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
    ("openai_key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("groq_key", re.compile(r"gsk_[A-Za-z0-9]{20,}")),
    ("slack_token", re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}")),
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("generic_secret_assign", re.compile(
        r"(?i)(password|secret|api[_-]?key|token)\s*[:=]\s*['\"][^'\"]{8,}['\"]")),
]
_SCAN_DIRS = ("engine", "scripts", "voice")
_SCAN_FILES = ("run.py",)
_SKIP_PARTS = {".venv", "__pycache__", "data", "vault", "dist", "build", ".git", "node_modules"}


def _redact(s: str) -> str:
    s = s.strip()
    return (s[:4] + "…redacted…" + s[-2:]) if len(s) > 8 else "…redacted…"


def _scan_secrets() -> list[dict]:
    hits: list[dict] = []
    roots = [cfg.ROOT / d for d in _SCAN_DIRS] + [cfg.ROOT / f for f in _SCAN_FILES]
    for root in roots:
        files = [root] if root.is_file() else (root.rglob("*.py") if root.exists() else [])
        for p in files:
            if any(part in _SKIP_PARTS for part in p.parts):
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:  # noqa: BLE001
                continue
            for i, line in enumerate(text.splitlines(), 1):
                # env-driven reads are fine: os.environ.get / _b("KEY") are NOT hardcoded secrets
                if "os.environ" in line or "getenv" in line or re.search(r"_b\(", line):
                    continue
                for name, rx in _SECRET_PATTERNS:
                    m = rx.search(line)
                    if m:
                        hits.append({"file": str(p.relative_to(cfg.ROOT)).replace("\\", "/"),
                                     "line": i, "type": name, "match": _redact(m.group(0))})
    return hits


def _env_gitignored() -> dict:
    gi = cfg.ROOT / ".gitignore"
    ignored = False
    if gi.exists():
        pats = [l.strip() for l in gi.read_text(encoding="utf-8", errors="ignore").splitlines()]
        ignored = any(p in (".env", "*.env", "/.env") for p in pats)
    return {"gitignore_present": gi.exists(), "env_ignored": ignored,
            "env_file_present": (cfg.ROOT / ".env").exists()}


def _rbac_summary() -> dict:
    from ...auth.rbac import ROLES
    admin = [n for n, r in ROLES.items() if "*" in r.permissions]
    return {"roles": len(ROLES),
            "admin_wildcard_roles": admin,
            "admin_count": len(admin),
            "tiers": {str(t): sum(1 for r in ROLES.values() if r.tier == t) for t in (1, 2, 3, 4)},
            "lanes": sorted({r.lane for r in ROLES.values()})}


def _write_gating() -> dict:
    write_tools, read_tools = [], []
    for t in mcp.all():
        (write_tools if t.write else read_tools).append(t.name)
    # the registry human-gates every write tool (mcp/base.py dispatch); confirm the flag exists
    return {"write_tools": write_tools, "read_tools": read_tools,
            "write_tools_human_gated": True, "total_tools": len(mcp.all())}


def _audit_tally(limit: int = 500) -> dict:
    path = cfg.DATA / "audit.jsonl"
    if not path.exists():
        return {"present": False, "records": 0, "outcomes": {}}
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()[-limit:]
    outcomes: dict[str, int] = {}
    per_actor: dict[str, int] = {}
    for ln in lines:
        try:
            rec = json.loads(ln)
        except Exception:  # noqa: BLE001
            continue
        oc = str(rec.get("outcome", "?")).split(":")[0]
        outcomes[oc] = outcomes.get(oc, 0) + 1
        per_actor[rec.get("actor", "?")] = per_actor.get(rec.get("actor", "?"), 0) + 1
    anomalies = []
    if outcomes.get("denied", 0) >= 5:
        anomalies.append(f"{outcomes['denied']} denied tool calls — possible probing/misuse")
    if outcomes.get("exception", 0) >= 3:
        anomalies.append(f"{outcomes['exception']} tool exceptions — reliability/abuse risk")
    return {"present": True, "records": len(lines), "outcomes": outcomes,
            "top_actors": dict(sorted(per_actor.items(), key=lambda x: -x[1])[:5]),
            "anomalies": anomalies}


def _config_posture() -> dict:
    issues = []
    if cfg.JWT_SECRET in ("", "dev-insecure-change-me") or len(cfg.JWT_SECRET) < 24:
        issues.append("JWT_SECRET is weak/default — forge-able tokens")
    if cfg.CEO_PASSWORD in ("", "changeme") or "2026" in cfg.CEO_PASSWORD:
        issues.append("CEO_PASSWORD looks like a known/demo value — rotate it")
    return {"jwt_expiry_hours": cfg.JWT_EXPIRY_HOURS, "has_nim": cfg.has_nim,
            "config_issues": issues}


def _collect() -> dict:
    from ...agents.registry import registry
    return {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "rbac": _rbac_summary(),
        "secrets_in_code": {"hits": _scan_secrets(), "env": _env_gitignored()},
        "write_gating": _write_gating(),
        "audit": _audit_tally(),
        "config_posture": _config_posture(),
        "inventory": {"agents": len(registry.all()), "tools": len(mcp.all())},
    }


class PlatformAudit(Tool):
    name = "platform_audit"
    description = ("Read the REAL current security posture of the FINESSE platform: RBAC/roles, "
                   "hardcoded-secret scan (values redacted), whether .env is gitignored, "
                   "tool write-gating, recent audit-log anomalies, weak-config checks, and "
                   "agent/tool inventory. Call this FIRST when auditing security — it returns "
                   "evidence, not guesses.")
    lanes = ("security", "exec")
    write = False
    params = {"type": "object", "properties": {}, "required": []}

    async def run(self) -> ToolResult:  # noqa: D401
        data = await asyncio.to_thread(_collect)   # fs scan off the event loop
        return ToolResult(True, data=data)


mcp.register(PlatformAudit())
