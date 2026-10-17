"""Authorization-first inventory; tools are catalogued but never auto-executed."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass

_CHALLENGE_KEY = secrets.token_bytes(32)
_CERTIFICATE_KEY = secrets.token_bytes(32)


@dataclass(frozen=True)
class SecurityTool:
    name: str
    category: str
    executable: str | None
    auto_execute: bool = False
    restricted: bool = False


_CLI_TOOLS = (
    ("gitleaks", "secrets"), ("semgrep", "static-analysis"), ("trivy", "supply-chain"),
    ("syft", "sbom"), ("osv-scanner", "dependency-audit"), ("httpx", "asset-inventory"),
    ("nuclei", "vulnerability-check"), ("subfinder", "asset-inventory"),
    ("amass", "asset-inventory"), ("dnsx", "dns"), ("naabu", "ports"),
    ("nmap", "ports"), ("owasp-zap", "web-application"),
)
SECURITY_TOOLS = tuple(SecurityTool(name, category, name) for name, category in _CLI_TOOLS) + (
    SecurityTool("raw_shell", "restricted", None, restricted=True),
    SecurityTool("credential_dump", "restricted", None, restricted=True),
    SecurityTool("destructive_scan", "restricted", None, restricted=True),
)


def create_target_challenge(domain: str, *, now: int | None = None) -> dict:
    normalized = domain.rstrip(".").lower()
    if not normalized or "/" in normalized or ":" in normalized:
        raise ValueError("a domain name is required")
    issued = int(time.time() if now is None else now)
    nonce = secrets.token_urlsafe(18)
    message = f"{normalized}|{issued}|{nonce}".encode()
    token = hmac.new(_CHALLENGE_KEY, message, hashlib.sha256).hexdigest()
    return {"domain": normalized, "issued_at": issued, "nonce": nonce, "token": token,
            "dns_record": f"_sastrava-verify.{normalized}",
            "https_path": "/.well-known/sastrava-verify.txt"}


def verify_target_challenge(challenge: dict, observed_value: str, *,
                            source: str, now: int | None = None) -> bool:
    if source not in {"dns_txt", "https_file"}:
        return False
    issued = challenge.get("issued_at")
    nonce = challenge.get("nonce")
    domain = str(challenge.get("domain", "")).rstrip(".").lower()
    if not isinstance(issued, int) or not nonce or not domain:
        return False
    current = int(time.time() if now is None else now)
    if issued > current or current - issued > 900:
        return False
    message = f"{domain}|{issued}|{nonce}".encode()
    expected = hmac.new(_CHALLENGE_KEY, message, hashlib.sha256).hexdigest()
    return (hmac.compare_digest(str(challenge.get("token", "")), expected)
            and hmac.compare_digest(observed_value.strip(), expected))


def safe_scan_profile(tool_name: str, args: list[str]) -> list[str]:
    if tool_name not in {tool.name for tool in SECURITY_TOOLS if not tool.restricted}:
        raise ValueError("tool is not in the approved local security registry")
    forbidden = {"--script=all", "--script=default", "-A", "--aggressive"}
    if any(arg.casefold() in forbidden for arg in args):
        raise ValueError("unsafe or intrusive scan arguments are not permitted")
    if tool_name == "nuclei":
        return [*args, "-severity", "critical,high,medium",
                "-exclude-tags", "dos,fuzz,intrusive"]
    return list(args)


def erasure_certificate(*, tenant_id: str, scan_id: str, evidence_count: int) -> dict:
    issued_at = int(time.time())
    body = f"{tenant_id}|{scan_id}|{evidence_count}|{issued_at}"
    signature = hmac.new(_CERTIFICATE_KEY, body.encode(), hashlib.sha256).hexdigest()
    return {"tenant_id": tenant_id, "scan_id": scan_id,
            "evidence_count": evidence_count, "issued_at": issued_at,
            "signature": signature}


def verify_erasure_certificate(certificate: dict) -> bool:
    try:
        body = (f"{certificate['tenant_id']}|{certificate['scan_id']}|"
                f"{int(certificate['evidence_count'])}|{int(certificate['issued_at'])}")
        expected = hmac.new(_CERTIFICATE_KEY, body.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, certificate["signature"])
    except (KeyError, TypeError, ValueError):
        return False
