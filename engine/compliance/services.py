"""Operational consent, incident, and DSAR records; no legal conclusion is implied."""
from __future__ import annotations

import hashlib
import json
import time
import uuid

from ..audit.pg_audit import audit_log
from ..db.storage import storage


class ComplianceService:
    def __init__(self, repository=storage):
        self.repository = repository

    def grant_consent(self, tenant_id: str, principal_id: str, purpose: str,
                      notice_version: str) -> dict:
        consent_id = uuid.uuid4().hex
        value = {"principal_id": principal_id, "purpose_code": purpose,
                 "notice_version": notice_version, "granted_at": time.time(),
                 "withdrawn_at": None, "status": "GRANTED"}
        self.repository.put("consent_records", tenant_id, consent_id, value)
        audit_log.append(tenant_id, {"event": "consent.granted", "principal_id": principal_id,
                                     "purpose": purpose, "record_id": consent_id})
        return {"id": consent_id, **value}

    def withdraw_consent(self, tenant_id: str, consent_id: str, *, actor: str) -> dict:
        record = self.repository.get("consent_records", tenant_id, consent_id)
        if not record:
            raise KeyError("consent record not found")
        record.update({"status": "WITHDRAWN", "withdrawn_at": time.time(),
                       "withdrawn_by": actor})
        self.repository.put("consent_records", tenant_id, consent_id, record)
        audit_log.append(tenant_id, {"event": "consent.withdrawn", "record_id": consent_id,
                                     "actor": actor})
        return record

    def create_dsar(self, tenant_id: str, principal_id: str, request_type: str) -> dict:
        if request_type not in {"ACCESS", "CORRECTION", "ERASURE", "GRIEVANCE"}:
            raise ValueError("unsupported data-subject request")
        now = time.time()
        request_id = uuid.uuid4().hex
        record = {"principal_id": principal_id, "request_type": request_type,
                  "submitted_at": now, "sla_due_at": now + 90 * 86400,
                  "completed_at": None, "status": "OPEN"}
        self.repository.put("dsar_erasure_requests", tenant_id, request_id, record)
        audit_log.append(tenant_id, {"event": "dsar.created", "request_id": request_id,
                                     "request_type": request_type})
        return {"id": request_id, **record}

    def create_breach_incident(self, tenant_id: str, severity: str,
                               affected_records_count: int) -> dict:
        if severity not in {"low", "medium", "high", "critical"} or affected_records_count < 0:
            raise ValueError("severity or affected record count is invalid")
        incident_id, now = uuid.uuid4().hex, time.time()
        record = {"incident_id": incident_id, "discovered_at": now,
                  "report_due_at": now + 72 * 3600, "severity": severity,
                  "affected_records_count": affected_records_count,
                  "initial_notification_at": None, "detailed_report_at": None,
                  "containment_actions": [], "status": "OPEN"}
        self.repository.put("breach_incidents", tenant_id, incident_id, record)
        audit_log.append(tenant_id, {"event": "breach.incident_opened", "incident_id": incident_id,
                                     "severity": severity})
        return record

    def retention_candidates(self, tenant_id: str, *, now: float | None = None,
                             minimum_days: int = 365) -> list[dict]:
        if minimum_days < 365:
            raise ValueError("configured audit retention must be at least 365 days")
        cutoff = (time.time() if now is None else now) - minimum_days * 86400
        candidates = []
        for table in ("audit_logs", "llm_usage_ledger"):
            for record_id, record in self.repository.list_items(table, tenant_id):
                created = float(record.get("created_at", 0))
                if created and created < cutoff and not record.get("legal_hold"):
                    digest = hashlib.sha256(json.dumps(record, sort_keys=True, default=str)
                                            .encode()).hexdigest()
                    candidates.append({"table": table, "record_id": record_id,
                                       "tombstone_hash": digest})
        return candidates


compliance = ComplianceService()
