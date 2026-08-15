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

- [x] Version is `3.2.0` in `pyproject.toml`.
- [x] Create annotated tag: `git tag -a v3.2.0 -m "Glider v3.2.0"`.
- [x] Push release commit and tag: `git push origin main --follow-tags`.

### Release references

- Release implementation commit: `17ffd39dfc8698738a7c27e3cf80b46369e8faad`.
- Annotated tag `v3.2.0` points to the release implementation commit above.
- The final documentation follow-up commit is recorded after this checklist
  is updated; `origin/main` will point to that descendant commit.

## Post-release

- [x] Run `venv\Scripts\python.exe verify_release.py --version 3.2.0`.
- [x] Verify GitHub shows tag `v3.2.0` and the release commit.
- [ ] Record the final documentation commit and remote verification after the
  checklist follow-up is pushed.
