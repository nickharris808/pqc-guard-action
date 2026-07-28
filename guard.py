#!/usr/bin/env python3
"""pqc-guard: fail a build when a post-quantum migration config is unsafe.

Two checks, both cheap enough to run on every pull request:

  WINDOW    Given your largest credential, your reassembly memory budget and your
            worst-case concurrency, does a safe capacity cap exist at all? If the
            interval is empty, no cap is both feasible and safe -- that is a design
            defect you want to learn about in CI, not in the field.

  BENCHMARK Given a PQC-MFB submission, does your coverage meet a threshold, and did
            you regress a case that already passed? A regression is a hard fail
            regardless of coverage.

Exit codes:  0 = pass   1 = check failed   2 = usage/config error

Designed to be readable: this is the whole implementation, and it shells out to
nothing. It imports the two libraries and reports.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

# ---------------------------------------------------------------- output


def _gh(line: str) -> None:
    """Emit a GitHub Actions workflow command, or a plain line elsewhere."""
    print(line, flush=True)


def _summary(md: str) -> None:
    """Append to the job summary when running inside GitHub Actions."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(md + "\n")


def _output(key: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{key}={value}\n")


def _error(msg: str) -> None:
    _gh(f"::error::{msg}")


def _notice(msg: str) -> None:
    _gh(f"::notice::{msg}")


# ---------------------------------------------------------------- checks


def check_window(args) -> int:
    try:
        from pqc_sizes import (
            credential_bytes,
            max_concurrent_contexts,
            reassembly_window,
        )
    except ImportError:
        _error("pqc-sizes is not installed. `pip install pqc-sizes`.")
        return 2

    if args.kem and args.sig:
        largest = credential_bytes(args.kem, args.sig)
        what = f"{args.kem}+{args.sig} credential"
    elif args.largest_object:
        largest = args.largest_object
        what = f"{largest:,} B object"
    else:
        _error("give --largest-object, or both --kem and --sig")
        return 2

    win = reassembly_window(largest, args.budget, args.concurrency)
    safe_conc = max_concurrent_contexts(largest, args.budget)

    _output("window_empty", "true" if win.is_empty else "false")
    _output("ceiling", str(win.ceiling))
    _output("max_safe_concurrency", str(safe_conc))

    if win.is_empty:
        _error(
            f"Reassembly window is EMPTY for {what}: floor {largest:,} B > "
            f"ceiling {win.ceiling:,} B. No capacity cap is both feasible and safe."
        )
        _summary(
            "### PQC guard: window **EMPTY**\n\n"
            f"| | |\n|---|--:|\n"
            f"| object | {what} |\n"
            f"| floor | {largest:,} B |\n"
            f"| ceiling | {win.ceiling:,} B |\n"
            f"| budget | {args.budget:,} B |\n"
            f"| concurrency | {args.concurrency} |\n"
            f"| **max safe concurrency** | **{safe_conc}** |\n\n"
            f"{win.explain()}\n"
        )
        return 1

    _notice(
        f"Reassembly window OK for {what}: [{largest:,}, {win.ceiling:,}] B; "
        f"max safe concurrency {safe_conc}."
    )
    _summary(
        "### PQC guard: window OK\n\n"
        f"`{what}` — window **[{largest:,}, {win.ceiling:,}] B**, "
        f"recommended cap **{win.ceiling:,} B**, "
        f"max safe concurrency **{safe_conc}**.\n"
    )
    return 0


def check_benchmark(args) -> int:
    try:
        from pqc_mfb import load_cases, score_submission
    except ImportError:
        _error("pqc-mfb is not installed. `pip install pqc-mfb`.")
        return 2

    sub_path = Path(args.submission)
    if not sub_path.exists():
        _error(f"submission not found: {sub_path}")
        return 2
    try:
        raw = json.loads(sub_path.read_text())
    except json.JSONDecodeError as exc:
        _error(f"submission is not valid JSON: {exc}")
        return 2
    if not isinstance(raw, dict):
        _error("submission must be a JSON object of {case_id: bool}")
        return 2

    sc = score_submission({k: bool(v) for k, v in raw.items()}, load_cases())
    pct = 100 * sc.coverage

    _output("coverage_pct", f"{pct:.1f}")
    _output("regressions", str(sc.n_regressions))
    _output("zero_families", str(len(sc.zero_families)))

    rows = [
        "### PQC guard: benchmark", "",
        "| metric | value |", "|---|--:|",
        f"| coverage | {sc.n_closed}/{sc.n_failures} ({pct:.1f}%) |",
        f"| threshold | {args.min_coverage:.1f}% |",
        f"| regressions | {sc.n_regressions} |",
        f"| unanswered | {sc.n_unanswered} |",
        f"| families closed 0 of | {len(sc.zero_families)} |",
    ]
    if sc.zero_families:
        rows += ["", "Zero-coverage families:", ""]
        rows += [f"- `{f}`" for f in sc.zero_families[:20]]
        if len(sc.zero_families) > 20:
            rows.append(f"- _...and {len(sc.zero_families) - 20} more_")
    _summary("\n".join(rows) + "\n")

    failed = False
    if sc.n_regressions:
        _error(
            f"{sc.n_regressions} regression(s): a case the unrepaired baseline "
            f"already passed now fails. This is a hard failure regardless of coverage."
        )
        failed = True
    if pct < args.min_coverage:
        _error(f"coverage {pct:.1f}% is below the required {args.min_coverage:.1f}%")
        failed = True
    if args.max_zero_families is not None and len(sc.zero_families) > args.max_zero_families:
        _error(
            f"{len(sc.zero_families)} families have zero coverage, "
            f"limit is {args.max_zero_families}"
        )
        failed = True

    if not failed:
        _notice(f"benchmark OK: {pct:.1f}% coverage, 0 regressions.")
    return 1 if failed else 0


# ------------------------------------------------------------------ cli


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pqc-guard",
        description="Fail a build when a post-quantum migration config is unsafe.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    w = sub.add_parser("window", help="check the reassembly-capacity window")
    w.add_argument("--largest-object", type=int, default=0)
    w.add_argument("--kem")
    w.add_argument("--sig")
    w.add_argument("--budget", type=int, required=True)
    w.add_argument("--concurrency", type=int, required=True)
    w.set_defaults(func=check_window)

    b = sub.add_parser("benchmark", help="score a PQC-MFB submission against a threshold")
    b.add_argument("submission")
    b.add_argument("--min-coverage", type=float, default=0.0)
    b.add_argument("--max-zero-families", type=int, default=None)
    b.set_defaults(func=check_benchmark)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
