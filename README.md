# pqc-guard-action

[![license](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![tests](https://img.shields.io/badge/tests-24%20passing-brightgreen.svg)](tests/)
[![action](https://img.shields.io/badge/GitHub-Action-2088FF.svg)](action.yml)

**Catch an unsafe post-quantum migration in CI, not in the field.**

Three lines in a workflow. Fails the build when no safe reassembly cap exists, when
benchmark coverage drops below your threshold, or when you regress a case that used to
pass.

---

## Why this exists

Post-quantum credentials are 7,533 bytes and up. That forces fragmentation, which forces
your receiver to hold attacker-influenced state before it can authenticate it, which
forces a capacity cap — and that cap has a floor *and* a ceiling. It is entirely possible
to pick a concurrency limit for which **no safe cap exists at all**.

That is a design defect, it is invisible in code review, and it is arithmetic. So it
belongs in CI.

## Quickstart

```yaml
- uses: nickharris808/pqc-guard-action@v1
  with:
    kem: ML-KEM-768
    sig: ML-DSA-65
    budget: 65536
    concurrency: 4
```

That's it. The job fails if the window is empty.

## Example output

When it fails, you get an annotation on the PR:

```
::error::Reassembly window is EMPTY for ML-KEM-768+SLH-DSA-SHA2-128f credential:
floor 19,392 B > ceiling 16,384 B. No capacity cap is both feasible and safe.
```

and a job summary that tells you how to fix it:

> ### PQC guard: window **EMPTY**
>
> | | |
> |---|--:|
> | object | ML-KEM-768+SLH-DSA-SHA2-128f credential |
> | floor | 19,392 B |
> | ceiling | 16,384 B |
> | **max safe concurrency** | **3** |
>
> Raise the budget to at least 77,568 B, reduce concurrency to at most 3, or choose a
> smaller credential.

**`max safe concurrency` is the actionable number** — the guard doesn't just say no, it
tells you the value that would pass.

## Both checks

```yaml
- uses: nickharris808/pqc-guard-action@v1
  with:
    check: both
    kem: ML-KEM-768
    sig: ML-DSA-65
    budget: 65536
    concurrency: 4
    submission: results/pqc-mfb.json
    min-coverage: "80"
    max-zero-families: "5"
```

## Inputs

| Input | Default | Meaning |
|---|---|---|
| `check` | `window` | `window`, `benchmark`, or `both` |
| `kem` / `sig` | — | algorithm names; resolves the credential size for you |
| `largest-object` | `0` | explicit byte count, instead of `kem`+`sig` |
| `budget` | `65536` | global reassembly memory budget, bytes |
| `concurrency` | `4` | worst-case concurrent reassembly contexts |
| `submission` | — | PQC-MFB submission JSON (`{case_id: bool}`) |
| `min-coverage` | `0` | minimum coverage percentage to pass |
| `max-zero-families` | unlimited | cap on families with zero coverage |
| `python-version` | `3.12` | Python used to run the checks |

## Outputs

`window-empty` · `ceiling` · `max-safe-concurrency` · `coverage-pct` · `regressions`

```yaml
- id: guard
  uses: nickharris808/pqc-guard-action@v1
  continue-on-error: true
  with: { kem: ML-KEM-768, sig: ML-DSA-65, budget: 65536, concurrency: 4 }
- run: echo "cap should be ${{ steps.guard.outputs.ceiling }} bytes"
```

## What counts as a failure

| Condition | Result |
|---|---|
| Reassembly window empty | **fail** |
| Coverage below `min-coverage` | **fail** |
| **Any regression** | **fail — regardless of coverage** |
| Too many zero-coverage families | **fail** |

A submission can score **100% coverage and still fail**, if it broke a case the
unrepaired baseline already handled. There is a test asserting exactly that.

## Run it locally

The Action is a thin wrapper over one readable script — no compiled bundle, no
`node_modules`:

```bash
pip install pqc-sizes pqc-mfb
python guard.py window --kem ML-KEM-768 --sig ML-DSA-65 --budget 65536 --concurrency 4
python guard.py benchmark results.json --min-coverage 80
```

Exit codes: **0** pass · **1** check failed · **2** usage error.

## Tests

```bash
pip install pytest pyyaml pqc-sizes pqc-mfb && pytest    # 24 passed
```

Tests drive `guard.py` as a subprocess with the GitHub Actions environment wired to
temp files, and assert on exit code, `GITHUB_OUTPUT` and the job summary — because an
Action that reports a problem but exits `0` fails nobody's build.

## Scope

Arithmetic and scoring. It does not inspect your implementation, read your traffic, or
verify anything cryptographically. A passing build means your *configuration* admits a
safe cap and your submission met your threshold — not that your code enforces it.

## Related

[`pqc-sizes`](https://github.com/nickharris808/pqc-sizes) · [`pqc-mfb`](https://github.com/nickharris808/pqc-mfb) ·
[`pqc-dos-embedded`](https://github.com/nickharris808/pqc-dos-embedded) · [`farkas-check`](https://github.com/nickharris808/farkas-check)

Enforcing the cap, and closing the other 38 failure families, is what the closed core
Relevant subject matter is covered by a filed provisional patent application.
For commercial use, open a [GitHub Discussion](https://github.com/nickharris808) or an issue.

---

## The PQC migration toolkit

Nine free tools for teams moving authenticated key exchange to post-quantum. They **find and measure**; they do not repair.

| Tool | What it does | Where |
|---|---|---|
| [pqc-sizes](https://github.com/nickharris808/pqc-sizes) | Sizes, fragment counts, and the two-sided reassembly window | PyPI |
| [pqc-sizes-js](https://github.com/nickharris808/pqc-sizes-js) | The same arithmetic for Node and the browser | npm |
| **pqc-guard-action** ← you are here | Fail the build when the window is empty | GitHub Action |
| [pqc-dos-embedded](https://github.com/nickharris808/pqc-dos-embedded) | 169 lines of C: the failure on a real 64 KB device | source |
| [farkas-check](https://github.com/nickharris808/farkas-check) | Re-verify the bound on-device, no SMT solver | source |
| [pqc-migration-mcp](https://github.com/nickharris808/pqc-migration-mcp) | Six MCP tools for AI agents | PyPI |
| [pqc-mfb](https://github.com/nickharris808/pqc-mfb) | 322 cases · 39 failure families · scorer | PyPI |
| [pqc-mfb (data)](https://huggingface.co/datasets/nickh007/pqc-mfb) | The benchmark as a dataset | HF |
| [pqc-formal-corpus](https://huggingface.co/datasets/nickh007/pqc-formal-corpus) | 122 named formal results, 6 provers | HF |
| [pqc-explorer](https://huggingface.co/spaces/nickh007/pqc-explorer) | Try it in your browser, no install | HF Space |

**Start here:** [`pqc-sizes`](https://github.com/nickharris808/pqc-sizes) tells you in five seconds whether your credential fragments and whether a safe cap exists. [`pqc-explorer`](https://huggingface.co/spaces/nickh007/pqc-explorer) does the same in a browser.

### The closed core

Closing the 39 failure families — downgrade binding, retransmission-safe installation, fragmentation transcripts, roaming forward secrecy, multi-link key separation, admission control, group-key binding — is a separate proprietary codebase. Relevant subject matter is covered by a filed provisional patent application.

That split is measured, not asserted: under a replicate noise control only **4 of 32** repair mechanisms are externally distinguishable, so publishing these detectors does not disclose the repairs.

For commercial licensing, open a [GitHub Discussion](https://github.com/nickharris808/pqc-sizes/discussions) or an issue on any of these repos.

## License

Apache-2.0. See [LICENSE](LICENSE) and [CONTRIBUTING.md](CONTRIBUTING.md).
