# AGENTS.md

Guidance for anyone, human or coding agent, working in this repository.

## Repository layout

`mediatools` is a collection of independent tools for broadcast audio
post-production. Each tool is a self-contained top-level folder:

- its own `README.md`, `pyproject.toml`, pinned `requirements*.txt`, `tests/`,
  `docs/` and build scripts;
- its own private Python in `<tool>/.python` (Windows: unpacked from the official
  python.org NuGet package by `install.bat`, never installed into Windows) and
  its own virtual environment in `<tool>/.venv`. Both are git-ignored and never
  shared between tools. Deleting a tool's folder must leave nothing behind
  except its documented per-user data folder (no registry, no PATH changes);
- no imports across tool folders. Shared code would get its own folder and
  explicit packaging first.

Current tools:

| Folder | Summary |
|---|---|
| `aaf_audio_extractor/` | Avid AAF → stereo 48 kHz / 24-bit BWF with record timecode, batch GUI (PySide6, pyaaf2, numpy) |

## Working on a tool

Run commands from inside the tool's folder:

```
cd aaf_audio_extractor
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-build.txt   # Linux/macOS
.venv/bin/python -m pytest -q          # all tests must pass before committing
.venv/bin/python launcher.py           # run the app from source
```

On Windows, `install.bat` does the setup, runs the tests and builds
`dist\AAF Audio Extractor\`. `run.bat` starts the app from source.

## Conventions

- **Python 3.12** (3.13 also accepted). Dependencies are pinned to exact versions
  that have Windows x64 wheels. Check this before bumping:
  `pip download --only-binary=:all: --platform win_amd64 --python-version 3.12 <pkg>==<ver>`.
- Match the surrounding code: dataclasses for plain data, `fractions.Fraction`
  for any timing arithmetic (never floats), small focused modules, and comments
  that explain *why*.
- Do not use the Windows registry: application settings go to an INI file in the
  per-user data folder (`%LOCALAPPDATA%\<App Name>`), and caches stay in the tool
  folder.
- Windows `.bat` files use CRLF line endings (enforced by `.gitattributes`).
  Resolve paths from the script location (`%~dp0`) and quote every path.
- Every behaviour change comes with a test. Prefer synthetic fixtures generated
  in code (see `aaf_audio_extractor/tests/aafgen.py`) over binary test files.
- Keep docs in step with behaviour: the tool README, `docs/OPERATOR_GUIDE.md`
  and `docs/TESTING.md`.

## Rules specific to broadcast audio

- **Never silently approximate.** If an AAF contains something that would change
  the sound (effects, gain other than unity, fades, automation, resampling), the
  file is reported as unsupported or needing attention. It is never exported as
  if it were faithful.
- **Record timecode is release-blocking.** Never fall back to 00:00:00:00, and
  never use source clip timecode as record timecode.
- Output must be verified after writing (independent header read-back) before it
  gets its final name. A failed or cancelled export must leave no partial file.
- Ambiguity goes to the operator, for example several candidate tracks, several
  sequences or conflicting timecode. Do not guess.

## Data and media

- **Never commit AAF, MXF, WAV or other programme media.** The files are large
  (GitHub rejects files over 100 MB) and are broadcaster material.
- Real sample files for validation are kept on the development server outside
  the repository, for example `/home/<user>/LI_510.aaf`. Record the results of
  real-file validation in the tool's `docs/TESTING.md`, not the files themselves.

## Git

- Commit messages: a summary line, then what changed and why.
- Do not commit `.venv/`, `build/`, `dist/`, logs or `*.partial` files (see each
  tool's `.gitignore`).
