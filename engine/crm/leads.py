"""
CRM inside Obsidian.

Each lead is BOTH a structured record (data/leads.json — fast queries, dashboard)
AND an Obsidian note in vault/21_CRM/Leads with [[wikilinks]] to its location,
status and source, so your CRM is a living graph. A pipeline MOC groups leads by
stage (kanban-in-markdown).

Human-touch gateway (new): the AI finds/qualifies leads and DRAFTS outreach, but
**reaching out is human**. `outreach_status` stays 'draft' until a person approves.
"""
from __future__ import annotations
import json
import re
import time
import uuid
from dataclasses import dataclass, asdict, field
from pathlib import Path

from ..config import cfg

STAGES = ["new", "qualified", "contacted", "proposal", "won", "lost"]
_DB = cfg.DATA / "leads.json"
_LEADS = cfg.VAULT / "21_CRM" / "Leads"
_PIPE = cfg.VAULT / "21_CRM" / "CRM Pipeline.md"


def _slug(s: str) -> str:
    return re.sub(r"[^\w\- ]", "_", (s or "lead")).strip()[:70] or "lead"


@dataclass
class Lead:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    name: str = ""
    company: str = ""
    title: str = ""
    location: str = ""          # geo
    industry: str = ""
    need: str = ""              # what the client needs (the fit signal)
    fit_score: float = 0.5      # product-market fit / lead score 0..1
    source: str = "manual"
    contact: str = ""           # email / phone / url
    status: str = "new"
    outreach_draft: str = ""
    outreach_status: str = "none"   # none | draft | approved | sent
    owner: str = ""             # employee who owns the lead
    created: float = field(default_factory=time.time)

    def label(self) -> str:
        return self.company or self.name or self.id


class CRM:
    def __init__(self):
        self._leads: dict[str, Lead] = {}
        self.load()

    def load(self):
        if _DB.exists():
            data = json.loads(_DB.read_text(encoding="utf-8"))
            self._leads = {i: Lead(**l) for i, l in data.items()}

    def save(self):
        _DB.parent.mkdir(parents=True, exist_ok=True)
        _DB.write_text(json.dumps({i: asdict(l) for i, l in self._leads.items()}, indent=2),
                       encoding="utf-8")

    # ---- ops ----
    def upsert(self, lead: Lead) -> Lead:
        self._leads[lead.id] = lead
        self.save()
        self._write_note(lead)
        self.rebuild_pipeline()
        return lead

    def add(self, **kw) -> Lead:
        return self.upsert(Lead(**kw))

    def get(self, lead_id: str) -> Lead | None:
        return self._leads.get(lead_id)

    def set_stage(self, lead_id: str, stage: str) -> Lead | None:
        l = self._leads.get(lead_id)
        if l and stage in STAGES:
            l.status = stage
            self.upsert(l)
        return l

    def approve_outreach(self, lead_id: str) -> Lead | None:
        l = self._leads.get(lead_id)
        if l and l.outreach_draft:
            l.outreach_status = "approved"   # a human clicked approve; sending is still manual/connector
            self.upsert(l)
        return l

    def all(self) -> list[Lead]:
        return sorted(self._leads.values(), key=lambda x: -x.created)

    def by_stage(self) -> dict[str, list[Lead]]:
        out = {s: [] for s in STAGES}
        for l in self._leads.values():
            out.setdefault(l.status, []).append(l)
        return out

    def stats(self) -> dict:
        bs = self.by_stage()
        return {"total": len(self._leads), **{s: len(bs.get(s, [])) for s in STAGES}}

    # ---- obsidian ----
    def _write_note(self, l: Lead):
        _LEADS.mkdir(parents=True, exist_ok=True)
        note = _LEADS / f"{_slug(l.label())}__{l.id}.md"
        fm = ("---\n"
              f"type: lead\nid: {l.id}\ncompany: {l.company}\nname: {l.name}\n"
              f"title: {l.title}\nlocation: {l.location}\nindustry: {l.industry}\n"
              f"fit_score: {l.fit_score}\nstatus: {l.status}\nsource: {l.source}\n"
              f"owner: {l.owner}\noutreach_status: {l.outreach_status}\n"
              f"tags: [lead, crm, {l.status}]\n---\n\n")
        body = (
            f"# {l.label()}\n\n"
            f"**Location:** [[{l.location or 'Unknown'}]] · **Industry:** {l.industry or '—'} · "
            f"**Fit:** {l.fit_score:.2f} · **Stage:** [[{l.status}]]\n\n"
            f"**Contact:** {l.contact or '—'} · **Owner:** {l.owner or 'unassigned'} · "
            f"**Source:** [[{l.source}]]\n\n"
            f"## Need / fit signal\n{l.need or '—'}\n\n"
            f"## Outreach (human-gated — {l.outreach_status})\n"
            f"{l.outreach_draft or '_no draft yet_'}\n\n"
            f"> [[CRM Pipeline]] · [[SASTRAVA OS MAP]]\n")
        note.write_text(fm + body, encoding="utf-8")

    def rebuild_pipeline(self):
        _PIPE.parent.mkdir(parents=True, exist_ok=True)
        bs = self.by_stage()
        parts = ["---\ntitle: CRM Pipeline\ntags: [crm, moc, pipeline]\n---\n",
                 "# 🎯 CRM Pipeline\n",
                 f"_{len(self._leads)} leads · human owns outreach._\n"]
        for s in STAGES:
            leads = bs.get(s, [])
            parts.append(f"\n## {s.upper()} ({len(leads)})")
            for l in leads:
                parts.append(f"- [[{_slug(l.label())}__{l.id}]] — {l.location or '—'} · "
                             f"fit {l.fit_score:.2f} · outreach:{l.outreach_status}")
        parts.append("\n\n> [[SASTRAVA OS MAP]]\n")
        _PIPE.write_text("\n".join(parts), encoding="utf-8")


crm = CRM()
