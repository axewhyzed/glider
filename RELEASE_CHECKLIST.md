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

- [x] Version is `3.1.0` in `pyproject.toml`.
- [x] Create annotated tag: `git tag -a v3.1.0 -m "Glider v3.1.0"`.
- [x] Push the release commit and tag: `git push origin main --follow-tags`.

### Release references

- Release implementation commit: `96b39dd7ec7d61b28a62adfd5c7a611eeb6c6ed8`.
- Annotated tag `v3.1.0` points to the release implementation commit above.
- Post-release verification documentation commit: `282d26c9046536e2ee65394a830de87372bc7a38`.
- `origin/main` points to the post-release documentation commit; the tag
  intentionally remains on the implementation commit.

## Post-release

- [x] Run `venv\Scripts\python.exe verify_release.py --version 3.1.0`.
- [x] Verify GitHub shows tag `v3.1.0` and the release commit.
- [x] Remote `v3.1.0` resolves to
  `96b39dd7ec7d61b28a62adfd5c7a611eeb6c6ed8`, and remote `main` resolves to
  `282d26c9046536e2ee65394a830de87372bc7a38`.
