# Glider v3.2.0 Release Checklist

## Pre-release

- [x] Complete local usage review and focused code review.
- [x] `venv\Scripts\python.exe -m pytest tests -q` - 313 passed, 1 deselected.
- [x] `venv\Scripts\python.exe -m compileall -q engine benchmarks main.py verify_release.py` - passed.
- [x] `git diff --check` passed.
- [x] Pyright clean for production code, release verifier, and benchmarks.
- [x] All `examples/*.json` files validate with the CLI.
- [x] Local benchmark completed: 100 pages, concurrency 10, three repeats,
  zero failures.
- [x] Documentation and release-state consistency reviewed.

## Release

- [ ] Version is `3.2.0` in `pyproject.toml`.
- [ ] Create annotated tag: `git tag -a v3.2.0 -m "Glider v3.2.0"`.
- [ ] Push release commit and tag: `git push origin main --follow-tags`.

## Post-release

- [ ] Run `venv\Scripts\python.exe verify_release.py --version 3.2.0`.
- [ ] Verify GitHub shows tag `v3.2.0` and the release commit.
- [ ] Record the release commit, tag target, post-release documentation commit,
  and remote verification here.
