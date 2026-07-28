"""Tests for the pqc-guard CI check.

These drive guard.py the way the Action does: as a subprocess, with the GitHub
Actions environment variables set, then assert on exit code, the outputs file
and the job-summary file.

The exit code is the whole product here -- an Action that reports a problem but
exits 0 does not fail anyone's build, so every failing path asserts rc == 1.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GUARD = ROOT / "guard.py"

PASS, FAIL, USAGE = 0, 1, 2


def run(args, tmp_path, env_extra=None):
    """Run guard.py with GH Actions env wired to temp files."""
    out = tmp_path / "gh_output"
    summary = tmp_path / "gh_summary"
    out.touch()
    summary.touch()
    env = {
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "GITHUB_OUTPUT": str(out),
        "GITHUB_STEP_SUMMARY": str(summary),
        "PYTHONPATH": ":".join(sys.path),
    }
    env.update(env_extra or {})
    proc = subprocess.run(
        [sys.executable, str(GUARD), *args],
        capture_output=True, text=True, env=env, timeout=60,
    )
    return proc, _parse_kv(out.read_text()), summary.read_text()


def _parse_kv(text: str) -> dict[str, str]:
    return dict(
        line.split("=", 1) for line in text.splitlines() if "=" in line
    )


# ------------------------------------------------------------- window

def test_safe_window_passes(tmp_path):
    proc, out, summary = run(
        ["window", "--largest-object", "12000", "--budget", "65536",
         "--concurrency", "4"], tmp_path)
    assert proc.returncode == PASS, proc.stdout + proc.stderr
    assert out["window_empty"] == "false"
    assert out["ceiling"] == "16384"
    assert out["max_safe_concurrency"] == "5"
    assert "window OK" in summary


def test_empty_window_FAILS_THE_BUILD(tmp_path):
    """The core promise. If this returns 0 the Action is useless."""
    proc, out, summary = run(
        ["window", "--largest-object", "12000", "--budget", "32768",
         "--concurrency", "3"], tmp_path)
    assert proc.returncode == FAIL
    assert out["window_empty"] == "true"
    assert "EMPTY" in summary
    assert "::error::" in proc.stdout


def test_window_from_algorithm_names(tmp_path):
    """kem+sig should resolve to the same 7,533 B credential."""
    proc, out, _ = run(
        ["window", "--kem", "ML-KEM-768", "--sig", "ML-DSA-65",
         "--budget", "65536", "--concurrency", "4"], tmp_path)
    assert proc.returncode == PASS
    assert out["ceiling"] == "16384"


def test_hash_based_credential_trips_the_guard(tmp_path):
    """SLH-DSA-128f pushes the credential past a 16 KiB ceiling."""
    proc, out, _ = run(
        ["window", "--kem", "ML-KEM-768", "--sig", "SLH-DSA-SHA2-128f",
         "--budget", "65536", "--concurrency", "4"], tmp_path)
    assert proc.returncode == FAIL
    assert out["window_empty"] == "true"


def test_window_without_object_or_algorithms_is_a_usage_error(tmp_path):
    proc, _, _ = run(
        ["window", "--budget", "65536", "--concurrency", "4"], tmp_path)
    assert proc.returncode == USAGE


def test_max_safe_concurrency_is_reported_and_actionable(tmp_path):
    """When the window is empty, the operator needs the number that would fix it."""
    proc, out, summary = run(
        ["window", "--largest-object", "12000", "--budget", "32768",
         "--concurrency", "8"], tmp_path)
    assert proc.returncode == FAIL
    assert out["max_safe_concurrency"] == "2"
    # and that number must actually be safe
    ok, _, _ = run(["window", "--largest-object", "12000", "--budget", "32768",
                    "--concurrency", "2"], tmp_path)
    assert ok.returncode == PASS


# ---------------------------------------------------------- benchmark

@pytest.fixture
def perfect_sub(tmp_path):
    from pqc_mfb import load_cases, perfect_submission
    p = tmp_path / "perfect.json"
    p.write_text(json.dumps(perfect_submission(load_cases())))
    return p


@pytest.fixture
def naive_sub(tmp_path):
    from pqc_mfb import load_cases, naive_baseline
    p = tmp_path / "naive.json"
    p.write_text(json.dumps(naive_baseline(load_cases())))
    return p


def test_perfect_submission_passes_a_high_threshold(tmp_path, perfect_sub):
    proc, out, summary = run(
        ["benchmark", str(perfect_sub), "--min-coverage", "99"], tmp_path)
    assert proc.returncode == PASS, proc.stdout
    assert out["coverage_pct"] == "100.0"
    assert out["regressions"] == "0"
    assert "benchmark" in summary


def test_naive_submission_fails_a_threshold(tmp_path, naive_sub):
    proc, out, _ = run(
        ["benchmark", str(naive_sub), "--min-coverage", "50"], tmp_path)
    assert proc.returncode == FAIL
    assert out["coverage_pct"] == "0.0"


def test_naive_passes_a_zero_threshold_but_reports_zero_families(tmp_path, naive_sub):
    proc, out, summary = run(
        ["benchmark", str(naive_sub), "--min-coverage", "0"], tmp_path)
    assert proc.returncode == PASS
    assert int(out["zero_families"]) >= 30
    assert "Zero-coverage families" in summary


def test_regression_fails_even_at_full_coverage(tmp_path, perfect_sub):
    """A submission can be 100% and still fail. Assert that explicitly."""
    from pqc_mfb import load_cases
    sub = json.loads(perfect_sub.read_text())
    ok_case = next(c for c in load_cases() if not c.is_failure)
    sub[ok_case.case_id] = False
    p = tmp_path / "regressed.json"
    p.write_text(json.dumps(sub))

    proc, out, _ = run(["benchmark", str(p), "--min-coverage", "0"], tmp_path)
    assert proc.returncode == FAIL
    assert out["coverage_pct"] == "100.0"     # full coverage ...
    assert out["regressions"] == "1"          # ... and still fails


def test_zero_family_limit_is_enforced(tmp_path, naive_sub):
    proc, _, _ = run(
        ["benchmark", str(naive_sub), "--min-coverage", "0",
         "--max-zero-families", "5"], tmp_path)
    assert proc.returncode == FAIL


def test_missing_submission_is_a_usage_error(tmp_path):
    proc, _, _ = run(["benchmark", "/nonexistent.json"], tmp_path)
    assert proc.returncode == USAGE


def test_malformed_submission_is_a_usage_error(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json")
    proc, _, _ = run(["benchmark", str(p)], tmp_path)
    assert proc.returncode == USAGE


def test_non_object_submission_is_a_usage_error(tmp_path):
    p = tmp_path / "arr.json"
    p.write_text("[1,2,3]")
    proc, _, _ = run(["benchmark", str(p)], tmp_path)
    assert proc.returncode == USAGE


# ------------------------------------------------------------ plumbing

def test_runs_without_github_env(tmp_path):
    """Outside Actions there is no GITHUB_OUTPUT; it must not crash."""
    proc = subprocess.run(
        [sys.executable, str(GUARD), "window", "--largest-object", "12000",
         "--budget", "65536", "--concurrency", "4"],
        capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": ":".join(sys.path)},
        timeout=60,
    )
    assert proc.returncode == PASS, proc.stderr


def test_action_yml_inputs_match_the_cli():
    """Every action input that maps to a flag must exist in guard.py."""
    action = (ROOT / "action.yml").read_text()
    guard = GUARD.read_text()
    for flag in ("--budget", "--concurrency", "--largest-object", "--kem",
                 "--sig", "--min-coverage", "--max-zero-families"):
        assert flag in guard, f"{flag} referenced by action.yml but not in guard.py"
        assert flag in action, f"{flag} in guard.py but not wired in action.yml"


def test_action_yml_is_valid_yaml_with_required_keys():
    yaml = pytest.importorskip("yaml")
    spec = yaml.safe_load((ROOT / "action.yml").read_text())
    assert spec["runs"]["using"] == "composite"
    assert "inputs" in spec and "outputs" in spec
    steps = spec["runs"]["steps"]
    install = next(s for s in steps if "pip install" in str(s.get("run", "")))
    run = install["run"]
    # Both checkers must be installed from somewhere that actually resolves.
    # This previously asserted "pqc-sizes==", which was satisfied by a pin to a
    # version that does not exist on any index -- the assertion passed while the
    # action was unusable. Assert an installable source instead.
    for pkg in ("pqc-sizes", "pqc-mfb"):
        assert pkg in run, f"{pkg} is not installed by the action"
    assert "git+https://github.com/nickharris808/pqc-sizes" in run
    assert "git+https://github.com/nickharris808/pqc-mfb" in run


def test_action_does_not_install_from_an_unpublished_pypi_pin():
    """Guard against reintroducing the pin that made the action unrunnable.

    `pip install pqc-sizes==0.1.0` is a 404: neither package is on PyPI. A bare
    `==` pin here is therefore a hard failure for every consumer of the action,
    and it is invisible until someone actually runs it.
    """
    yaml = pytest.importorskip("yaml")
    spec = yaml.safe_load((ROOT / "action.yml").read_text())
    # Inspect the commands that actually execute, not the file text: the comment
    # above the install step names the bad pin on purpose, to explain why it went.
    commands = " ".join(str(s.get("run", "")) for s in spec["runs"]["steps"])
    assert "pqc-sizes==" not in commands
    assert "pqc-mfb==" not in commands
