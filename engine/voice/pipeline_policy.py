"""Voice pipeline privacy and side-effect approval rules."""


def require_local_audio_provider(sensitivity: str, provider: str) -> None:
    if sensitivity not in {"public", "internal", "confidential", "restricted"}:
        raise ValueError("unsupported sensitivity")
    if sensitivity in {"confidential", "restricted"} and provider != "local":
        raise PermissionError("sensitive voice data requires local speech services")


def side_effect_disposition(is_write_action: bool) -> str:
    return "gatekeeper_required" if is_write_action else "read_only_allowed"
