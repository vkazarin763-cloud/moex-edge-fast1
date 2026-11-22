"""Isolated MOEX EDGE v2 research components. Never imported by v1 scanners."""

V2_VERSION = "moex-edge-v2-core-2026-11-21"

from .features import FeatureInputError, extract_ohlcv_features
from .execution import ExecutionInputError, evaluate_hypothesis
from .multiple_testing import MultipleTestingInputError, holm_bonferroni
from .bootstrap import BootstrapInputError, moving_block_bootstrap_mean_test

__all__ = ["V2_VERSION", "FeatureInputError", "extract_ohlcv_features", "ExecutionInputError", "evaluate_hypothesis", "MultipleTestingInputError", "holm_bonferroni", "BootstrapInputError", "moving_block_bootstrap_mean_test"]
