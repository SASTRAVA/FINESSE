"""
LLM provider — one async interface, three backends, chosen at call time.

  hosted NIM  (free tier)     -> now
  local GPU   (vLLM/TRT-LLM)  -> auto-used for heavy roles once LOCAL_LLM_BASE_URL is set
  echo        (no key)        -> offline stub so the whole system still boots & demos

Every call flows through TurboQuant (concurrency + cache). Retries handle
free-tier 429s with backoff.
"""
from __future__ import annotations
import asyncio
import logging
import re
from typing import Optional

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from ..config import cfg
from .turboquant import turbo

try:
    from openai import AsyncOpenAI, RateLimitError, APIError
    _OPENAI = True
except Exception:  # noqa: BLE001
    _OPENAI = False
    RateLimitError = APIError = Exception  # type: ignore


class DataEgressBlocked(RuntimeError):
    """Raised when sensitivity policy prevents sending a prompt to a cloud provider."""


_SENSITIVITY_ORDER = ("public", "internal", "confidential", "restricted")


def is_sensitive_for_egress(sensitivity: str) -> bool:
    if sensitivity not in _SENSITIVITY_ORDER:
        raise ValueError(f"unsupported sensitivity: {sensitivity}")
    return sensitivity in ("confidential", "restricted")


def ensure_external_egress_allowed(sensitivity: str, channel: str) -> None:
    if is_sensitive_for_egress(sensitivity) and not cfg.ALLOW_CONFIDENTIAL_EXTERNAL_EGRESS:
        logging.getLogger("finesse.security").error(
            "Blocked external %s egress for %s-sensitivity data; payload omitted",
            channel, sensitivity)
        raise DataEgressBlocked(
            f"{sensitivity} data blocked from external {channel} egress by policy")


_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(?:nvapi-[A-Za-z0-9_-]{16,}|gsk_[A-Za-z0-9_-]{16,}|"
               r"sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,})\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*"),
)
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE = re.compile(r"(?<!\w)(?:\+?\d[\d().\-\s]{7,}\d)(?!\w)")


def scrub_outbound(text: str, *, redact_pii: bool = True) -> str:
    """Remove recognizable credentials and (optionally) email/phone PII before egress."""
    result = text or ""
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub("[REDACTED_SECRET]", result)
    if redact_pii:
        result = _EMAIL.sub("[REDACTED_EMAIL]", result)
        result = _PHONE.sub("[REDACTED_PHONE]", result)
    return result


class LLM:
    """Async, backend-agnostic chat completion."""

    def __init__(self):
        self._nim: Optional["AsyncOpenAI"] = None
        self._local: Optional["AsyncOpenAI"] = None
        self._jarvis: Optional["AsyncOpenAI"] = None
        if _OPENAI and cfg.has_nim:
            self._nim = AsyncOpenAI(base_url=cfg.NIM_BASE_URL, api_key=cfg.NVIDIA_API_KEY,
                                    timeout=cfg.REQUEST_TIMEOUT_S)
        if _OPENAI and cfg.has_local_llm:
            self._local = AsyncOpenAI(base_url=cfg.LOCAL_LLM_BASE_URL, api_key="local",
                                      timeout=cfg.REQUEST_TIMEOUT_S)
        # JARVIS gets a DEDICATED key + concurrency lane so his replies never queue
        # behind the agent swarm / security loop on the shared key.
        if _OPENAI and cfg.NVIDIA_API_KEY_JARVIS and "PASTE" not in cfg.NVIDIA_API_KEY_JARVIS:
            self._jarvis = AsyncOpenAI(base_url=cfg.NIM_BASE_URL, api_key=cfg.NVIDIA_API_KEY_JARVIS,
                                       timeout=cfg.JARVIS_TIMEOUT_S)
        # Groq: ultra-fast free inference — preferred for JARVIS's real-time voice
        self._groq: Optional["AsyncOpenAI"] = None
        if _OPENAI and cfg.GROQ_API_KEY:
            self._groq = AsyncOpenAI(base_url=cfg.GROQ_BASE_URL, api_key=cfg.GROQ_API_KEY,
                                     timeout=cfg.JARVIS_TIMEOUT_S)
        self._jarvis_sem = asyncio.Semaphore(4)
        # per-lane dedicated NIM keys: each lane gets its own client + concurrency lane,
        # so coding/marketing/security/... never fight one key's rate limit.
        self._lane_clients: dict[str, "AsyncOpenAI"] = {}
        self._lane_sems: dict[str, asyncio.Semaphore] = {}
        if _OPENAI:
            for lane, key in cfg.LANE_KEYS.items():
                if key and "PASTE" not in key:
                    self._lane_clients[lane] = AsyncOpenAI(
                        base_url=cfg.NIM_BASE_URL, api_key=key, timeout=cfg.REQUEST_TIMEOUT_S)
                    self._lane_sems[lane] = asyncio.Semaphore(cfg.LANE_CONCURRENCY)

    def _lane_backend(self, lane: str | None, role: str):
        """(client, model, semaphore) for a lane — its own key if set, else the shared primary."""
        client = self._lane_clients.get(lane) if lane else None
        if client is not None:
            return client, cfg.MODELS.get(role, cfg.MODELS["fast"]), self._lane_sems[lane]
        c, m = self._route(role)
        return c, m, turbo._sem

    def lanes_status(self) -> dict:
        """Which lanes have a dedicated key (for the monitor)."""
        return {lane: {"dedicated_key": lane in self._lane_clients,
                       "in_flight": (cfg.LANE_CONCURRENCY - self._lane_sems[lane]._value)
                       if lane in self._lane_sems else None}
                for lane in cfg.LANES}

    # ---- backend selection -------------------------------------------------
    def _route(self, role: str):
        """Heavy roles prefer local GPU when available; else hosted NIM."""
        heavy = role in ("orchestrator", "coding")
        if heavy and self._local is not None:
            return self._local, (cfg.LOCAL_LLM_MODEL or cfg.MODELS.get(role, cfg.MODELS["fast"]))
        if self._nim is not None:
            return self._nim, cfg.MODELS.get(role, cfg.MODELS["fast"])
        if self._local is not None:
            return self._local, (cfg.LOCAL_LLM_MODEL or "local")
        return None, cfg.MODELS.get(role, cfg.MODELS["fast"])

    def _select_backend(self, role: str, lane: str | None, sensitivity: str):
        order = ("public", "internal", "confidential", "restricted")
        if sensitivity not in order:
            raise ValueError(f"unsupported sensitivity: {sensitivity}")
        if (sensitivity in ("confidential", "restricted")
                and not cfg.ALLOW_CONFIDENTIAL_EXTERNAL_EGRESS):
            if self._local is not None:
                return (self._local, cfg.LOCAL_LLM_MODEL or cfg.MODELS.get(role, "local"),
                        turbo._sem)
            if any((self._nim, self._jarvis, self._groq, *self._lane_clients.values())):
                logging.getLogger("finesse.security").error(
                    "Blocked external LLM egress for %s-sensitivity prompt; no prompt data logged",
                    sensitivity)
                raise DataEgressBlocked(
                    f"{sensitivity} prompt blocked: configure LOCAL_LLM_BASE_URL or explicitly "
                    "allow confidential external egress")
        client, model, sem = self._lane_backend(lane, role)
        return client, model, sem

    @staticmethod
    def _scrub(text: str) -> str:
        return scrub_outbound(text, redact_pii=cfg.REDACT_PII_ON_EXTERNAL_LLM)

    # ---- resilient completion --------------------------------------------
    @retry(reraise=True, stop=stop_after_attempt(4),
           wait=wait_exponential(multiplier=1, min=1, max=20),
           retry=retry_if_exception_type((RateLimitError, APIError)))
    async def _create(self, client, *, sem=None, **kwargs):
        """Concurrency-bounded chat.completion with free-tier retry/backoff. `sem` is the
        lane's own semaphore (per-lane key isolation) or the shared global one.
        APIError is the base for APITimeoutError/APIConnectionError, so slow-tier
        timeouts and 429s are all retried here — one hiccup no longer kills an agent run."""
        async with (sem or turbo._sem):
            return await client.chat.completions.create(**kwargs)

    # ---- public API --------------------------------------------------------
    async def chat(self, system: str, user: str, role: str = "fast",
                   temperature: float = 0.3, max_tokens: int = 1200,
                   sensitivity: str = "internal", lane: str | None = None) -> str:
        client, model, _ = self._select_backend(role, lane, sensitivity)
        system, user = self._scrub(system), self._scrub(user)
        prompt = f"SYS::{system}\nUSR::{user}"

        if client is None:  # no backend configured -> offline stub, system still works
            async def _echo() -> str:
                return (f"[OFFLINE MODE — set NVIDIA_API_KEY to enable real inference]\n"
                        f"role={role} model={model}\n"
                        f"Would answer: {user[:280]}")
            if sensitivity in ("confidential", "restricted"):
                return await _echo()
            return await turbo.run(model, prompt, temperature, _echo)

        @retry(reraise=True,
               stop=stop_after_attempt(4),
               wait=wait_exponential(multiplier=1, min=1, max=20),
               retry=retry_if_exception_type((RateLimitError, APIError)))
        async def _call() -> str:
            resp = await client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content or ""

        if sensitivity in ("confidential", "restricted"):
            return await _call()
        return await turbo.run(model, prompt, temperature, _call)

    async def chat_with_tools(self, system: str, user: str, *, role: str,
                              tool_schemas: list[dict], dispatch,
                              temperature: float = 0.3, max_tokens: int = 1600,
                              max_rounds: int = 2, lane: str | None = None,
                              sensitivity: str = "internal") -> str:
        """
        Tool-calling loop (OpenAI/NIM function-calling). `dispatch(name, args)` must
        be an async fn returning a string tool result. Falls back to plain chat when
        no real backend is configured. Not cached (tool calls are dynamic).
        """
        import json
        client, model, sem = self._select_backend(role, lane, sensitivity)
        system, user = self._scrub(system), self._scrub(user)
        if client is None:
            return await self.chat(system, user, role=role, temperature=temperature,
                                   max_tokens=max_tokens, sensitivity=sensitivity, lane=lane)

        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        last = ""
        for _ in range(max_rounds):
            resp = await self._create(
                client, sem=sem, model=model, messages=messages, tools=tool_schemas,
                tool_choice="auto", temperature=temperature, max_tokens=max_tokens)
            msg = resp.choices[0].message
            last = msg.content or last
            if not getattr(msg, "tool_calls", None):
                return msg.content or last
            messages.append({
                "role": "assistant", "content": msg.content or None,
                "tool_calls": [{"id": tc.id, "type": "function",
                                "function": {"name": tc.function.name,
                                             "arguments": tc.function.arguments}}
                               for tc in msg.tool_calls]})
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except Exception:  # noqa: BLE001
                    args = {}
                result = await dispatch(tc.function.name, args)
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": self._scrub(result)})
        # ran out of rounds — ask for a final answer with no more tools
        resp = await self._create(
            client, sem=sem, model=model, messages=messages, temperature=temperature, max_tokens=max_tokens)
        return resp.choices[0].message.content or last

    async def agentic_loop(self, system: str, task_prompt: str, *, role: str,
                           tool_schemas: list[dict], dispatch, on_step,
                           temperature: float = 0.3, max_tokens: int = 1600,
                           max_steps: int = 8, lane: str | None = None,
                           sensitivity: str = "internal") -> tuple[str, int]:
        """
        Hermes/Claude-style autonomous loop: the model plans, calls tools, observes
        the results, and keeps going until it produces a final answer (a turn with
        no tool calls) or hits max_steps. `on_step(n, kind, detail)` streams progress.
        Returns (final_text, steps_taken).
        """
        import json
        client, model, sem = self._select_backend(role, lane, sensitivity)
        system, task_prompt = self._scrub(system), self._scrub(task_prompt)
        if client is None:
            return await self.chat(system, task_prompt, role=role, temperature=temperature,
                                   max_tokens=max_tokens, sensitivity=sensitivity, lane=lane), 1
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": task_prompt}]
        last = ""
        step = 0
        for step in range(1, max_steps + 1):
            resp = await self._create(
                client, sem=sem, model=model, messages=messages,
                tools=tool_schemas or None,
                tool_choice=("auto" if tool_schemas else None),
                temperature=temperature, max_tokens=max_tokens)
            msg = resp.choices[0].message
            calls = getattr(msg, "tool_calls", None)
            if calls:
                names = ", ".join(tc.function.name for tc in calls)
                await on_step(step, "act", f"using {names}")
                messages.append({"role": "assistant", "content": msg.content or None,
                                 "tool_calls": [{"id": tc.id, "type": "function",
                                                 "function": {"name": tc.function.name,
                                                              "arguments": tc.function.arguments}}
                                                for tc in calls]})
                for tc in calls:
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except Exception:  # noqa: BLE001
                        args = {}
                    result = await dispatch(tc.function.name, args)
                    messages.append({"role": "tool", "tool_call_id": tc.id,
                                     "content": self._scrub(result)})
                continue
            # a turn with no tool calls == the agent is done
            last = msg.content or last
            await on_step(step, "observe", "reached a conclusion")
            return last, step
        return last, step

    async def reflect(self, system: str, task: str, draft: str, *, role: str,
                      max_tokens: int = 1800, lane: str | None = None,
                      sensitivity: str = "internal") -> str:
        """One self-critique + improve pass (the Claude-style reflection step)."""
        client, model, sem = self._select_backend(role, lane, sensitivity)
        if client is None:
            return draft
        system, task, draft = self._scrub(system), self._scrub(task), self._scrub(draft)
        prompt = (f"# Task\n{task}\n\n# Your draft\n{draft}\n\n"
                  f"Critique your draft for correctness, completeness, and — critically — "
                  f"FAITHFULNESS (did you invent any facts, names, numbers, or data not given?). "
                  f"Then output the improved FINAL deliverable only (no meta-commentary), "
                  f"ending with a short 'Needs human review:' note.")
        resp = await self._create(
            client, sem=sem, model=model, messages=[{"role": "system", "content": system},
                                                    {"role": "user", "content": prompt}],
            temperature=0.2, max_tokens=max_tokens)
        return resp.choices[0].message.content or draft

    async def jarvis_say(self, system: str, user: str, *, temperature: float = 0.6,
                         max_tokens: int = 180, sensitivity: str = "internal") -> str:
        """JARVIS's spoken reply. Picks the FASTEST available brain (Groq > dedicated NIM
        key > shared fast lane) and hard-caps the wait so the voice UI NEVER hangs — on a
        slow/failed call it returns a graceful in-character line instead of blocking."""
        if sensitivity in ("confidential", "restricted") and not cfg.ALLOW_CONFIDENTIAL_EXTERNAL_EGRESS:
            client, model, _ = self._select_backend(cfg.JARVIS_MODEL_ROLE, None, sensitivity)
            if client is not None and client not in (self._local,):
                raise DataEgressBlocked(f"{sensitivity} prompt cannot use a remote JARVIS provider")
        elif self._groq is not None:
            client, model = self._groq, cfg.GROQ_MODEL
        elif self._jarvis is not None:
            client, model = self._jarvis, cfg.NIM_MODEL_JARVIS
        else:
            client = model = None

        async def _call() -> str:
            if client is None:   # no dedicated brain -> shared fast lane
                return await self.chat(system, user, role=cfg.JARVIS_MODEL_ROLE,
                                       temperature=temperature, max_tokens=max_tokens,
                                       sensitivity=sensitivity)
            async with self._jarvis_sem:
                resp = await client.chat.completions.create(
                    model=model, messages=[{"role": "system", "content": self._scrub(system)},
                                           {"role": "user", "content": self._scrub(user)}],
                    temperature=temperature, max_tokens=max_tokens)
            return resp.choices[0].message.content or ""

        try:
            return await asyncio.wait_for(_call(), timeout=cfg.JARVIS_TIMEOUT_S)
        except DataEgressBlocked:
            raise
        except Exception:  # noqa: BLE001 — never hang the voice loop
            return "Apologies, sir — my inference link is running slow this moment. Ask me again."

    def backend_name(self) -> str:
        if self._local is not None:
            return "local-gpu+nim" if self._nim else "local-gpu"
        if self._nim is not None:
            return "nim-hosted"
        return "offline-stub"


llm = LLM()
