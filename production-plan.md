# Glider v3.1.0 Production Readiness Plan

Status: complete pending commit, annotated tag, and remote push.

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

- [ ] Commit the reviewed changes as the v3.1.0 release.
- [ ] Create annotated tag `v3.1.0`.
- [ ] Push `main` and the tag with `git push origin main --follow-tags`.
- [ ] Run `verify_release.py --version 3.1.0` after the push and record the
  remote commit/tag verification.
