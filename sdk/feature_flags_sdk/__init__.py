"""SDK do Feature Flags Platform."""
from .client import FlagClient
from .models import EvaluationResult, FlagValue

__all__ = ["FlagClient", "EvaluationResult", "FlagValue"]
__version__ = "1.0.0"
