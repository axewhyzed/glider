# Glider v3.2.1 Release Checklist

## Pre-release

- [x] Fix bounded HTML data-URL browser navigation and Windows event-loop
  compatibility.
- [x] `venv\Scripts\python.exe -m pytest tests -m browser -q` - 1 passed,
  313 deselected.
- [x] `venv\Scripts\python.exe -m pytest tests -q` - 313 passed, 1 deselected.
- [x] `venv\Scripts\python.exe -m compileall -q engine benchmarks main.py verify_release.py` - passed.
- [x] Pyright clean for production code, release verifier, and benchmarks.
- [x] All `examples/*.json` files validate with the CLI.
- [x] `git diff --check` passed.
- [x] Documentation and release-state consistency reviewed.

## Release

- [x] Version is `3.2.1` in `pyproject.toml`.
- [x] Create annotated tag: `git tag -a v3.2.1 -m "Glider v3.2.1"`.
- [x] Push release commit and tag: `git push origin main --follow-tags`.

### Release references

- Release implementation commit: `8c51d68420f42042cb58f6a93d2fd40223e1efb0`.
- Annotated tag `v3.2.1` points to the release implementation commit above.
- Post-release checklist commit: `5ca4a7d`.
- `origin/main` contains that documentation commit; the tag intentionally
  remains on the implementation commit.

## Post-release

- [x] Run `venv\Scripts\python.exe verify_release.py --version 3.2.1`.
- [x] Verify GitHub shows tag `v3.2.1` and the release commit.
- [x] Remote `v3.2.1` resolves to
  `8c51d68420f42042cb58f6a93d2fd40223e1efb0`.
