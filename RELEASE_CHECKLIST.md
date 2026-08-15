# Glider v3.0.2 Release Checklist

## Pre-release

- [x] Implement safe browser proxy circuit rotation and documentation follow-ups.
- [x] `venv\Scripts\python.exe -m pytest tests -q` - 278 passed, 1 deselected.
- [x] `venv\Scripts\python.exe -m pytest tests\test_browser.py -m browser -q` - browser smoke gate passed.
- [x] `venv\Scripts\python.exe -m compileall -q engine main.py verify_release.py` - passed.
- [x] `npx --yes pyright --pythonpath .\venv\Scripts\python.exe engine main.py verify_release.py` - 0 errors, 0 warnings, 0 informations.
- [x] `venv\Scripts\glider.exe validate configs\hacker_news.json --format json` - valid, no issues.
- [x] Build `glider-3.0.2-py3-none-any.whl` successfully.
- [x] `git diff --check` passed.
- [x] Documentation and release-state consistency reviewed.

## Release

- [x] Version is `3.0.2` in `pyproject.toml`.
- [x] Create annotated tag: `git tag -a v3.0.2 -m "Glider v3.0.2"`.
- [x] Push release commit and tag: `git push origin main --follow-tags`.

## Post-release

- [x] Run `venv\Scripts\python.exe verify_release.py --version 3.0.2` after push.
- [x] Verify GitHub shows tag `v3.0.2` and the release commit.
- [x] Record the final commit/tag and remote verification in the living production plan.
