"""Built-in connectors. Importing registers them on the shared `mcp` registry."""
from . import vault           # noqa: F401
from . import web             # noqa: F401
from . import github          # noqa: F401
from . import platform_audit  # noqa: F401  (Security Audit Agent's read-only platform sensor)
