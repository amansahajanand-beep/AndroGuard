"""Measure the AI privacy-policy check against the golden cases.

    python -m evals.run_evals            # offline: validators against canned replies (no key, no cost)
    python -m evals.run_evals --live     # real model: needs ANTHROPIC_API_KEY and AI_REPORT_ENABLED=true

Live mode reports, over all cases:
  recall      expected issues the model found (matched by cited fact ids and issue type)
  precision   issues the model returned that match an expected one
  clean-case false alarms   issues returned on cases that should have none
  dropped     statements removed by the citation / quote checks (a measure of hallucination)
Run it before and after changing a prompt or model and compare the numbers.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from app.core.config import settings
from app.services import ai_provider
from app.services.audit_evidence import build_facts, fact_ids
from app.services.policy_analysis import analyze_policy, validate

from evals.cases import CASES


def _matches(issue: dict[str, Any], expected: dict[str, Any]) -> bool:
    return bool(set(issue["evidence_ids"]) & set(expected["evidence_any"])) and issue["type"] in expected["types"]


def run_offline() -> int:
    failures = 0
    for case in CASES:
        facts = build_facts(case["result"])
        result = validate(case["offline_reply"], case["policy"], fact_ids(facts))
        want = case["offline_expect"]
        problems = []
        if len(result["issues"]) != want["issues"]:
            problems.append(f"issues {len(result['issues'])} != {want['issues']}")
        if len(result["claims"]) != want["claims"]:
            problems.append(f"claims {len(result['claims'])} != {want['claims']}")
        if result["unsupported_dropped"] < want["min_dropped"]:
            problems.append(f"dropped {result['unsupported_dropped']} < {want['min_dropped']}")
        for expected in case["expect"]["issues"]:
            if not any(_matches(i, expected) for i in result["issues"]):
                problems.append(f"missing expected issue on {expected['evidence_any']}")
        print(f"{'PASS' if not problems else 'FAIL'}  {case['name']}  {'; '.join(problems)}")
        failures += bool(problems)
    return failures


def run_live() -> int:
    if not ai_provider.configured():
        print("Live mode needs AI_REPORT_ENABLED=true and an API key for AI_REPORT_PROVIDER.", file=sys.stderr)
        return 2
    expected_total = found = returned = matched = false_alarms = dropped = 0
    rows = []
    for case in CASES:
        analysis = analyze_policy(case["policy"], build_facts(case["result"]), source="eval")
        if analysis is None:
            print(f"ERROR {case['name']}: the model call failed")
            return 1
        issues = analysis["issues"]
        expected = case["expect"]["issues"]
        expected_total += len(expected)
        hit = sum(any(_matches(i, e) for i in issues) for e in expected)
        found += hit
        returned += len(issues)
        good = sum(any(_matches(i, e) for e in expected) for i in issues)
        matched += good
        if not expected:
            false_alarms += len(issues)
        dropped += analysis["unsupported_dropped"]
        rows.append({"case": case["name"], "expected": len(expected), "found": hit, "returned": len(issues), "dropped": analysis["unsupported_dropped"]})
        print(f"{case['name']:<40} expected={len(expected)} found={hit} returned={len(issues)} dropped={analysis['unsupported_dropped']}")
    recall = found / expected_total if expected_total else 1.0
    precision = matched / returned if returned else 1.0
    print(f"\nmodel={ai_provider.model()}  recall={recall:.0%}  precision={precision:.0%}  false alarms on clean cases={false_alarms}  dropped={dropped}")
    print(json.dumps({"model": ai_provider.model(), "recall": recall, "precision": precision, "false_alarms": false_alarms, "dropped": dropped, "cases": rows}))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="call the real model")
    args = parser.parse_args()
    raise SystemExit(run_live() if args.live else run_offline())
