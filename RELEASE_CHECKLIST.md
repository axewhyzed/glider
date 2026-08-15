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

- [ ] Version is `3.2.1` in `pyproject.toml`.
- [ ] Create annotated tag: `git tag -a v3.2.1 -m "Glider v3.2.1"`.
- [ ] Push release commit and tag: `git push origin main --follow-tags`.

## Post-release

- [ ] Run `venv\Scripts\python.exe verify_release.py --version 3.2.1`.
- [ ] Verify GitHub shows tag `v3.2.1` and the release commit.
- [ ] Record the release commit, tag target, documentation commit, and remote
  verification here.
