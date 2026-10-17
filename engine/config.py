"""
Central configuration. One object, loaded from .env, imported everywhere.
Karpathy rule: no magic — every knob is visible here.
"""
from __future__ import annotations
import os
import logging
import ipaddress
import re
from collections.abc import Mapping
from pathlib import Path
from functools import lru_cache
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent          # .../FINESSE
_IS_VERCEL = bool(os.getenv("VERCEL") or os.getenv("VERCEL_ENV"))
if not _IS_VERCEL:
    load_dotenv(ROOT / ".env")


def _b(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _i(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _csv(name: str, default: str) -> tuple[str, ...]:
    values = tuple(value.strip() for value in _b(name, default).split(",") if value.strip())
    if "*" in values:
        raise ValueError(f"{name} must not contain a wildcard origin")
    return values


def _ips(name: str) -> tuple[str, ...]:
    values = tuple(value.strip() for value in os.environ.get(name, "").split(",")
                   if value.strip())
    try:
        return tuple(str(ipaddress.ip_address(value)) for value in values)
    except ValueError as exc:
        raise ValueError(f"{name} must contain comma-separated IP addresses") from exc


def _rooted_path(name: str, default: str) -> Path:
    value = Path(_b(name, default))
    return (value if value.is_absolute() else ROOT / value).resolve()


def _storage_paths(environ: Mapping[str, str] = os.environ) -> tuple[Path, Path]:
    is_vercel = bool(environ.get("VERCEL") or environ.get("VERCEL_ENV"))
    data_value = environ.get("FINESSE_DATA_DIR", "").strip()
    vault_value = environ.get("VAULT_PATH", "").strip()
    data = (Path(data_value) if data_value else
            Path("/tmp/finesse-data") if is_vercel else ROOT / "data")
    vault = (Path(vault_value) if vault_value else
             Path("/tmp/finesse-vault") if is_vercel else ROOT / "vault")
    if not data.is_absolute():
        data = ROOT / data
    if not vault.is_absolute():
        vault = ROOT / vault
    return data.resolve(), vault.resolve()


def _cors_origins(environ: Mapping[str, str] = os.environ) -> tuple[str, ...]:
    raw_origins = environ.get("CORS_ORIGINS", _DEV_ORIGINS)
    origins = [value.strip() for value in raw_origins.split(",") if value.strip()]
    if "*" in origins:
        raise ValueError("CORS_ORIGINS must not contain a wildcard origin")
    for variable in ("VERCEL_URL", "VERCEL_PROJECT_PRODUCTION_URL"):
        host = environ.get(variable, "").strip().rstrip("/")
        if host and re.fullmatch(r"[A-Za-z0-9.-]+(?::[0-9]{1,5})?", host):
            origin = f"https://{host}"
            if origin not in origins:
                origins.append(origin)
    return tuple(origins)


_DEV_ORIGINS = "http://localhost:8000,http://127.0.0.1:8000"


class Config:
    # --- paths ---
    ROOT = ROOT
    IS_VERCEL = _IS_VERCEL
    ENV = _b("FINESSE_ENV", _b("ENV", "development")).lower()
    HOST = _b("HOST", _b("APP_HOST", "127.0.0.1"))
    PORT = _i("PORT", _i("APP_PORT", 8600))
    APP_HOST = HOST
    APP_PORT = PORT
    CORS_ORIGINS = _cors_origins()
    REDACT_PII_ON_EXTERNAL_LLM = _b("REDACT_PII_ON_EXTERNAL_LLM", "true").lower() in (
        "1", "true", "yes")
    ALLOW_CONFIDENTIAL_EXTERNAL_EGRESS = _b(
        "ALLOW_CONFIDENTIAL_EXTERNAL_EGRESS", "false").lower() in ("1", "true", "yes")
    TRUSTED_PROXY_IPS = _ips("TRUSTED_PROXY_IPS")
    ALLOW_UNENCRYPTED_PUBLIC_BIND = _b(
        "ALLOW_UNENCRYPTED_PUBLIC_BIND", "false").lower() in ("1", "true", "yes")
    REDIS_URL = _b("REDIS_URL")
    DATABASE_URL = _b("DATABASE_URL")
    KMS_MASTER_KEY = _b("KMS_MASTER_KEY")
    SALES_DRY_RUN = _b("SALES_DRY_RUN", "true").lower() in ("1", "true", "yes")
    SALES_LIVE_OUTREACH_ENABLED = _b(
        "SALES_LIVE_OUTREACH_ENABLED", "false").lower() in ("1", "true", "yes")
    EMAIL_PROVIDER = _b("EMAIL_PROVIDER", "sandbox").lower()
    EMAIL_LIVE_ENABLED = _b("EMAIL_LIVE_ENABLED", "false").lower() in ("1", "true", "yes")
    SMTP_HOST = _b("SMTP_HOST")
    SMTP_PORT = _i("SMTP_PORT", 587)
    SMTP_USERNAME = _b("SMTP_USERNAME")
    SMTP_PASSWORD = _b("SMTP_PASSWORD")
    SMTP_FROM = _b("SMTP_FROM")
    EMAIL_WEBHOOK_URL = _b("EMAIL_WEBHOOK_URL")
    EMAIL_WEBHOOK_TOKEN = _b("EMAIL_WEBHOOK_TOKEN")
    PUBLIC_BASE_URL = _b("PUBLIC_BASE_URL", "http://localhost:8600").rstrip("/")
    WEBHOOK_SIGNING_SECRET = _b("WEBHOOK_SIGNING_SECRET")
    VOICE_PROVIDER = _b("VOICE_PROVIDER", "sandbox").lower()
    TWILIO_ACCOUNT_SID = _b("TWILIO_ACCOUNT_SID")
    TWILIO_AUTH_TOKEN = _b("TWILIO_AUTH_TOKEN")
    TWILIO_CALLER_ID = _b("TWILIO_CALLER_ID")
    VOICE_LIVE_ENABLED = _b("VOICE_LIVE_ENABLED", "false").lower() in ("1", "true", "yes")
    VOICE_WEBHOOK_URL = _b("VOICE_WEBHOOK_URL")
    SALES_ENRICHMENT_ENABLED = _b("SALES_ENRICHMENT_ENABLED", "false").lower() in (
        "1", "true", "yes")
    ENRICHMENT_PROVIDER_URL = _b("ENRICHMENT_PROVIDER_URL")
    ENRICHMENT_API_TOKEN = _b("ENRICHMENT_API_TOKEN")
    CALENDAR_PROVIDER = _b("CALENDAR_PROVIDER", "local").lower()
    CALENDAR_SYNC_ENABLED = _b("CALENDAR_SYNC_ENABLED", "false").lower() in ("1", "true", "yes")
    CALENDAR_WEBHOOK_URL = _b("CALENDAR_WEBHOOK_URL")
    CALENDAR_API_TOKEN = _b("CALENDAR_API_TOKEN")
    DATA, VAULT = _storage_paths()
    DATA_DIR = DATA
    VAULT_PATH = VAULT
    UPLOADS = DATA / "uploads"

    # --- inference (NIM now, local later) ---
    NVIDIA_API_KEY = _b("NVIDIA_API_KEY")
    # dedicated key + model for JARVIS so his voice replies never queue behind the swarm
    NVIDIA_API_KEY_JARVIS = _b("NVIDIA_API_KEY_JARVIS")
    NIM_MODEL_JARVIS = _b("NIM_MODEL_JARVIS", "meta/llama-3.1-70b-instruct")
    NIM_BASE_URL = _b("NIM_BASE_URL", "https://integrate.api.nvidia.com/v1")
    # Groq = ultra-fast free inference; the real fix for a SNAPPY real-time JARVIS voice
    GROQ_API_KEY = _b("GROQ_API_KEY")
    GROQ_BASE_URL = _b("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    GROQ_MODEL = _b("GROQ_MODEL", "llama-3.1-8b-instant")
    JARVIS_TIMEOUT_S = _i("JARVIS_TIMEOUT_S", 15)   # hard cap so the voice UI never hangs
    LOCAL_LLM_BASE_URL = _b("LOCAL_LLM_BASE_URL")
    LOCAL_LLM_MODEL = _b("LOCAL_LLM_MODEL")

    # per-lane dedicated NIM keys — eliminate cross-lane rate-limit contention.
    # Set NIM_KEY_CODING / NIM_KEY_MARKETING / ... in .env; empty = falls back to primary.
    LANES = ("coding", "prompt", "marketing", "bizdev", "exec", "general", "security")
    LANE_KEYS = {l: _b(f"NIM_KEY_{l.upper()}") for l in
                 ("coding", "prompt", "marketing", "bizdev", "exec", "general", "security")}
    LANE_CONCURRENCY = _i("LANE_CONCURRENCY", 4)   # in-flight cap PER lane key

    MODELS = {
        "orchestrator": _b("NIM_MODEL_ORCHESTRATOR", "qwen/qwen3-next-80b-a3b-instruct"),
        "coding":       _b("NIM_MODEL_CODING", "qwen/qwen3-next-80b-a3b-instruct"),
        "prompt":       _b("NIM_MODEL_PROMPT", "meta/llama-3.1-70b-instruct"),
        "marketing":    _b("NIM_MODEL_MARKETING", "meta/llama-3.1-70b-instruct"),
        "fast":         _b("NIM_MODEL_FAST", "meta/llama-3.1-8b-instruct"),
    }

    # --- embeddings ---
    EMBEDDINGS_BACKEND = _b("EMBEDDINGS_BACKEND", "local")     # local | nim
    EMBEDDINGS_MODEL_LOCAL = _b("EMBEDDINGS_MODEL_LOCAL", "BAAI/bge-small-en-v1.5")
    EMBEDDINGS_MODEL_NIM = _b("EMBEDDINGS_MODEL_NIM", "nvidia/nv-embedqa-e5-v5")

    # --- vector db ---
    QDRANT_MODE = _b("QDRANT_MODE", "embedded")               # embedded | server
    # resolve to absolute under ROOT so the brain is found regardless of CWD
    QDRANT_PATH = str(_rooted_path("QDRANT_PATH", str(DATA_DIR / "qdrant")))
    QDRANT_URL = _b("QDRANT_URL")
    QDRANT_COLLECTION = _b("QDRANT_COLLECTION", "sastrava_brain")

    # --- auth ---
    JWT_SECRET = _b("JWT_SECRET")
    JWT_EXPIRY_HOURS = _i("JWT_EXPIRY_HOURS", 12)
    CEO_EMAIL = _b("CEO_EMAIL", "ceo@sastrava.ai")
    CEO_PASSWORD = _b("CEO_PASSWORD")

    # --- obsidian ---
    OBSIDIAN_REST_URL = _b("OBSIDIAN_REST_URL")
    OBSIDIAN_API_KEY = _b("OBSIDIAN_API_KEY")

    # --- JARVIS premium voice (optional key -> natural voice; else browser fallback) ---
    OPENAI_API_KEY = _b("OPENAI_API_KEY")
    OPENAI_TTS_MODEL = _b("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
    OPENAI_TTS_VOICE = _b("OPENAI_TTS_VOICE", "onyx")     # onyx/ash = deep male, JARVIS-ish
    ELEVENLABS_API_KEY = _b("ELEVENLABS_API_KEY")
    ELEVENLABS_VOICE_ID = _b("ELEVENLABS_VOICE_ID", "onwK4e9ZLuTAKqWW03F9")  # "Daniel" British male
    ELEVENLABS_MODEL = _b("ELEVENLABS_MODEL", "eleven_turbo_v2_5")
    JARVIS_MODEL_ROLE = _b("JARVIS_MODEL_ROLE", "fast")   # brain tier for spoken replies
    # Edge TTS = FREE Microsoft neural voice, NO API KEY. British male = very JARVIS.
    EDGE_VOICE = _b("EDGE_VOICE", "en-GB-RyanNeural")

    @property
    def voice_provider(self) -> str:
        if self.OPENAI_API_KEY:
            return "openai"
        if self.ELEVENLABS_API_KEY:
            return "elevenlabs"
        return "edge"   # free, natural, no key — the default JARVIS voice

    # --- continuous growth (opt-in) ---
    CRAWLER_ENABLED = _b("CRAWLER_ENABLED", "0") in ("1", "true", "yes")
    CRAWLER_INTERVAL_MIN = _i("CRAWLER_INTERVAL_MIN", 30)
    CRAWLER_QUERIES = [q.strip() for q in _b("CRAWLER_QUERIES").split(",") if q.strip()]
    CRAWLER_LEADGEN = _b("CRAWLER_LEADGEN", "0") in ("1", "true", "yes")
    CRAWLER_ICP = _b("CRAWLER_ICP", "small businesses needing digital marketing")
    CRAWLER_LOCATION = _b("CRAWLER_LOCATION", "")
    REWEAVE_INTERVAL_MIN = _i("REWEAVE_INTERVAL_MIN", 0)   # 0 = off

    # --- skill harvesting from free git repos (opt-in) ---
    SKILL_HARVEST_ENABLED = _b("SKILL_HARVEST_ENABLED", "0") in ("1", "true", "yes")
    SKILL_HARVEST_INTERVAL_MIN = _i("SKILL_HARVEST_INTERVAL_MIN", 360)
    # comma list of "owner/repo" or "owner/repo/sub/path" pointing at .md skill files
    SKILL_REPOS = [r.strip() for r in _b("SKILL_REPOS").split(",") if r.strip()]
    GITHUB_TOKEN = _b("GITHUB_TOKEN")

    # --- agentic loop (Hermes/Claude-style autonomous reasoning) ---
    AGENTIC_MAX_STEPS = _i("AGENTIC_MAX_STEPS", 8)     # max plan->act->observe iterations
    AGENTIC_REFLECT = _b("AGENTIC_REFLECT", "1") in ("1", "true", "yes")  # self-critique pass

    # --- security audit agent (continuous, opt-in watch loop) ---
    SECURITY_AUDIT_ENABLED = _b("SECURITY_AUDIT_ENABLED", "0") in ("1", "true", "yes")
    SECURITY_AUDIT_INTERVAL_MIN = _i("SECURITY_AUDIT_INTERVAL_MIN", 180)
    # baseline security skills harvested once on first watch cycle (train from day one)
    SECURITY_HARVEST_REPOS = [r.strip() for r in _b(
        "SECURITY_HARVEST_REPOS",
        "OWASP/CheatSheetSeries/cheatsheets, swisskyrepo/PayloadsAllTheThings").split(",") if r.strip()]

    # --- Hermes overseer (self-evolving meta-agent) ---
    HERMES_ENABLED = _b("HERMES_ENABLED", "1") in ("1", "true", "yes")
    HERMES_MIN_STARS = _i("HERMES_MIN_STARS", 400)          # only harvest repos with >= this
    HERMES_MAX_NEW_AGENTS = _i("HERMES_MAX_NEW_AGENTS", 1)  # new agent types per evolve cycle
    HERMES_MIN_INTERVAL_S = _i("HERMES_MIN_INTERVAL_S", 45) # rate-limit between evolutions

    # --- concurrency / turboquant ---
    MAX_CONCURRENT_LLM = _i("MAX_CONCURRENT_LLM", 8)
    SWARM_MAX_AGENTS = _i("SWARM_MAX_AGENTS", 64)
    LLM_CACHE_SIZE = _i("LLM_CACHE_SIZE", 512)
    REQUEST_TIMEOUT_S = _i("REQUEST_TIMEOUT_S", 90)

    def ensure_dirs(self) -> None:
        paths = (self.DATA, self.UPLOADS, self.DATA / "qdrant")
        if self.IS_VERCEL:
            paths += (self.VAULT,)
        for p in paths:
            p.mkdir(parents=True, exist_ok=True)

    @property
    def has_nim(self) -> bool:
        return bool(self.NVIDIA_API_KEY) and "PASTE" not in self.NVIDIA_API_KEY

    @property
    def has_local_llm(self) -> bool:
        return bool(self.LOCAL_LLM_BASE_URL)


def validate_runtime_security(config=None) -> None:
    """Fail closed in production; warn loudly in development when auth secrets are unsafe."""
    config = config or cfg
    environment = getattr(config, "ENV", "development")
    if environment not in {"development", "production"}:
        raise RuntimeError("FINESSE_ENV must be 'development' or 'production'")
    placeholders = {"dev-insecure-change-me", "changeme", "0000", "finesse-ceo-2026"}
    def is_placeholder(value: str) -> bool:
        lowered = value.lower()
        return (lowered in placeholders or
                (lowered.startswith("<") and lowered.endswith(">")) or
                any(marker in lowered for marker in ("paste_", "generate_", "set_a_strong_")))

    problems = []
    jwt_secret = str(getattr(config, "JWT_SECRET", "") or "").strip()
    password = str(getattr(config, "CEO_PASSWORD", "") or "").strip()
    if len(jwt_secret) < 32 or is_placeholder(jwt_secret):
        problems.append("JWT_SECRET must be a non-placeholder secret of at least 32 characters")
    if len(password) < 12 or is_placeholder(password):
        problems.append("CEO_PASSWORD must be a non-placeholder password of at least 12 characters")
    host = str(getattr(config, "HOST", "127.0.0.1")).strip().lower()
    loopback = host == "localhost"
    if not loopback:
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = False
    trusted_proxies = getattr(config, "TRUSTED_PROXY_IPS", ())
    if (environment == "production" and not loopback and not trusted_proxies
            and not getattr(config, "ALLOW_UNENCRYPTED_PUBLIC_BIND", False)):
        problems.append(
            "non-loopback production HOST requires TRUSTED_PROXY_IPS for a trusted TLS "
            "reverse proxy or ALLOW_UNENCRYPTED_PUBLIC_BIND=true as an explicit override")
    if not problems:
        return
    message = "Unsafe FINESSE authentication configuration: " + "; ".join(problems)
    if environment == "production":
        raise RuntimeError(message)
    logging.getLogger("finesse.security").critical("%s — development mode is unsafe", message)


def vercel_missing_environment(config=None) -> list[str]:
    """Return required Vercel bootstrap settings that are absent or unsafe."""
    config = config or cfg
    placeholders = {"dev-insecure-change-me", "changeme", "0000", "finesse-ceo-2026"}

    def unsafe(value: str) -> bool:
        lowered = value.casefold()
        return (lowered in placeholders or lowered.startswith("<")
                or any(marker in lowered
                       for marker in ("paste_", "generate_", "set_a_strong_")))

    missing = []
    jwt_secret = str(getattr(config, "JWT_SECRET", "") or "").strip()
    if len(jwt_secret.encode("utf-8")) < 32 or unsafe(jwt_secret):
        missing.append("JWT_SECRET")
    password = str(getattr(config, "CEO_PASSWORD", "") or "").strip()
    if (len(password) < 12 or len(password.encode("utf-8")) > 72
            or unsafe(password)):
        missing.append("CEO_PASSWORD")
    email = os.environ.get("CEO_EMAIL", "").strip()
    if not email:
        missing.append("CEO_EMAIL")
    master_key = str(getattr(config, "KMS_MASTER_KEY", "") or "").strip()
    if len(master_key.encode("utf-8")) < 32 or unsafe(master_key):
        missing.append("KMS_MASTER_KEY")
    return missing


def validate_startup_config(config=None) -> None:
    """Backward-compatible name retained for existing startup callers and tests."""
    validate_runtime_security(config)


@lru_cache
def get_config() -> "Config":
    cfg = Config()
    cfg.ensure_dirs()
    return cfg


cfg = get_config()
