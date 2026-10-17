"""Process-wide emergency stop for state-changing integrations."""

_EMERGENCY_STOP_ACTIVE = False


def emergency_stop_active() -> bool:
    return _EMERGENCY_STOP_ACTIVE


def activate_emergency_stop() -> None:
    global _EMERGENCY_STOP_ACTIVE
    _EMERGENCY_STOP_ACTIVE = True
