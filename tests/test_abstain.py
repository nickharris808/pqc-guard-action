"""The guard must never certify a submission that did not answer.

Oracle: NO INPUT MAY PRODUCE A CONFIDENT-LOOKING ANSWER THAT IS WRONG.

The hole this closes: the benchmark gate checked regressions and a coverage
threshold. An empty submission has zero regressions, and 0% coverage clears a 0%
threshold -- so `pqc-guard benchmark empty.json --min-coverage 0` passed, and a
green check appeared on a repository that had demonstrated nothing.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GUARD = ROOT / "guard.py"


def run(*args: str, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    import os
    env = dict(os.environ)
    env.setdefault("PYTHONPATH", "")
    if env_extra:
        env.update(env_extra)
    return subprocess.run([sys.executable, str(GUARD), *args],
                          capture_output=True, text=True, timeout=120, env=env)


@pytest.fixture()
def cases():
    pytest.importorskip("pqc_mfb")
    from pqc_mfb import load_cases
    return load_cases()


def write(tmp_path, obj) -> str:
    p = tmp_path / "sub.json"
    p.write_text(json.dumps(obj))
    return str(p)


def test_empty_submission_fails_even_at_a_zero_threshold(tmp_path):
    r = run("benchmark", write(tmp_path, {}), "--min-coverage", "0")
    assert r.returncode == 1, "an empty submission satisfied the guard"
    assert "unanswered" in (r.stdout + r.stderr)
    assert "Silence is not credit" in (r.stdout + r.stderr)


def test_partial_submission_fails(tmp_path, cases):
    failures = [c for c in cases if c.is_failure]
    sub = {c.case_id: True for c in failures[:-1]}
    r = run("benchmark", write(tmp_path, sub), "--min-coverage", "0")
    assert r.returncode == 1


def test_complete_submission_passes(tmp_path, cases):
    sub = {c.case_id: True for c in cases}
    r = run("benchmark", write(tmp_path, sub), "--min-coverage", "90")
    assert r.returncode == 0, r.stdout + r.stderr


def test_unknown_ids_are_flagged(tmp_path, cases):
    sub = {c.case_id: True for c in cases}
    sub["stale::case_from_an_old_version"] = True
    r = run("benchmark", write(tmp_path, sub), "--min-coverage", "0")
    assert r.returncode == 1
    assert "match no case" in (r.stdout + r.stderr)


def test_regression_still_fails_regardless_of_coverage(tmp_path, cases):
    sub = {c.case_id: True for c in cases}
    control = next(c for c in cases if not c.is_failure)
    sub[control.case_id] = False
    r = run("benchmark", write(tmp_path, sub), "--min-coverage", "0")
    assert r.returncode == 1
    assert "regression" in (r.stdout + r.stderr)


def test_verdict_is_exposed_as_an_action_output(tmp_path, cases):
    """Downstream steps should be able to branch on the verdict."""
    out_file = tmp_path / "gh_output"
    out_file.touch()
    sub = {c.case_id: True for c in cases}
    r = run("benchmark", write(tmp_path, sub), "--min-coverage", "0",
            env_extra={"GITHUB_OUTPUT": str(out_file)})
    assert r.returncode == 0
    written = out_file.read_text()
    assert "verdict=PASS" in written
    assert "unanswered=0" in written
