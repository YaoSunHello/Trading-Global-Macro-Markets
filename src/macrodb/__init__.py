"""macrodb: provider-agnostic historical financial & economic database."""
from .access import MacroDB
from .settings import Settings

__all__ = ["MacroDB", "Settings"]
__version__ = "0.1.0"
