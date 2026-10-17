"""Deterministic weighted lead qualification score."""
from __future__ import annotations

WEIGHTS = {"service_fit": 35, "industry_company_fit": 25, "need_evidence": 20,
           "decision_maker_relevance": 10, "contact_confidence": 10}


def score_lead(*, service_fit: float, industry_company_fit: float,
               need_evidence: float, decision_maker_relevance: float,
               contact_confidence: float) -> dict:
    values = locals().copy()
    points = {name: round(max(0.0, min(1.0, values[name])) * weight, 2)
              for name, weight in WEIGHTS.items()}
    return {"score": round(sum(points.values()), 2), "max_score": 100,
            "components": points}
