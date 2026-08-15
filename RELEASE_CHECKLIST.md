# Glider v3.3.0 Release Checklist

## Pre-release

- [x] Tighten browser `data:text/html` media-type validation.
- [x] Add deterministic list, pagination, JSON, and nested-link benchmark
  scenarios with regression coverage.
- [x] Improve first-run examples and benchmark documentation.
- [x] `venv\Scripts\python.exe -m pytest tests -q` - 314 passed, 1 deselected.
- [x] `venv\Scripts\python.exe -m pytest tests -m browser -q` - 1 passed,
  314 deselected.
- [x] `venv\Scripts\python.exe -m compileall -q engine benchmarks main.py verify_release.py` passed.
- [x] Pyright is clean for production code, release verifier, and benchmarks.
- [x] All `examples/*.json` files validate with the CLI.
- [x] `git diff --check` passed.
- [x] Documentation and release-state consistency reviewed.

## Release

- [x] Version is `3.3.0` in `pyproject.toml`.
- [ ] Commit the reviewed implementation as the v3.3.0 release commit.
- [ ] Create annotated tag: `git tag -a v3.3.0 -m "Glider v3.3.0"`.
- [ ] Push release commit and tag: `git push origin main --follow-tags`.

### Release references

- Release implementation commit: to be recorded after commit.
- Annotated tag `v3.3.0` must point to the release implementation commit.
- Any post-release documentation commit must be recorded separately; the tag
  intentionally remains on the implementation commit.

## Post-release

- [ ] Run `venv\Scripts\python.exe verify_release.py --version 3.3.0`.
- [ ] Verify GitHub shows tag `v3.3.0` and the release commit.
- [ ] Record the final remote commit and tag hashes here.
