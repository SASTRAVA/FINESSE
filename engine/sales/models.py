from __future__ import annotations

from pydantic import BaseModel, Field


class AgentCommandIn(BaseModel):
    command: str = Field(min_length=1, max_length=4000)
    tainted: bool = False
    sensitivity: str = Field(default="internal",
                              pattern="^(public|internal|confidential|restricted)$")


class MemoryPatternIn(BaseModel):
    pattern: str = Field(min_length=1, max_length=4000)
    human_confirmed: bool = False
    sensitivity: str = Field(default="internal",
                             pattern="^(public|internal|confidential|restricted)$")


class LeadGenerateIn(BaseModel):
    service_id: str = Field(min_length=1, max_length=80)
    geography: str = Field(min_length=1, max_length=200)
    industry: str = Field(default="startup", max_length=200)
    count: int = Field(default=5, ge=1, le=100)


class EmailDraftIn(BaseModel):
    lead_id: str = Field(min_length=1, max_length=100)
    service_id: str = Field(min_length=1, max_length=80)


class VoiceCallIn(BaseModel):
    command: str = Field(min_length=8, max_length=1000)
    lead_id: str = Field(min_length=1, max_length=100)
    service_id: str = Field(min_length=1, max_length=80)
    confirmed: bool = False
    consent_confirmed: bool = False
    approved_script: bool = False
    handoff_requested: bool = False


class CampaignPlanIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    service_id: str = Field(min_length=1, max_length=80)
    geography: str = Field(min_length=1, max_length=200)
    industry: str = Field(default="startup", max_length=200)
    count: int = Field(default=5, ge=1, le=100)


class CampaignCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    service_id: str = Field(min_length=1, max_length=80)
    lead_ids: list[str] = Field(default_factory=list, max_length=500)


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


class ConsentIn(BaseModel):
    contact_id: str = Field(min_length=1, max_length=100)
    purpose: str = Field(min_length=1, max_length=100)
    consented: bool
    evidence_reference: str = Field(min_length=1, max_length=500)
