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

    if analyzed == 0:
        warnings.append("no ticker has a completed research analysis")
    checks = checked_folds + checked_cost_candidates + analyzed
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
        "errors": errors,
        "warnings": warnings,
        "scope": (
            "Independent structural audit of report chronology and cost-claim "
            "consistency. It does not rerun the simulator, establish statistical "
            "significance, prove profitability, or approve production use."
        ),
    }
