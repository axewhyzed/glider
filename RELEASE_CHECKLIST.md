# Glider v3.1.0 Release Checklist

## Pre-release

- [x] Complete Terra security/core review and Luna implementation review.
- [x] `venv\Scripts\python.exe -m pytest tests -q` - 309 passed, 1 deselected.
- [x] `venv\Scripts\python.exe -m compileall -q engine main.py verify_release.py` - passed.
- [x] `git diff --check` passed.
- [x] Browser-marked smoke command ran locally; Chromium was unavailable, so
  the test was skipped. CI installs Chromium in the browser job.
- [x] Pyright clean run using the repository environment.
- [x] Config validation and package build.
- [x] Documentation and release-state consistency review.

## Release

- [ ] Version is `3.1.0` in `pyproject.toml`.
- [ ] Create annotated tag: `git tag -a v3.1.0 -m "Glider v3.1.0"`.
- [ ] Push release commit and tag: `git push origin main --follow-tags`.

## Post-release

- [ ] Run `venv\Scripts\python.exe verify_release.py --version 3.1.0`.
- [ ] Verify GitHub shows tag `v3.1.0` and the release commit.
- [ ] Record the final commit/tag and remote verification here.
