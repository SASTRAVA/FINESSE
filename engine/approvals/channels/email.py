"""Scanner-safe approval flow helpers; viewing a link never changes approval state."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ApprovalView:
    approval_id: str
    payload: dict
    payload_sha256: str
    status: str


def view_approval(approval_id: str, payload: dict, payload_sha256: str,
                  status: str) -> ApprovalView:
    return ApprovalView(approval_id, dict(payload), payload_sha256, status)


def confirm_approval(*, method: str, authenticated: bool, explicit_confirmation: bool,
                     approve_callback, approval_id: str):
    if method.upper() != "POST":
        raise ValueError("approval confirmation requires POST")
    if not authenticated or not explicit_confirmation:
        raise PermissionError("authenticated explicit confirmation is required")
    return approve_callback(approval_id)
