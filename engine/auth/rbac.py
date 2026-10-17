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
ALL_LANES = (LANE_CODING, LANE_PROMPT, LANE_MARKETING, LANE_BIZDEV,
             LANE_EXEC, LANE_GENERAL, LANE_SECURITY)
SENSITIVITY_LEVELS = ("public", "internal", "confidential", "restricted")


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
    "Sales Manager": RoleDef("Sales Manager", 2, LANE_BIZDEV,
                             ["orchestrate:bizdev", "inject", "spawn:bizdev",
                              "read:bizdev", "view:analytics"]),
    "Sales Representative": RoleDef("Sales Representative", 1, LANE_BIZDEV,
                                    ["inject", "spawn:bizdev", "read:bizdev"]),
    "Analyst": RoleDef("Analyst", 1, LANE_GENERAL, ["view:analytics"]),
    "Administrator": RoleDef("Administrator", 3, LANE_EXEC,
                             ["orchestrate", "read:all", "inject", "spawn:any",
                              "view:analytics"]),
    "admin": RoleDef("admin", 2, LANE_BIZDEV, ["view:analytics", "sales:admin"]),
    "sales_manager": RoleDef("sales_manager", 2, LANE_BIZDEV,
                             ["orchestrate:bizdev", "inject", "spawn:bizdev",
                              "read:bizdev", "view:analytics"]),
    "sales_rep": RoleDef("sales_rep", 1, LANE_BIZDEV,
                         ["inject", "spawn:bizdev", "read:bizdev"]),
    "analyst": RoleDef("analyst", 1, LANE_GENERAL, ["view:analytics"]),
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


def permitted_lanes(role_or_lane: str) -> tuple[str, ...]:
    """Return the data lanes a principal may retrieve; unknown context is least-privilege."""
    if role_or_lane in ALL_LANES:
        lane = role_or_lane
        executive = lane == LANE_EXEC
    else:
        role = role_of(role_or_lane)
        lane = role.lane
        executive = role.tier >= 3 or ADMIN in role.permissions
    if executive:
        return ALL_LANES + ("shared", "global")
    return tuple(dict.fromkeys((lane, LANE_GENERAL, "shared", "global")))


def max_sensitivity(role_or_lane: str) -> str:
    if role_or_lane in ALL_LANES:
        return "internal" if role_or_lane != LANE_EXEC else "restricted"
    role = role_of(role_or_lane)
    return "restricted" if role.tier >= 3 or ADMIN in role.permissions else "internal"
