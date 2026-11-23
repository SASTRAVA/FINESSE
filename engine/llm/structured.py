"""Bounded Pydantic validation for model-produced JSON."""
from __future__ import annotations

import json
from typing import TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class StructuredOutputError(ValueError):
    pass


async def generate_structured(call, schema: type[T], *, max_retries: int = 2) -> T:
    if max_retries < 0 or max_retries > 2:
        raise ValueError("max_retries must be between 0 and 2")
    feedback = "Return only JSON matching the requested schema."
    for attempt in range(max_retries + 1):
        raw = await call(feedback)
        try:
            value = json.loads(raw)
            return schema.model_validate(value)
        except (json.JSONDecodeError, ValidationError) as exc:
            if attempt == max_retries:
                raise StructuredOutputError("model output did not match schema") from exc
            feedback = f"Correct the JSON using these validation errors: {str(exc)[:2000]}"
    raise StructuredOutputError("model output did not match schema")
