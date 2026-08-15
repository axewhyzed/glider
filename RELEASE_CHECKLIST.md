# Release Checklist

Use this checklist before tagging a release.

## Pre-release

- [ ] `venv\Scripts\python.exe -m pytest tests -q` — full suite green (no browser/network markers excluded unexpectedly)
- [ ] `venv\Scripts\python.exe -m pytest tests -m browser -q` — browser tests pass on a machine with `playwright install chromium`
- [ ] `python -m compileall engine main.py` — no compile errors
- [ ] `glider validate configs/hacker_news.json` — CLI smoke passes
- [ ] `pip wheel . --no-deps -w dist` — package builds
- [ ] Check `git diff` for: no secrets/tokens, no debug artifacts, no unbounded resource changes
- [ ] `docs/KNOWN_ISSUES.md` is up to date; no resolved items still listed as open
- [ ] CHANGELOG.md has an entry for this release

## Release

- [ ] Bump `version` in `pyproject.toml`
- [ ] Tag: `git tag vX.Y.Z`
- [ ] Push: `git push origin main --tags` (only when explicitly requested)

## Post-release

- [ ] Update the production-readiness checklist with the release note and verification commands
