"""Local idempotent usage ledger and injectable Stripe Meter adapter."""
from __future__ import annotations

import csv
import io
import time
from typing import Protocol

from ..db.storage import storage


class BillingMeterAdapter(Protocol):
    def emit(self, *, tenant_id: str, metric: str, quantity: int,
             window_hour: str) -> bool: ...


class LocalLedgerOnlyAdapter:
    def __init__(self, repository=storage):
        self.repository = repository

    def emit(self, *, tenant_id: str, metric: str, quantity: int,
             window_hour: str) -> bool:
        if not metric or quantity < 0:
            raise ValueError("metric and non-negative quantity are required")
        event_id = f"{tenant_id}:{window_hour}:{metric}"
        return self.repository.put_if_absent("billing_meter_events", tenant_id, event_id, {
            "metric": metric, "quantity": quantity, "window_hour": window_hour,
            "created_at": time.time(), "adapter": "local"})

    def export_csv(self, tenant_id: str) -> str:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(("event_id", "metric", "quantity", "window_hour", "created_at"))
        for event_id, record in self.repository.list_items("billing_meter_events", tenant_id):
            writer.writerow((event_id, record["metric"], record["quantity"],
                             record["window_hour"], record["created_at"]))
        return output.getvalue()


class StripeMetersAdapter:
    def __init__(self, create_meter_event):
        self.create_meter_event = create_meter_event

    def emit(self, *, tenant_id: str, metric: str, quantity: int,
             window_hour: str) -> bool:
        idempotency_key = f"{tenant_id}:{window_hour}:{metric}"
        return bool(self.create_meter_event(
            event_name=metric, payload={"stripe_customer_id": tenant_id,
                                        "value": str(quantity)},
            identifier=idempotency_key, idempotency_key=idempotency_key))
