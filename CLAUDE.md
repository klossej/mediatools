# CLAUDE.md

All project guidance lives in AGENTS.md so that every coding agent follows the same rules:

@AGENTS.md

## Claude Code notes

- Each tool has its own `.venv` inside its folder. Run tests with that
  interpreter, e.g. `cd aaf_audio_extractor && .venv/bin/python -m pytest -q`.
- The GUI tests run headless (`QT_QPA_PLATFORM=offscreen` is set in
  `tests/conftest.py`).
- Put scratch files and large exports in the session's temp directory, never in
  the repository.
