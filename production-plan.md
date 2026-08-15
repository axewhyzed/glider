# Glider v3.1.0 Production Readiness Plan

Status: complete. Release commit `96b39dd7ec7d61b28a62adfd5c7a611eeb6c6ed8`
and annotated tag `v3.1.0` are pushed to GitHub.

## Review and implementation checklist

- [x] Terra security review: SSRF/DNS, redirects, credential scoping, browser
  schemes/service workers, OAuth, artifact redaction, and path safety.
- [x] Terra core review: proxy/context races, request caps, HTTP status health,
  cancellation, checkpoint durability, nested crawling, pagination, and sitemap
  bounds.
- [x] Luna transport implementation: origin-scoped cookies, fail-closed DNS
  handling, allowed-domain enforcement, browser guards, OAuth protections, and
  redaction.
- [x] Luna state implementation: cancellation-safe run states, durable flush
  fences, bounded caches/in-flight work, kind-aware checkpoint handling, nested
  failure completion, and pagination validation.
- [x] Add regression tests for every verified security/correctness fix.
- [x] Add `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, and the threat
  model.
- [x] Update README, configuration, operations, upgrade, known-issues,
  changelog, and release checklist documentation.
- [x] Set package version to `3.1.0`.

## Verification record

- `venv\Scripts\python.exe -m pytest tests -q`: 309 passed, 1 deselected.
- `npx --yes pyright --pythonpath .\venv\Scripts\python.exe engine main.py verify_release.py`:
  0 errors, 0 warnings, 0 informations.
- `venv\Scripts\python.exe -m compileall -q engine main.py verify_release.py`:
  passed.
- `venv\Scripts\python.exe -m pytest tests -m browser -q`: 1 skipped locally
  because Chromium is not installed; CI installs Chromium in the browser job.
- `venv\Scripts\glider.exe validate configs\hacker_news.json --format json`:
  valid, no issues.
- `venv\Scripts\python.exe -m pip wheel . --no-deps -w dist`: built
  `glider-3.1.0-py3-none-any.whl`.
- `git diff --check`: passed.

## Release handoff

- [x] Commit the reviewed changes as the v3.1.0 release.
- [x] Create annotated tag `v3.1.0`.
- [x] Push `main` and the tag with `git push origin main --follow-tags`.
- [x] `verify_release.py --version 3.1.0` passed: local and remote `main` and
  `v3.1.0` resolve to `96b39dd7ec7d61b28a62adfd5c7a611eeb6c6ed8`.

## v3.2.0 usage phase

The completed usage-focused phase is documented in
[`docs/V3.2_PLAN.md`](docs/V3.2_PLAN.md). It adds deterministic local
validation, benchmarks, examples, and developer workflow improvements without
changing the core configuration contract.

## v3.2.1 patch

- [x] Fix the real Chromium `data:text/html` smoke path.
- [x] Remove import-time Windows event-loop policy mutation from the CLI.
- [x] Verify browser suite, full suite, Pyright, compile, examples, and package
  build before tagging the patch release.

## v3.3.0 usage validation follow-up

- [x] Tighten browser `data:text/html` validation to require the exact media
  type while preserving valid MIME parameters.
- [x] Add separate deterministic local benchmark scenarios for list,
  pagination, JSON, and nested-link workflows.
- [x] Add request and nested-child accounting plus regression coverage for the
  benchmark matrix.
- [x] Improve the first-run examples workflow and benchmark documentation.
- [x] Complete release verification, tag `v3.3.0`, and push the release.

Release implementation commit: `971761f732cd1af8359e9f6a573ae21db13609b7`.
Post-release checklist documentation is kept in a separate commit so the tag
continues to identify the reviewed implementation.

## v3.3.1 benchmark cleanup

- [x] Remove release-number coupling from benchmark configuration names.
- [x] Use `workload_size` as the documented benchmark input while preserving
  `pages` compatibility aliases and output.
- [x] Add regression coverage for canonical and legacy benchmark APIs.
- [x] Complete release verification, tag `v3.3.1`, and push the patch.

Release implementation commit: `f24cd1e0b2c1ce0cf396dfd36092f252466aca47`.
Post-release checklist documentation is kept in a separate commit so the tag
continues to identify the reviewed implementation.
