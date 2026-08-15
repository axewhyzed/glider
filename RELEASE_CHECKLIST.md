# Glider v3.3.1 Release Checklist

## Pre-release

- [x] Remove release-number coupling from benchmark configuration names.
- [x] Make `workload_size` the documented benchmark concept while preserving
  `pages` compatibility aliases.
- [x] Add regression coverage for canonical and legacy benchmark APIs.
- [x] `venv\Scripts\python.exe -m pytest tests -q` - 315 passed, 1 deselected.
- [x] `venv\Scripts\python.exe -m pytest tests -m browser -q` - 1 passed,
  315 deselected.
- [x] `venv\Scripts\python.exe -m compileall -q engine benchmarks main.py verify_release.py` passed.
- [x] Pyright is clean for production code, release verifier, and benchmarks.
- [x] All `examples/*.json` files validate with the CLI.
- [x] `git diff --check` passed.
- [x] Documentation and release-state consistency reviewed.

## Release

- [x] Version is `3.3.1` in `pyproject.toml`.
- [ ] Commit the reviewed implementation as the v3.3.1 release commit.
- [ ] Create annotated tag: `git tag -a v3.3.1 -m "Glider v3.3.1"`.
- [ ] Push release commit and tag: `git push origin main --follow-tags`.

### Release references

- Release implementation commit: to be recorded after commit.
- Annotated tag `v3.3.1` must point to the release implementation commit.
- Any post-release documentation commit must be recorded separately; the tag
  intentionally remains on the implementation commit.

## Post-release

- [ ] Run `venv\Scripts\python.exe verify_release.py --version 3.3.1`.
- [ ] Verify GitHub shows tag `v3.3.1` and the release commit.
- [ ] Record the final remote commit and tag hashes here.
