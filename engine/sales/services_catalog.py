"""Approved service facts shared by sales drafts and consulting workflows."""
from __future__ import annotations

SERVICES = (
    {"id": "software_development", "name": "Software Development",
     "pillars": ["software_build", "ai_automation"],
     "target_industries": [], "ideal_company_size": "not configured",
     "target_countries_regions": "caller-specified",
     "decision_maker_roles": ["Founder or CEO", "CTO", "CIO", "Product Manager"],
     "approved_offerings": ["custom software", "web and mobile applications",
                            "software integration"],
     "customer_pain_points": [], "approved_differentiators": [],
     "approved_case_studies": [], "default_qualification_criteria": [],
     "approved_claims": ["SASTRAVA provides software development and delivery services."],
     "disallowed_claims": ["guaranteed revenue", "guaranteed delivery date",
                           "unverified client results"],
     "email_templates": ["service_intro"],
     "template": "Hello {company},\n\nSASTRAVA provides software development services. "
                 "If custom software or mobile applications are a current priority, "
                 "we can discuss scope and constraints.\n\nRegards,\nSASTRAVA"},
    {"id": "digital_marketing", "name": "Digital Marketing",
     "pillars": ["seo_digital_growth"],
     "target_industries": [], "ideal_company_size": "not configured",
     "target_countries_regions": "caller-specified",
     "decision_maker_roles": ["CMO", "Marketing Director", "Head of Growth"],
     "approved_offerings": ["SEO", "content strategy", "digital campaigns"],
     "customer_pain_points": [], "approved_differentiators": [],
     "approved_case_studies": [], "default_qualification_criteria": [],
     "approved_claims": ["SASTRAVA provides digital marketing and growth services."],
     "disallowed_claims": ["guaranteed rankings", "guaranteed leads", "unverified ROI"],
     "email_templates": ["service_intro"],
     "template": "Hello {company},\n\nSASTRAVA provides digital marketing services. "
                 "If search or campaign planning is relevant, we can discuss your goals "
                 "and constraints.\n\nRegards,\nSASTRAVA"},
    {"id": "content_media", "name": "Content and Media",
     "pillars": ["seo_digital_growth"],
     "target_industries": [], "ideal_company_size": "not configured",
     "target_countries_regions": "caller-specified",
     "decision_maker_roles": ["Content Head", "Creative Director", "Brand Manager"],
     "approved_offerings": ["content production", "media strategy", "brand content"],
     "customer_pain_points": [], "approved_differentiators": [],
     "approved_case_studies": [], "default_qualification_criteria": [],
     "approved_claims": ["SASTRAVA provides content and media services."],
     "disallowed_claims": ["guaranteed audience growth", "unverified engagement results"],
     "email_templates": ["service_intro"],
     "template": "Hello {company},\n\nSASTRAVA provides content and media services. "
                 "If content planning or production is a current need, we can compare "
                 "requirements.\n\nRegards,\nSASTRAVA"},
    {"id": "edutech", "name": "Edutech",
     "pillars": ["digital_learning"],
     "target_industries": [], "ideal_company_size": "not configured",
     "target_countries_regions": "caller-specified",
     "decision_maker_roles": ["Institution Director", "Principal", "L&D Head", "EdTech Founder"],
     "approved_offerings": ["digital learning design", "learning platforms",
                            "education technology"],
     "customer_pain_points": [], "approved_differentiators": [],
     "approved_case_studies": [], "default_qualification_criteria": [],
     "approved_claims": ["SASTRAVA provides digital learning and Edutech services."],
     "disallowed_claims": ["guaranteed learning outcomes", "unverified student results"],
     "email_templates": ["service_intro"],
     "template": "Hello {company},\n\nSASTRAVA provides digital learning and Edutech "
                 "services. If learning design or platform work is relevant, we can "
                 "discuss the intended audience.\n\nRegards,\nSASTRAVA"},
)

_BY_ID = {item["id"]: item for item in SERVICES}


def get_service(service_id: str) -> dict | None:
    return _BY_ID.get(service_id)
