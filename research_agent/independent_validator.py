"""Independent structural audit of MOEX EDGE research reports.

This validator deliberately does not trust candidate pass labels. It checks
holdout separation, walk-forward chronology, and consistency of doubled-cost
claims. It does not rerun the simulator or certify profitability.
"""
from __future__ import annotations

from datetime import date
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
    if not isinstance(lab, dict):
        errors.append("experiment_lab must be an object")
        return 0, 0
    status = lab.get("status")
    if status == "EXPERIMENT_LAB_ERROR":
        warnings.append("experiment lab did not complete: " + str(lab.get("error", "unknown error")))
        return 0, 0
    if status not in (None, "EXPERIMENT_LAB_COMPLETE"):
        errors.append("experiment_lab has an unrecognized status")
    if lab.get("generated_scope") != "development_history_only":
        errors.append("experiment_lab must declare development_history_only scope")
    if holdout_start:
        lab_cutoff = lab.get("holdout_start")
        if lab_cutoff != holdout_start.isoformat():
            errors.append("experiment_lab holdout cutoff does not match report policy")

    ids = lab.get("hypothesis_ids")
    if not isinstance(ids, list) or not ids or any(not isinstance(x, str) or not x for x in ids):
        errors.append("experiment_lab hypothesis_ids must be a non-empty string list")
        ids = []
    if len(set(ids)) != len(ids):
        errors.append("experiment_lab hypothesis_ids must be unique")
    hypothesis_count = lab.get("hypothesis_count")
    if hypothesis_count != len(ids):
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
    for index, trial in enumerate(trials):
        if not isinstance(trial, dict):
            errors.append(f"experiment_lab trial {index} must be an object")
            continue
        ticker = trial.get("ticker")
        hypothesis_id = trial.get("hypothesis_id")
        if not isinstance(ticker, str) or ticker not in results:
            errors.append(f"experiment_lab trial {index} references an unknown ticker")
        if hypothesis_id not in ids:
            errors.append(f"experiment_lab trial {index} references an unknown hypothesis")
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
            for key in ("fee_per_side", "slippage_per_side"):
                value = config.get(key)
                if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
                    errors.append(f"experiment_lab trial {index} has invalid {key}")
        trial_status = trial.get("status")
        if trial_status == "EXPERIMENTAL_SCREEN_COMPLETE":
            completed += 1
            if not isinstance(trial.get("walk_forward"), dict):
                errors.append(f"experiment_lab trial {index} lacks walk_forward results")
            if not isinstance(trial.get("adversarial_cost_check"), dict):
                errors.append(f"experiment_lab trial {index} lacks cost-stress results")
        elif trial_status != "INSUFFICIENT_OR_INVALID_DEVELOPMENT_DATA":
            errors.append(f"experiment_lab trial {index} has unknown status")

    if lab.get("trials_completed") != completed:
        errors.append("experiment_lab trials_completed count is inconsistent")
    if lab.get("trials_incomplete") != len(trials) - completed:
        errors.append("experiment_lab trials_incomplete count is inconsistent")
    return len(trials), completed

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
            "scope": "Structural audit only; no profitability certification.",
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
                    end = _as_date(
                        fold.get("end_inclusive"),
                        f"{ticker} fold {index} end_inclusive", errors
                    )
                    if start and end and start > end:
                        errors.append(f"{ticker}: fold {index} starts after it ends")
                    if start and previous_end and start <= previous_end:
                        errors.append(f"{ticker}: walk-forward folds overlap or are unordered")
                    if end and holdout_start and end >= holdout_start:
                        errors.append(
                            f"{ticker}: development fold {index} touches or crosses holdout"
                        )
                    if end:
                        previous_end = end
                    checked_folds += 1

        prospective = result.get("prospective_holdout")
        if not isinstance(prospective, dict):
            errors.append(f"{ticker}: missing prospective_holdout section")
        elif holdout_start:
            reported_cutoff = prospective.get("holdout_start")
            if reported_cutoff != holdout_start.isoformat():
                errors.append(f"{ticker}: prospective holdout cutoff mismatch")

        checked_cost_candidates += _audit_cost_claims(
            ticker, result, errors, warnings
        )

    checked_lab_trials, completed_lab_trials = _audit_experiment_lab(
        report.get("experiment_lab"), results, holdout_start, errors, warnings
    )
    if analyzed == 0:
        warnings.append("no ticker has a completed research analysis")
    checks = checked_folds + checked_cost_candidates + analyzed + checked_lab_trials
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
        "experiment_lab_trials_checked": checked_lab_trials,
        "experiment_lab_trials_completed": completed_lab_trials,
        "errors": errors,
        "warnings": warnings,
        "scope": (
            "Independent structural audit of report chronology, cost-claim consistency, "
            "and experiment-lab metadata/completeness. It does not rerun the "
            "simulator, establish statistical significance, prove profitability, "
            "or approve production use."
        ),
    }
