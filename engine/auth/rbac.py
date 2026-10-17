"""
Role-Based Access Control — the hierarchy of the company, in code.

Mirrors vault/03_Roles and vault/20_AI_Orchestration_Core/Security/Role-Based Access.md.

Login tiers:
  L4  admin        -> CEO ONLY (you). Full system + user management.
  L3  executive    -> COO. Cross-department visibility.
  L2  manager      -> department managers. Own department + own swarm.
  L1  specialist   -> individual contributors. Own lane.

Every role maps to an agent "lane" so, at login, the orchestra already knows
which swarm to stand up for that person.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List

# lanes = the three core agent domains you asked for + support lanes
LANE_CODING = "coding"
LANE_PROMPT = "prompt"
LANE_MARKETING = "marketing"
LANE_BIZDEV = "bizdev"
LANE_EXEC = "exec"
LANE_GENERAL = "general"
LANE_SECURITY = "security"      # continuous platform security auditing


@dataclass
class RoleDef:
    name: str
    tier: int                       # 1..4
    lane: str
    permissions: List[str] = field(default_factory=list)


# Wildcard permission for the CEO.
ADMIN = "*"

ROLES: dict[str, RoleDef] = {
    # ---- L4 admin (CEO only) ----
    "CEO": RoleDef("CEO", 4, LANE_EXEC, [ADMIN]),

    # ---- L3 executive ----
    "COO": RoleDef("COO", 3, LANE_EXEC,
                   ["orchestrate", "read:all", "inject", "spawn:any", "view:analytics"]),

    # ---- L2 managers ----
    "Business Development Manager": RoleDef("Business Development Manager", 2, LANE_BIZDEV,
        ["orchestrate:bizdev", "inject", "spawn:bizdev", "read:bizdev", "view:analytics"]),
    "Digital Marketing Manager": RoleDef("Digital Marketing Manager", 2, LANE_MARKETING,
        ["orchestrate:marketing", "inject", "spawn:marketing", "read:marketing", "view:analytics"]),
    "AI Engineer": RoleDef("AI Engineer", 2, LANE_CODING,
        ["orchestrate:coding", "inject", "spawn:coding", "read:coding"]),
    "Operations Manager": RoleDef("Operations Manager", 2, LANE_GENERAL,
        ["inject", "spawn:general", "read:general", "view:analytics"]),
    "Security Auditor": RoleDef("Security Auditor", 2, LANE_SECURITY,
        ["orchestrate:security", "inject", "spawn:security", "read:security", "view:analytics"]),
    "Finance Manager": RoleDef("Finance Manager", 2, LANE_GENERAL,
        ["inject", "spawn:general", "read:finance"]),
    "HR Manager": RoleDef("HR Manager", 2, LANE_GENERAL,
        ["inject", "spawn:general", "read:hr"]),

    # ---- L1 specialists ----
    "Prompt Engineer": RoleDef("Prompt Engineer", 1, LANE_PROMPT,
        ["inject", "spawn:prompt", "read:prompt"]),
    "Software Engineer": RoleDef("Software Engineer", 1, LANE_CODING,
        ["inject", "spawn:coding", "read:coding"]),
    "Full Stack Developer": RoleDef("Full Stack Developer", 1, LANE_CODING,
        ["inject", "spawn:coding", "read:coding"]),
    "SEO Specialist": RoleDef("SEO Specialist", 1, LANE_MARKETING,
        ["inject", "spawn:marketing", "read:marketing"]),
    "Content Strategist": RoleDef("Content Strategist", 1, LANE_MARKETING,
        ["inject", "spawn:marketing", "read:marketing"]),
    "Sales Executive": RoleDef("Sales Executive", 1, LANE_BIZDEV,
        ["inject", "spawn:bizdev", "read:bizdev"]),
    "Research Analyst": RoleDef("Research Analyst", 1, LANE_GENERAL,
        ["inject", "spawn:general", "read:general"]),
    "Graphic Designer": RoleDef("Graphic Designer", 1, LANE_MARKETING,
        ["inject", "spawn:marketing", "read:marketing"]),
    "Video Editor": RoleDef("Video Editor", 1, LANE_MARKETING,
        ["inject", "spawn:marketing", "read:marketing"]),
    "Curriculum Designer": RoleDef("Curriculum Designer", 1, LANE_GENERAL,
        ["inject", "spawn:general", "read:general"]),
    "Trainer": RoleDef("Trainer", 1, LANE_GENERAL, ["inject", "spawn:general", "read:general"]),
    "Legal Advisor": RoleDef("Legal Advisor", 1, LANE_GENERAL, ["inject", "read:legal"]),
}

LANE_OF_ROLE = {name: r.lane for name, r in ROLES.items()}


def role_of(name: str) -> RoleDef:
    return ROLES.get(name, RoleDef(name, 1, LANE_GENERAL, ["inject", "spawn:general", "read:general"]))


def can(role_name: str, permission: str) -> bool:
    r = role_of(role_name)
    if ADMIN in r.permissions:
        return True
    if permission in r.permissions:
        return True
    # prefix perms, e.g. "spawn:marketing" satisfies a "spawn:marketing" check;
    # "read:all" satisfies any "read:*"
    if permission.startswith("read:") and "read:all" in r.permissions:
        return True
    return False
