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
    for index, bar in enumerate(bars):
        if bar["timestamp"] == timestamp:
            return index
    return None


def cross_sectional_momentum_12_1(
    panel: Mapping[str, Sequence[dict[str, Any]]],
    *,
    as_of: str,
    price_basis_status: str = "unverified",
    min_universe: int = CROSS_SECTIONAL_MIN_UNIVERSE,
) -> dict[str, Any]:
    """Rank the supplied point-in-time universe on common 12-1 session anchors.

    Highest quintile is LONG_CANDIDATE; lowest quintile SHORT_CANDIDATE.
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

    normalized = {}
    for ticker, bars in panel.items():
        if not isinstance(ticker, str) or not ticker:
            raise DataContractError("ticker keys must be non-empty strings")
        validate_bars(bars)
        normalized[ticker] = {bar["timestamp"]: float(bar["close"]) for bar in bars}

    # Use only dates shared by every supplied point-in-time constituent. This
    # prevents a missing/suspended bar from shifting one symbol's return window.
    common_dates = set.intersection(*(set(values) for values in normalized.values()))
    common_dates = sorted(common_dates)
    if as_of not in common_dates:
        return {
            "strategy": "CS_MOM_12_1",
            "status": "UNSYNCHRONIZED_DATA",
            "as_of": as_of,
            "reason": "As-of date is not shared by every supplied universe member",
            "ranked": [],
            "eligible_for_performance_test": False,
        }
    end = common_dates.index(as_of)
    old_index = end - TRADING_SESSIONS_PER_YEAR
    skipped_index = end - SKIP_RECENT_SESSIONS
    if old_index < 0:
        return {
            "strategy": "CS_MOM_12_1",
            "status": "INSUFFICIENT_COMMON_HISTORY",
            "as_of": as_of,
            "common_sessions": len(common_dates[: end + 1]),
            "reason": "Fewer than 253 common completed sessions through as-of date",
            "ranked": [],
            "eligible_for_performance_test": False,
        }

    old_date = common_dates[old_index]
    skipped_date = common_dates[skipped_index]
    ranked = []
    for ticker in sorted(normalized):
        values = normalized[ticker]
        value = values[skipped_date] / values[old_date] - 1.0
        ranked.append({"ticker": ticker, "return_12_1": value})

    if len(ranked) < min_universe:
        return {
            "strategy": "CS_MOM_12_1",
            "status": "INSUFFICIENT_UNIVERSE",
            "as_of": as_of,
            "reason": f"Only {len(ranked)} eligible symbols; minimum is {min_universe}",
            "ranked": [],
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
        "common_anchor_timestamp": old_date,
        "skip_anchor_timestamp": skipped_date,
        "universe_size": len(ranked),
        "long_bucket_size": bucket_size,
        "short_bucket_size": bucket_size,
        "ranked": ranked,
        "reason": "Point-in-time 12-1 ranking on identical common sessions",
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

    The security and IMOEX must match on the as-of date and both anchor dates.
    The result is excess return, not beta-adjusted alpha or a trade signal.
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
            "reason": "Not enough history for lookback and skip window",
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
