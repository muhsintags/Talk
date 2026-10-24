"""
TALK Core Package
"""

from .models import (
    RiskLevel,
    RiskIssue,
    RiskReport,
    CommandSpec,
    ExecChunk,
    ExecResult,
    HistoryEntry,
)
from .config import (
    Config,
    load_config,
    DEFAULT_MODEL,
    AVAILABLE_MODELS,
    CONFIG_DIR,
    CONFIG_PATH,
)
from .security import (
    analyze_command,
    is_dangerous,
    needs_caution,
    get_risk_reasons,
)
from .executor import (
    find_bash,
    execute_stream,
    run_command,
    EXIT_HINTS,
)
from .history import (
    HistoryManager,
)
from .llm import (
    generate_command,
    test_api_connection,
    parse_response,
    resolve_model_name,
)
from .pipeline import TalkPipeline
from .confirm import GateDecision, evaluate_gate

__version__ = "1.1.0"

__all__ = [
    "RiskLevel",
    "RiskIssue",
    "RiskReport",
    "CommandSpec",
    "ExecChunk",
    "ExecResult",
    "HistoryEntry",
    "Config",
    "load_config",
    "DEFAULT_MODEL",
    "AVAILABLE_MODELS",
    "CONFIG_DIR",
    "CONFIG_PATH",
    "analyze_command",
    "is_dangerous",
    "needs_caution",
    "get_risk_reasons",
    "find_bash",
    "execute_stream",
    "run_command",
    "EXIT_HINTS",
    "HistoryManager",
    "generate_command",
    "test_api_connection",
    "parse_response",
    "resolve_model_name",
    "TalkPipeline",
    "GateDecision",
    "evaluate_gate",
    "__version__",
]