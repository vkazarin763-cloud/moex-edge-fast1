"""Point-in-time cross-sectional research primitives for MOEX EDGE v2.

The caller supplies the point-in-time eligible universe and already validated
single-security bars. No universe membership is inferred from today's listings.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from .strategies import (
    DataContractError,
    SKIP_RECENT_SESSIONS,
    TRADING_SESSIONS_PER_YEAR,
    VALID_PRICE_BASES,
    validate_bars,
)

CROSS_SECTIONAL_MIN_UNIVERSE = 10
RELATIVE_STRENGTH_LOOKBACK = 126


def _index_for_timestamp(
    bars: Sequence[dict[str, Any]], timestamp: str
) -> int | None:
    # Inputs are strictly ordered, so a simple lookup is deterministic.
    for index, bar in enumerate(bars):
        if bar["timestamp"] == timestamp:
            return index
    return None


def _return_12_1(
    bars: Sequence[dict[str, Any]], end: int, lookback: int
) -> float | None:
    old_index = end - lookback
    skipped_index = end - SKIP_RECENT_SESSIONS
    if old_index < 0 or skipped_index < 0:
        return None
    return float(bars[skipped_index]["close"]) / float(bars[old_index]["close"]) - 1.0


def cross_sectional_momentum_12_1(
    panel: Mapping[str, Sequence[dict[str, Any]]],
    *,
    as_of: str,
    price_basis_status: str = "unverified",
    min_universe: int = CROSS_SECTIONAL_MIN_UNIVERSE,
) -> dict[str, Any]:
    """Rank the explicitly supplied point-in-time universe by 12-1 return.

    Highest quintile is labelled LONG_CANDIDATE; lowest quintile SHORT_CANDIDATE.
    This is a research ranking only, not a portfolio or trade instruction.
    """
    if not isinstance(panel, Mapping) or not panel:
        raise DataContractError("panel must be a non-empty ticker-to-bars mapping")
    if not isinstance(as_of, str) or not as_of:
        raise DataContractError("as_of must be an exact completed-bar timestamp")
    if price_basis_status not in VALID_PRICE_BASES:
        return {
            "strategy": "CS_MOM_12_1",
            "status": "DATA_NOT_READY",
            "as_of": as_of,
            "reason": "Corporate-action/same-share price basis is not verified",
            "ranked": [],
            "eligible_for_performance_test": False,
        }
    if isinstance(min_universe, bool) or not isinstance(min_universe, int) or min_universe < 5:
        raise DataContractError("min_universe must be an integer >= 5")

    ranked = []
    excluded = {}
    for ticker in sorted(panel):
        bars = panel[ticker]
        validate_bars(bars)
        end = _index_for_timestamp(bars, as_of)
        if end is None:
            excluded[ticker] = "NO_EXACT_AS_OF_BAR"
            continue
        value = _return_12_1(bars, end, TRADING_SESSIONS_PER_YEAR)
        if value is None:
            excluded[ticker] = "INSUFFICIENT_252_SESSION_HISTORY"
            continue
        ranked.append({"ticker": ticker, "return_12_1": value})

    if len(ranked) < min_universe:
        return {
            "strategy": "CS_MOM_12_1",
            "status": "INSUFFICIENT_UNIVERSE",
            "as_of": as_of,
            "reason": f"Only {len(ranked)} eligible symbols; minimum is {min_universe}",
            "ranked": [],
            "excluded": excluded,
            "eligible_for_performance_test": False,
        }

    ranked.sort(key=lambda item: (-item["return_12_1"], item["ticker"]))
    bucket_size = max(1, len(ranked) // 5)
    for rank, item in enumerate(ranked, start=1):
        item["rank"] = rank
        item["cohort"] = (
            "LONG_CANDIDATE" if rank <= bucket_size
            else "SHORT_CANDIDATE" if rank > len(ranked) - bucket_size
            else "NEUTRAL"
        )
    return {
        "strategy": "CS_MOM_12_1",
        "status": "READY_FOR_RESEARCH",
        "as_of": as_of,
        "universe_size": len(ranked),
        "long_bucket_size": bucket_size,
        "short_bucket_size": bucket_size,
        "ranked": ranked,
        "excluded": excluded,
        "reason": "Point-in-time 12-1 cross-sectional ranking; no future bars used",
        "eligible_for_performance_test": True,
    }


def relative_strength_vs_imoex(
    security_bars: Sequence[dict[str, Any]],
    imoex_bars: Sequence[dict[str, Any]],
    *,
    as_of: str,
    price_basis_status: str = "unverified",
    lookback_sessions: int = RELATIVE_STRENGTH_LOOKBACK,
) -> dict[str, Any]:
    """Measure 6-month relative performance vs IMOEX, skipping latest 21 sessions.

    Both instruments must contain the exact same formation timestamp and both
    historical anchor timestamps. The result is excess return in percentage
    points; it is not beta-adjusted alpha and is not a directional trade signal.
    """
    validate_bars(security_bars)
    validate_bars(imoex_bars)
    if price_basis_status not in VALID_PRICE_BASES:
        return {
            "strategy": "RS_VS_IMOEX_6M_1M",
            "status": "DATA_NOT_READY",
            "as_of": as_of,
            "excess_return": None,
            "reason": "Corporate-action/same-share price basis is not verified",
            "eligible_for_performance_test": False,
        }
    if isinstance(lookback_sessions, bool) or not isinstance(lookback_sessions, int):
        raise DataContractError("lookback_sessions must be an integer")
    if lookback_sessions <= SKIP_RECENT_SESSIONS:
        raise DataContractError("lookback_sessions must exceed skipped recent sessions")

    sec_end = _index_for_timestamp(security_bars, as_of)
    idx_end = _index_for_timestamp(imoex_bars, as_of)
    if sec_end is None or idx_end is None:
        return {
            "strategy": "RS_VS_IMOEX_6M_1M",
            "status": "UNSYNCHRONIZED_DATA",
            "as_of": as_of,
            "excess_return": None,
            "reason": "Security and IMOEX do not both contain the exact as-of timestamp",
            "eligible_for_performance_test": False,
        }

    sec_old = sec_end - lookback_sessions
    sec_skip = sec_end - SKIP_RECENT_SESSIONS
    idx_old = idx_end - lookback_sessions
    idx_skip = idx_end - SKIP_RECENT_SESSIONS
    if min(sec_old, sec_skip, idx_old, idx_skip) < 0:
        return {
            "strategy": "RS_VS_IMOEX_6M_1M",
            "status": "INSUFFICIENT_DATA",
            "as_of": as_of,
            "excess_return": None,
            "reason": "Not enough synchronized history for lookback and skip window",
            "eligible_for_performance_test": False,
        }

    anchor_timestamp = security_bars[sec_old]["timestamp"]
    skipped_timestamp = security_bars[sec_skip]["timestamp"]
    if (
        imoex_bars[idx_old]["timestamp"] != anchor_timestamp
        or imoex_bars[idx_skip]["timestamp"] != skipped_timestamp
    ):
        return {
            "strategy": "RS_VS_IMOEX_6M_1M",
            "status": "UNSYNCHRONIZED_DATA",
            "as_of": as_of,
            "excess_return": None,
            "reason": "Security and IMOEX lookback anchor sessions do not match exactly",
            "eligible_for_performance_test": False,
        }

    sec_return = (
        float(security_bars[sec_skip]["close"])
        / float(security_bars[sec_old]["close"]) - 1.0
    )
    idx_return = (
        float(imoex_bars[idx_skip]["close"])
        / float(imoex_bars[idx_old]["close"]) - 1.0
    )
    return {
        "strategy": "RS_VS_IMOEX_6M_1M",
        "status": "READY_FOR_RESEARCH",
        "as_of": as_of,
        "security_return": sec_return,
        "imoex_return": idx_return,
        "excess_return": sec_return - idx_return,
        "lookback_sessions": lookback_sessions,
        "skipped_recent_sessions": SKIP_RECENT_SESSIONS,
        "reason": "Synchronized 6m-minus-1m relative return; not beta-adjusted alpha",
        "eligible_for_performance_test": True,
    }
