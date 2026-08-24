"""evpred -- hybrid LLM + classical ML event prediction from unstructured text.

Built as a direct response to the gap analysis in Bhattacharjee et al.,
"Survey and Gap Analysis on Event Prediction of English Unstructured Texts".
See ``docs/01-survey-gap-analysis.md`` for the gap-to-component mapping.
"""

from .backtest import BacktestConfig, BacktestResult, run_backtest, summarise
from .calibration import Calibrator, SplitConformal, coverage_report
from .embedding import HashingSVDEmbedder, get_embedder
from .evidence import extract_precursors, precursor_report
from .extraction import LLMExtractor, RuleExtractor, get_extractor
from .metrics import evaluate, format_metrics
from .nmil import NestedMIL, NestedMILConfig
from .schema import BagGroup, Document, Event, Forecast, Precursor
from .stacking import HybridConfig, HybridEventPredictor
from .synthetic import EventSimulator, SimConfig, make_dataset

__version__ = "0.1.0"

__all__ = [
    "BacktestConfig", "BacktestResult", "run_backtest", "summarise",
    "Calibrator", "SplitConformal", "coverage_report",
    "HashingSVDEmbedder", "get_embedder",
    "extract_precursors", "precursor_report",
    "LLMExtractor", "RuleExtractor", "get_extractor",
    "evaluate", "format_metrics",
    "NestedMIL", "NestedMILConfig",
    "BagGroup", "Document", "Event", "Forecast", "Precursor",
    "HybridConfig", "HybridEventPredictor",
    "EventSimulator", "SimConfig", "make_dataset",
    "__version__",
]
