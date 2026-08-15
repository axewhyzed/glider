# Contributing to Glider

## Development setup

Glider supports Python 3.10 and newer. Create a virtual environment, install
the editable package with development dependencies, and install Chromium when
working on browser paths:

```bash
python -m venv venv
venv/bin/pip install -e ".[dev,browser]"
playwright install chromium
```

On Windows, use `venv\Scripts\python.exe` and
`venv\Scripts\pip.exe` instead.

## Before opening a pull request

Run the core suite, browser gate, compiler, type checker, configuration smoke
test, and packaging checks:

```bash
python -m pytest tests -q
python -m pytest tests -m browser -q
python -m compileall engine main.py verify_release.py
npx --yes pyright --pythonpath ./venv/bin/python engine main.py verify_release.py
glider validate configs/hacker_news.json --format json
python -m pip wheel . --no-deps -w dist
git diff --check
```

Tests must not make live network requests unless explicitly marked and
requested. Add a regression test for every correctness or security fix.

## Change guidelines

- Preserve URL policy, origin-scoped credentials, cancellation safety, and
  resumable checkpoint semantics.
- Keep browser and HTTP behavior aligned where the configuration promises the
  same behavior.
- Do not log or commit secrets, cookie files, proxy credentials, generated
  run artifacts, or local environment files.
- Keep changes focused and update the relevant configuration, operations,
  security, and changelog documentation.
- Use conventional commit subjects such as `fix:`, `feat:`, `docs:`, and
  `release:`.

## Pull requests and releases

Describe the user-visible behavior, security implications, compatibility
impact, tests run, and any follow-up risk. Releases require an annotated tag,
a clean-tree verification, the complete release checklist, and confirmation
that reachable commit identities are authorized project contributors.
