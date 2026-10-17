from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

from .sanitize import sanitize_public_text

KNOWLEDGE_DIR = Path(__file__).resolve().parent

METHOD = [
    {"name": "Listen", "focus": "Understand the context, goals, evidence, constraints, and people affected."},
    {"name": "Shape", "focus": "Agree a bounded approach, options, assumptions, risks, and measures of success."},
    {"name": "Deliver", "focus": "Define practical outputs, ownership, milestones, acceptance criteria, and review."},
]

PILLARS = [
    {"id": "direction", "name": "Direction", "focus": "Strategy, opportunity discovery, and growth planning."},
    {"id": "build", "name": "Build", "focus": "Software delivery and responsible AI automation."},
    {"id": "protect", "name": "Protect", "focus": "Authorized security scoping and risk reduction."},
    {"id": "growth", "name": "Growth", "focus": "Search, digital marketing, and measurable reach."},
    {"id": "learning", "name": "Learning", "focus": "Digital learning design and practical capability building."},
    {"id": "enablement", "name": "Enablement", "focus": "Skills, process, and adoption support."},
]

SERVICES = [
    {"id": "strategy_consulting", "name": "Strategy and incubation",
     "pillar": "direction", "lane": "bizdev", "agent": "sastrava_strategy",
     "description": "Clarify the opportunity, value proposition, validation steps, and a realistic growth path."},
    {"id": "ai_automation", "name": "AI and automation",
     "pillar": "build", "lane": "coding", "agent": "sastrava_ai_automation",
     "description": "Map candidate workflows and shape bounded AI or automation pilots with human oversight."},
    {"id": "software_delivery", "name": "Software delivery",
     "pillar": "build", "lane": "coding", "agent": "sastrava_software_delivery",
     "description": "Shape software requirements, delivery milestones, testing, and operational readiness."},
    {"id": "cybersecurity", "name": "Cybersecurity",
     "pillar": "protect", "lane": "security", "agent": "sastrava_security",
     "description": "Scope authorized security reviews and organize evidence-led remediation priorities."},
    {"id": "digital_growth", "name": "Digital growth",
     "pillar": "growth", "lane": "marketing", "agent": "sastrava_digital_growth",
     "description": "Plan search, content, and digital marketing work with clear measurement."},
    {"id": "digital_learning", "name": "Digital learning",
     "pillar": "learning", "lane": "general", "agent": "sastrava_learning",
     "description": "Design audience-led learning journeys, practice, assessment, and adoption."},
]

PLAYBOOKS = [
    {"id": "discovery", "name": "Business discovery", "path": "playbooks/business_discovery.md"},
    {"id": "ai_pilot", "name": "Responsible AI pilot", "path": "playbooks/ai_pilot.md"},
    {"id": "software_delivery", "name": "Software delivery", "path": "playbooks/software_delivery.md"},
    {"id": "security_scope", "name": "Authorized security scope", "path": "playbooks/security_scope.md"},
    {"id": "digital_growth", "name": "Digital growth", "path": "playbooks/digital_growth.md"},
    {"id": "learning_design", "name": "Digital learning design", "path": "playbooks/learning_design.md"},
]

_SERVICE_TERMS = {
    "strategy_consulting": ("strategy", "incubat", "business model", "market fit", "growth plan", "go to market"),
    "ai_automation": ("ai", "artificial intelligence", "automation", "automate", "agent", "workflow"),
    "software_delivery": ("software", "application", "app", "website", "platform", "engineering", "development"),
    "cybersecurity": ("security", "cyber", "vulnerability", "risk review", "penetration", "incident"),
    "digital_growth": ("seo", "search", "marketing", "content", "campaign", "digital growth", "social media"),
    "digital_learning": ("learning", "training", "curriculum", "course", "education", "enablement"),
}


def infer_service_lines(text: str) -> list[str]:
    normalized = (text or "").lower()
    matches = [
        service_id for service_id, terms in _SERVICE_TERMS.items()
        if any(re.search(rf"\b{re.escape(term)}\b", normalized) for term in terms)
    ]
    return matches[:3] or ["strategy_consulting"]


def _load_json(name: str) -> dict:
    path = KNOWLEDGE_DIR / name
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid public knowledge catalog: {name}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"public knowledge catalog must be an object: {name}")
    return value


def catalog_response() -> dict:
    site = _load_json("site_pages.json")
    github = _load_json("github_portfolio.json")
    pages = []
    site_pages = site.get("pages", [])
    if not isinstance(site_pages, list):
        raise RuntimeError("public website catalog pages must be a list")
    for page in site_pages:
        if not isinstance(page, dict) or not page.get("url"):
            continue
        try:
            parsed = urlparse(str(page["url"]))
        except ValueError:
            continue
        if parsed.scheme != "https" or parsed.hostname not in {"sastrava.com", "www.sastrava.com"}:
            continue
        pages.append({
            "url": str(page["url"]),
            "title": sanitize_public_text(str(page.get("title", ""))),
            "content": sanitize_public_text(str(page.get("content", ""))),
        })
    repositories = []
    github_repositories = github.get("repositories", [])
    if not isinstance(github_repositories, list):
        raise RuntimeError("public GitHub catalog repositories must be a list")
    for repo in github_repositories:
        if not isinstance(repo, dict) or repo.get("private") is not False:
            continue
        name = str(repo.get("name", ""))
        if (name.casefold() == "finesse"
                or not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", name)):
            continue
        repositories.append({
            "name": sanitize_public_text(name),
            "url": f"https://github.com/SASTRAVA/{name}",
            "description": sanitize_public_text(str(repo.get("description", ""))),
            "language": sanitize_public_text(str(repo.get("language", ""))),
            "summary": sanitize_public_text(str(repo.get("summary", ""))),
        })
    playbooks = []
    for item in PLAYBOOKS:
        path = KNOWLEDGE_DIR / item["path"]
        content = path.read_text(encoding="utf-8") if path.is_file() else ""
        playbooks.append({**item, "content": sanitize_public_text(content)})
    return {
        "organization": "SASTRAVA",
        "approach": list(METHOD),
        "pillars": list(PILLARS),
        "services": list(SERVICES),
        "playbooks": playbooks,
        "site_pages": pages,
        "public_repositories": repositories,
    }
