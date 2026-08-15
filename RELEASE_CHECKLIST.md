# Release Checklist

Use this checklist before tagging a release.

## Pre-release

- [x] `venv\Scripts\python.exe -m pytest tests -q` — core suite green; browser smoke is intentionally marker-gated
- [ ] `venv\Scripts\python.exe -m pytest tests -m browser -q` — browser tests pass on a machine with `playwright install chromium`
- [x] `python -m compileall engine main.py` — no compile errors
- [x] `glider validate configs/hacker_news.json` — CLI smoke passes
- [x] `pip wheel . --no-deps -w dist` — package builds
- [x] Check `git diff` for: no secrets/tokens, no debug artifacts, no unbounded resource changes
- [x] `docs/KNOWN_ISSUES.md` is up to date; no resolved items still listed as open
- [x] CHANGELOG.md has an entry for this release

## Release

- [ ] Bump `version` in `pyproject.toml`
- [ ] Tag: `git tag vX.Y.Z`
- [ ] Push: `git push origin main --tags` (only when explicitly requested)

## Post-release

- [x] Update the production-readiness checklist with the release note and verification commands
