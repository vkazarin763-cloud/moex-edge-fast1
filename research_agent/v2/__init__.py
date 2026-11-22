"""Isolated MOEX EDGE v2 research components. Never imported by v1 scanners."""

V2_VERSION = "moex-edge-v2-core-2026-11-21"

from .features import FeatureInputError, extract_ohlcv_features

__all__ = ["V2_VERSION", "FeatureInputError", "extract_ohlcv_features"]
