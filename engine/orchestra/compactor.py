"""Bounded conversation compaction preserving citation and security state."""
from __future__ import annotations

import re
from dataclasses import dataclass

_RANK = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}
_CITATION = re.compile(r"\[C\d+\]")
_GATEKEEPER = re.compile(r"\b(?:gatekeeper|approval)[-_ ]?(?:id|#)?\s*[:=]?\s*([A-Za-z0-9_-]{4,})", re.I)


@dataclass(frozen=True)
class CompactedConversation:
    messages: list[dict]
    sensitivity: str
    token_estimate: int
    compacted: bool


def estimate_tokens(messages: list[dict]) -> int:
    return sum(max(1, (len(str(m.get("content", ""))) + 3) // 4) for m in messages)


def compact(messages: list[dict], *, sensitivity: str = "internal", context_limit: int = 32000,
            trigger_ratio: float = 0.7, preserve_tail: int = 6) -> CompactedConversation:
    if sensitivity not in _RANK or not 0.1 <= trigger_ratio <= 0.95:
        raise ValueError("invalid sensitivity or trigger ratio")
    observed = sensitivity
    for message in messages:
        tag = message.get("sensitivity")
        if tag in _RANK and _RANK[tag] > _RANK[observed]:
            observed = tag
    total = estimate_tokens(messages)
    if total <= int(context_limit * trigger_ratio) or len(messages) <= preserve_tail:
        return CompactedConversation(list(messages), observed, total, False)
    older, recent = messages[:-preserve_tail], messages[-preserve_tail:]
    content = "\n".join(str(m.get("content", "")) for m in older)
    citations = list(dict.fromkeys(_CITATION.findall(content)))
    approvals = list(dict.fromkeys(match.group(0) for match in _GATEKEEPER.finditer(content)))
    # Keep recent history untouched; summarize only older turns deterministically.
    summary = content[: max(256, context_limit * 2)]
    state = (f"<compacted_state sensitivity=\"{observed}\">\n{summary}\n"
             f"Verified citation IDs: {', '.join(citations)}\n"
             f"Open approval references: {', '.join(approvals)}\n</compacted_state>")
    compacted = [{"role": "system", "content": state, "sensitivity": observed}, *recent]
    return CompactedConversation(compacted, observed, estimate_tokens(compacted), True)
