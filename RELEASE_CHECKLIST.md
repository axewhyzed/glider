# Glider v3.0.0 Release Checklist

## Pre-release

- [x] Implement all v3 assessment fixes and requested capabilities.
- [x] `venv\Scripts\python.exe -m pytest tests -q` - 268 passed, 1 deselected.
- [x] `venv\Scripts\python.exe -m pytest tests\test_browser.py -m browser -q` - 1 passed, 8 deselected.
- [x] `venv\Scripts\python.exe -m compileall -q engine main.py` - passed.
- [x] `npx --yes pyright --pythonpath .\venv\Scripts\python.exe engine main.py` - 0 errors, 0 warnings, 0 informations.
- [x] `venv\Scripts\glider.exe validate configs\hacker_news.json --format json` - valid, no issues.
- [x] `venv\Scripts\python.exe -m pip wheel . --no-deps --no-build-isolation -w dist-v3` - built `glider-3.0.0-py3-none-any.whl`.
- [x] `git diff --check` - passed.
- [x] Review source, docs, logs, and generated artifacts for secrets, accidental data, nondeterminism, and unbounded resources.
- [x] Update CHANGELOG, README, configuration reference, known issues, and operations plan.

## Release

- [x] Version is `3.0.0` in `pyproject.toml`.
- [ ] Create annotated tag: `git tag -a v3.0.0 -m "Glider v3.0.0"`.
- [ ] Push release commit and tag: `git push origin main --follow-tags`.

## Post-release

- [x] Verify GitHub shows tag `v3.0.0` and the release commit.
- [x] Record the final commit/tag and remote verification in the living production plan.
