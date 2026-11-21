"""Independent structural audit of MOEX EDGE research reports.

This validator checks holdout separation, walk-forward chronology, doubled-cost
claims, experiment-lab completeness, independent signal/execution replay parity,
and raw-to-history reconciliation metadata. It does not certify profitability
or independently establish the provenance of MOEX source data.
"""
from __future__ import annotations

from datetime import date
import math
from typing import Any


PASS = "DEVELOPMENT_SCREEN_PASS_UNADJUSTED"
FAIL = "REJECT_OR_INSUFFICIENT_EVIDENCE"


def _as_date(value: Any, field: str, errors: list[str]) -> date | None:
    if not isinstance(value, str):
        errors.append(f"{field}: expected ISO date string")
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        errors.append(f"{field}: invalid ISO date {value!r}")
        return None


def _audit_cost_claims(ticker: str, result: dict[str, Any],
                       errors: list[str], warnings: list[str]) -> int:
    stress = result.get("adversarial_cost_check")
    if not isinstance(stress, dict):
        warnings.append(f"{ticker}: no doubled-cost audit present")
        return 0
    baseline_cfg = stress.get("baseline_execution_config")
    stressed_cfg = stress.get("double_cost_execution_config")
    if not isinstance(baseline_cfg, dict) or not isinstance(stressed_cfg, dict):
        errors.append(f"{ticker}: missing execution configuration in cost audit")
    else:
        for key in ("fee_per_side", "slippage_per_side"):
            base = baseline_cfg.get(key)
            doubled = stressed_cfg.get(key)
            if not isinstance(base, (int, float)) or not isinstance(doubled, (int, float)):
                errors.append(f"{ticker}: invalid {key} in cost audit")
            elif abs(doubled - 2 * base) > 1e-12:
                errors.append(f"{ticker}: {key} is not doubled in stress configuration")

    candidates = stress.get("candidates", {})
    if not isinstance(candidates, dict):
        errors.append(f"{ticker}: cost audit candidates must be an object")
        return 0
    checked = 0
    for name, candidate in candidates.items():
        if not isinstance(candidate, dict):
            errors.append(f"{ticker}/{name}: malformed cost candidate")
            continue
        checked += 1
        baseline_pass = candidate.get("baseline_status") == PASS
        stressed_pass = candidate.get("double_cost_status") == PASS
        stressed_mean = candidate.get("double_cost_average_net_return")
        should_survive = (
            baseline_pass and stressed_pass
            and isinstance(stressed_mean, (int, float))
            and stressed_mean > 0
        )
        if candidate.get("survives_double_costs") is True and not should_survive:
            errors.append(
                f"{ticker}/{name}: false double-cost survival claim; "
                "both screens and positive stressed return are required"
            )
        if candidate.get("survives_double_costs") is True and should_survive:
            continue
        if candidate.get("survives_double_costs") not in (True, False):
            errors.append(f"{ticker}/{name}: survival flag must be boolean")
    return checked



def _audit_experiment_lab(
    lab: Any, results: dict[str, Any], holdout_start: date | None,
    errors: list[str], warnings: list[str],
) -> tuple[int, int]:
    """Audit experiment-lab completeness and metadata without trusting its labels."""
    if lab is None:
        return 0, 0
    if not isinstance(lab, dict):
        errors.append("experiment_lab must be an object")
        return 0, 0
    status = lab.get("status")
    if status == "EXPERIMENT_LAB_ERROR":
        warnings.append("experiment lab did not complete: " + str(lab.get("error", "unknown error")))
        return 0, 0
    if status != "EXPERIMENT_LAB_COMPLETE":
        errors.append("experiment_lab must explicitly declare EXPERIMENT_LAB_COMPLETE status")
    if lab.get("generated_scope") != "development_history_only":
        errors.append("experiment_lab must declare development_history_only scope")
    if holdout_start and lab.get("holdout_start") != holdout_start.isoformat():
        errors.append("experiment_lab holdout cutoff does not match report policy")

    ids = lab.get("hypothesis_ids")
    if not isinstance(ids, list) or not ids or any(not isinstance(x, str) or not x for x in ids):
        errors.append("experiment_lab hypothesis_ids must be a non-empty string list")
        ids = []
    if len(set(ids)) != len(ids):
        errors.append("experiment_lab hypothesis_ids must be unique")
    hypothesis_configs = lab.get("hypothesis_configs")
    if not isinstance(hypothesis_configs, dict) or set(hypothesis_configs) != set(ids):
        errors.append("experiment_lab hypothesis_configs must exactly cover hypothesis_ids")
        hypothesis_configs = {}
    for hypothesis_id, cfg in hypothesis_configs.items():
        if not isinstance(cfg, dict):
            errors.append(f"experiment_lab hypothesis {hypothesis_id} config must be an object")
            continue
        if set(cfg) != {"fee_per_side", "slippage_per_side", "stop_pct", "target_pct", "max_bars"}:
            errors.append(f"experiment_lab hypothesis {hypothesis_id} config has unexpected or missing fields")
        for key in ("fee_per_side", "slippage_per_side"):
            value = cfg.get(key)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or not 0 <= value < 1:
                errors.append(f"experiment_lab hypothesis {hypothesis_id} has invalid {key}")
        for key in ("stop_pct", "target_pct"):
            value = cfg.get(key)
            if value is not None and (
                not isinstance(value, (int, float)) or isinstance(value, bool)
                or not math.isfinite(value) or not 0 < value < 1
            ):
                errors.append(f"experiment_lab hypothesis {hypothesis_id} has invalid {key}")
        max_bars = cfg.get("max_bars")
        if max_bars is not None and (
            not isinstance(max_bars, int) or isinstance(max_bars, bool) or max_bars < 1
        ):
            errors.append(f"experiment_lab hypothesis {hypothesis_id} has invalid max_bars")
    if lab.get("hypothesis_count") != len(ids):
        errors.append("experiment_lab hypothesis_count does not match hypothesis_ids")

    entry_ids = lab.get("entry_strategy_ids")
    if not isinstance(entry_ids, list) or not entry_ids or any(not isinstance(x, str) or not x for x in entry_ids):
        errors.append("experiment_lab entry_strategy_ids must be a non-empty string list")
        entry_ids = []
    if len(set(entry_ids)) != len(entry_ids):
        errors.append("experiment_lab entry_strategy_ids must be unique")
    if lab.get("entry_strategy_count") != len(entry_ids):
        errors.append("experiment_lab entry_strategy_count does not match entry_strategy_ids")

    ticker_count = lab.get("ticker_count")
    if not isinstance(ticker_count, int) or isinstance(ticker_count, bool) or ticker_count < 0:
        errors.append("experiment_lab ticker_count must be a non-negative integer")
        ticker_count = 0
    ticker_ids = lab.get("ticker_ids")
    if not isinstance(ticker_ids, list) or any(not isinstance(x, str) or not x for x in ticker_ids):
        errors.append("experiment_lab ticker_ids must be a string list")
        ticker_ids = []
    if len(set(ticker_ids)) != len(ticker_ids):
        errors.append("experiment_lab ticker_ids must be unique")
    if len(ticker_ids) != ticker_count:
        errors.append("experiment_lab ticker_count does not match ticker_ids")
    for ticker_id in ticker_ids:
        if ticker_id not in results:
            errors.append(f"experiment_lab references unknown ticker_id: {ticker_id}")
    expected_trials = ticker_count * len(ids)
    expected_family = expected_trials * len(entry_ids)
    if lab.get("trials_total") != expected_trials:
        errors.append("experiment_lab trials_total does not match ticker x hypothesis family")
    if lab.get("multiple_testing_family_size") != expected_family:
        errors.append("experiment_lab multiple_testing_family_size is inconsistent")

    trials = lab.get("trials")
    if not isinstance(trials, list):
        errors.append("experiment_lab trials must be a list")
        trials = []
    if len(trials) != lab.get("trials_total"):
        errors.append("experiment_lab trial list length does not match trials_total")

    seen: set[tuple[str, str]] = set()
    completed = 0
    replay_checked = 0
    for index, trial in enumerate(trials):
        if not isinstance(trial, dict):
            errors.append(f"experiment_lab trial {index} must be an object")
            continue
        ticker = trial.get("ticker")
        hypothesis_id = trial.get("hypothesis_id")
        if not isinstance(ticker, str) or ticker not in results or ticker not in ticker_ids:
            errors.append(f"experiment_lab trial {index} references an unknown or undeclared ticker")
        if hypothesis_id not in ids:
            errors.append(f"experiment_lab trial {index} references an unknown hypothesis")
        if isinstance(ticker, str) and isinstance(hypothesis_id, str):
            pair = (ticker, hypothesis_id)
            if pair in seen:
                errors.append(f"experiment_lab duplicate trial: {ticker}/{hypothesis_id}")
            seen.add(pair)
        bars = trial.get("development_bars")
        excluded = trial.get("excluded_holdout_bars")
        if not isinstance(bars, int) or isinstance(bars, bool) or bars < 0:
            errors.append(f"experiment_lab trial {index} has invalid development_bars")
        if excluded != 0:
            errors.append(f"experiment_lab trial {index} contains or reports holdout bars")
        fingerprint = trial.get("development_data_sha256")
        if bars and (not isinstance(fingerprint, str) or len(fingerprint) != 64
                     or any(ch not in "0123456789abcdef" for ch in fingerprint)):
            errors.append(f"experiment_lab trial {index} has invalid development data SHA256")
        config = trial.get("execution_config")
        if not isinstance(config, dict):
            errors.append(f"experiment_lab trial {index} is missing execution_config")
        else:
            expected_config = hypothesis_configs.get(hypothesis_id)
            if expected_config is not None and config != expected_config:
                errors.append(f"experiment_lab trial {index} execution_config differs from registered hypothesis config")
        trial_status = trial.get("status")
        if trial_status == "EXPERIMENTAL_SCREEN_COMPLETE":
            completed += 1
            if not isinstance(trial.get("walk_forward"), dict):
                errors.append(f"experiment_lab trial {index} lacks walk_forward results")
            if not isinstance(trial.get("adversarial_cost_check"), dict):
                errors.append(f"experiment_lab trial {index} lacks cost-stress results")
            replay = trial.get("execution_replay_audit")
            if not isinstance(replay, dict):
                errors.append(f"experiment_lab trial {index} lacks independent execution replay audit")
            else:
                replay_checked += 1
                if replay.get("status") != "REFERENCE_REPLAY_MATCH":
                    errors.append(f"experiment_lab trial {index} independent execution replay did not match")
                if replay.get("mismatch_count") != 0:
                    errors.append(f"experiment_lab trial {index} replay mismatch_count must be zero")
                main_count = replay.get("main_trade_count")
                reference_count = replay.get("reference_trade_count")
                if not isinstance(main_count, int) or isinstance(main_count, bool) or main_count < 0:
                    errors.append(f"experiment_lab trial {index} has invalid primary replay trade count")
                if not isinstance(reference_count, int) or isinstance(reference_count, bool) or reference_count != main_count:
                    errors.append(f"experiment_lab trial {index} primary/reference replay trade counts differ")
            signal_audit = trial.get("signal_generation_audit")
            if not isinstance(signal_audit, dict):
                errors.append(f"experiment_lab trial {index} lacks independent signal generation audit")
            else:
                if signal_audit.get("status") != "REFERENCE_SIGNAL_MATCH":
                    errors.append(f"experiment_lab trial {index} independent signal generation replay did not match")
                if signal_audit.get("mismatch_count") != 0:
                    errors.append(f"experiment_lab trial {index} signal generation mismatch_count must be zero")
                primary_count = signal_audit.get("primary_signal_count")
                reference_signal_count = signal_audit.get("reference_signal_count")
                if (not isinstance(primary_count, int) or isinstance(primary_count, bool) or primary_count < 0
                        or not isinstance(reference_signal_count, int) or isinstance(reference_signal_count, bool)
                        or reference_signal_count != primary_count):
                    errors.append(f"experiment_lab trial {index} primary/reference signal counts differ")
        elif trial_status != "INSUFFICIENT_OR_INVALID_DEVELOPMENT_DATA":
            errors.append(f"experiment_lab trial {index} has unknown status")

    expected_pairs = {(ticker_id, hypothesis_id) for ticker_id in ticker_ids for hypothesis_id in ids}
    missing_pairs = expected_pairs - seen
    unexpected_pairs = seen - expected_pairs
    if missing_pairs:
        errors.append(
            "experiment_lab is missing ticker/hypothesis trial combinations: "
            + ", ".join(f"{ticker}/{hypothesis}" for ticker, hypothesis in sorted(missing_pairs))
        )
    if unexpected_pairs:
        errors.append("experiment_lab contains trial combinations outside the declared Cartesian family")

    if lab.get("trials_completed") != completed:
        errors.append("experiment_lab trials_completed count is inconsistent")
    if lab.get("trials_incomplete") != len(trials) - completed:
        errors.append("experiment_lab trials_incomplete count is inconsistent")
    return len(trials), completed


def _audit_raw_session_provenance(
    ticker: str, result: dict[str, Any], warnings: list[str], errors: list[str],
) -> int:
    """Check internal consistency of raw calendar-candle reconciliation metadata."""
    audit = result.get("session_date_mapping")
    if audit is None:
        warnings.append(f"{ticker}: raw-to-TQBR session reconciliation evidence is missing")
        return 0
    if not isinstance(audit, dict):
        errors.append(f"{ticker}: session_date_mapping must be an object")
        return 0

    count_fields = (
        "positive_trade_history_dates",
        "history_dates_with_raw_fragments",
        "history_trade_dates_without_raw_fragments",
        "trading_days_reconciled",
        "trading_days_mismatched",
        "unassigned_raw_candles",
        "raw_candles",
        "raw_weekend_candles",
        "raw_weekend_candles_mapped",
        "raw_weekend_candles_unmapped",
    )
    counts = {}
    for field in count_fields:
        value = audit.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            errors.append(f"{ticker}: session_date_mapping {field} must be a non-negative integer")
        else:
            counts[field] = value

    if len(counts) != len(count_fields):
        return 0
    if counts["raw_weekend_candles_mapped"] + counts["raw_weekend_candles_unmapped"] != counts["raw_weekend_candles"]:
        errors.append(f"{ticker}: mapped and unmapped weekend candle counts do not sum to raw weekend candle count")
    if counts["raw_weekend_candles"] > counts["raw_candles"]:
        errors.append(f"{ticker}: raw weekend candle count exceeds total raw candles")

    if counts["unassigned_raw_candles"] > counts["raw_candles"]:
        errors.append(f"{ticker}: unassigned raw candle count exceeds total raw candles")
    if counts["trading_days_reconciled"] + counts["trading_days_mismatched"] != counts["history_dates_with_raw_fragments"]:
        errors.append(f"{ticker}: reconciled and mismatched trading-day counts do not cover raw/history matched dates")

    expected_missing = counts["positive_trade_history_dates"] - counts["history_dates_with_raw_fragments"]
    if expected_missing < 0 or counts["history_trade_dates_without_raw_fragments"] != expected_missing:
        errors.append(f"{ticker}: raw/history date coverage counts are inconsistent")

    ratio = audit.get("raw_history_date_coverage_ratio")
    positive = counts["positive_trade_history_dates"]
    if positive == 0:
        if ratio is not None:
            errors.append(f"{ticker}: raw/history coverage ratio must be null without positive history dates")
    elif (not isinstance(ratio, (int, float)) or isinstance(ratio, bool)
          or not math.isfinite(ratio) or not 0 <= ratio <= 1
          or abs(ratio - counts["history_dates_with_raw_fragments"] / positive) > 1e-12):
        errors.append(f"{ticker}: raw/history coverage ratio is inconsistent")

    expected_status = (
        "NO_POSITIVE_HISTORY_DATES" if positive == 0 else
        "NO_RAW_CANDLES" if counts["raw_candles"] == 0 else
        "COMPLETE_DATE_COVERAGE" if expected_missing == 0 else
        "PARTIAL_DATE_COVERAGE"
    )
    if audit.get("raw_history_coverage_status") != expected_status:
        errors.append(f"{ticker}: raw/history coverage status is inconsistent")

    expected_complete = (
        counts["raw_candles"] > 0
        and counts["trading_days_mismatched"] == 0
        and counts["unassigned_raw_candles"] == 0
        and expected_missing == 0
    )
    if audit.get("complete") is not expected_complete:
        errors.append(f"{ticker}: raw session reconciliation complete flag is inconsistent")
    expected_reconciliation_status = (
        "RECONCILED" if expected_complete else
        "NO_RAW_CANDLES" if counts["raw_candles"] == 0 else
        "RECONCILIATION_WITH_CAVEATS"
    )
    if audit.get("status") != expected_reconciliation_status:
        errors.append(f"{ticker}: raw session reconciliation status is inconsistent")
    if counts["trading_days_mismatched"] or counts["unassigned_raw_candles"] or expected_missing:
        warnings.append(
            f"{ticker}: raw calendar candles do not fully reconcile to TQBR history "
            f"(missing dates={max(expected_missing, 0)}, mismatched days={counts['trading_days_mismatched']}, "
            f"unassigned candles={counts['unassigned_raw_candles']})"
        )
    return 1


def validate_research_report(report: dict[str, Any]) -> dict[str, Any]:
    """Return an auditable PASS/FAIL/INCOMPLETE structural validation report."""
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(report, dict):
        return {
            "status": "INDEPENDENT_VALIDATION_FAIL",
            "checks": 0,
            "errors": ["research report must be a JSON object"],
            "warnings": [],
            "scope": "Structural and replay audit only; no profitability certification.",
        }

    policy = report.get("development_holdout_policy", {})
    if not isinstance(policy, dict):
        errors.append("development_holdout_policy must be an object")
        policy = {}
    if policy.get("holdout_is_strictly_prospective") is not True:
        errors.append("holdout must be explicitly marked strictly prospective")
    if policy.get("candidate_set_frozen") is not True:
        errors.append("candidate set must be explicitly marked frozen")
    holdout_start = _as_date(policy.get("holdout_start"), "holdout_start", errors)
    report_end = _as_date(report.get("date_till"), "date_till", errors)
    if holdout_start and report_end and report_end < holdout_start:
        warnings.append("report ends before holdout; no prospective observations to audit")

    results = report.get("results")
    if not isinstance(results, dict) or not results:
        errors.append("results must be a non-empty ticker mapping")
        results = {}
    checked_folds = 0
    checked_cost_candidates = 0
    checked_lab_trials = 0
    completed_lab_trials = 0
    checked_raw_provenance = 0
    analyzed = 0
    for ticker, result in results.items():
        if not isinstance(result, dict):
            errors.append(f"{ticker}: result must be an object")
            continue
        if result.get("status") != "ANALYZED":
            warnings.append(f"{ticker}: not analyzed ({result.get('status', 'missing status')})")
            continue
        analyzed += 1
        walk = result.get("walk_forward")
        if not isinstance(walk, dict):
            errors.append(f"{ticker}: missing walk_forward report")
        else:
            folds = walk.get("folds")
            if not isinstance(folds, list) or not folds:
                errors.append(f"{ticker}: walk_forward folds must be a non-empty list")
            else:
                previous_end = None
                for index, fold in enumerate(folds, start=1):
                    if not isinstance(fold, dict):
                        errors.append(f"{ticker}: fold {index} must be an object")
                        continue
                    start = _as_date(fold.get("start"), f"{ticker} fold {index} start", errors)
                    end = _as_date(fold.get("end_inclusive"), f"{ticker} fold {index} end_inclusive", errors)
                    if start and end and start > end:
                        errors.append(f"{ticker}: fold {index} starts after it ends")
                    if start and previous_end and start <= previous_end:
                        errors.append(f"{ticker}: walk-forward folds overlap or are unordered")
                    if end and holdout_start and end >= holdout_start:
                        errors.append(f"{ticker}: development fold {index} touches or crosses holdout")
                    if end:
                        previous_end = end
                    checked_folds += 1
        prospective = result.get("prospective_holdout")
        if not isinstance(prospective, dict):
            errors.append(f"{ticker}: missing prospective_holdout section")
        elif holdout_start and prospective.get("holdout_start") != holdout_start.isoformat():
            errors.append(f"{ticker}: prospective holdout cutoff mismatch")
        checked_cost_candidates += _audit_cost_claims(ticker, result, errors, warnings)
        checked_raw_provenance += _audit_raw_session_provenance(ticker, result, warnings, errors)

    checked_lab_trials, completed_lab_trials = _audit_experiment_lab(
        report.get("experiment_lab"), results, holdout_start, errors, warnings
    )
    if analyzed == 0:
        warnings.append("no ticker has a completed research analysis")
    checks = checked_folds + checked_cost_candidates + analyzed + checked_lab_trials + checked_raw_provenance
    if errors:
        status = "INDEPENDENT_VALIDATION_FAIL"
    elif analyzed == 0 or warnings:
        status = "INDEPENDENT_VALIDATION_INCOMPLETE"
    else:
        status = "INDEPENDENT_VALIDATION_PASS"
    return {
        "status": status,
        "checks": checks,
        "tickers_analyzed": analyzed,
        "walk_forward_folds_checked": checked_folds,
        "cost_candidates_checked": checked_cost_candidates,
        "raw_session_provenance_checks": checked_raw_provenance,
        "experiment_lab_trials_checked": checked_lab_trials,
        "experiment_lab_trials_completed": completed_lab_trials,
        "experiment_lab_replays_checked": sum(
            1 for trial in report.get("experiment_lab", {}).get("trials", [])
            if isinstance(trial, dict) and isinstance(trial.get("execution_replay_audit"), dict)
        ) if isinstance(report.get("experiment_lab"), dict) else 0,
        "experiment_lab_signal_replays_checked": sum(
            1 for trial in report.get("experiment_lab", {}).get("trials", [])
            if isinstance(trial, dict) and isinstance(trial.get("signal_generation_audit"), dict)
        ) if isinstance(report.get("experiment_lab"), dict) else 0,
        "errors": errors,
        "warnings": warnings,
        "scope": (
            "Independent structural audit of report chronology, cost-claim consistency, "
            "experiment-lab metadata/completeness, independent signal-formula and "
            "execution replay parity, and internal consistency of raw-to-history "
            "reconciliation metadata. It does not independently establish raw market-data "
            "provenance, verify exchange-wide calendars, establish statistical significance, "
            "prove profitability, "
            "or approve production use."
        ),
    }
