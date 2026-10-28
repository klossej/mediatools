# mediatools

Small, dependable utilities for broadcast audio post-production. Each tool
lives in its own folder with its own dependencies, tests, build scripts and
documentation.

| Tool | What it does | Platform |
|---|---|---|
| [aaf_audio_extractor](aaf_audio_extractor/README.md) | Extracts premixed audio tracks from Avid Media Composer AAF files into stereo 48 kHz / 24-bit Broadcast WAV files placed at the sequence record timecode, in batches (e.g. a whole series). | Windows desktop app (PySide6), builds a standalone `.exe` |

## Getting started

Clone the repository, then follow the README of the tool you need. For example,
for the AAF Audio Extractor on Windows:

```
git clone https://github.com/klossej/mediatools.git
cd mediatools\aaf_audio_extractor
install.bat
```

## Repository layout

```
mediatools/
├── README.md            this file
├── AGENTS.md            conventions for contributors and coding agents
├── CLAUDE.md            Claude Code entry point (imports AGENTS.md)
└── aaf_audio_extractor/ AAF → stereo BWF extractor (source, tests, docs, build scripts)
```

New tools go in their own top-level folder, following the conventions in
[AGENTS.md](AGENTS.md).
