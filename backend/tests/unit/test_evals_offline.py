import pytest

from evals.cases import CASES
from evals.run_evals import run_offline


def test_golden_cases_are_well_formed() -> None:
    names = [case["name"] for case in CASES]
    assert len(names) == len(set(names)) and len(names) >= 4
    for case in CASES:
        assert {"name", "result", "policy", "expect", "offline_reply", "offline_expect"} <= set(case)


def test_validators_pass_every_offline_golden_case(capsys: pytest.CaptureFixture[str]) -> None:
    failures = run_offline()
    output = capsys.readouterr().out
    assert failures == 0, output
