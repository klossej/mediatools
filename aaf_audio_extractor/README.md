# AAF Audio Extractor

A small Windows utility for audio post-production. It opens AAF files exported
from Avid Media Composer, takes premixed audio (a stereo track such as A31, or
two mono tracks such as A1 + A2), and writes it as one **stereo 48 kHz / 24-bit
Broadcast WAV** file placed at the sequence's **record start timecode**. Many
AAFs can be processed as one batch, e.g. a whole series of episodes.

Version 0.1.0. It does one job: no editing, mixing or effect rendering.

---

## Quick start (operators)

1. Double-click **`AAF Audio Extractor.exe`** (in `dist\AAF Audio Extractor\`).
2. Drag the AAF files, or the folder that holds them, into the window.

**Stereo mix that may sit on different tracks:** tick **Auto-detect stereo mix
track in every file**, choose the output folder and click **Export All**. That's
it. Otherwise, set the tracks by hand:

3. Click a file. In **Tracks**, choose the **Left channel** and **Right channel**.
   For a stereo track, pick `A31 ch1 (stereo L)` as Left; Right is set to
   `A31 ch2 (stereo R)` automatically.
4. Click **Apply to All Files**. Every file is checked, and the Status column shows
   `Ready` or explains what needs attention.
5. Choose the **Output folder** and click **Export All**.
6. Read the completion summary. A CSV report is saved next to the WAV files.

`501.aaf` becomes `501_MIX.wav`. You can change the suffix. See
[docs/OPERATOR_GUIDE.md](docs/OPERATOR_GUIDE.md) for the full workflow:
per-file overrides, manual timecode, retrying failed files, and linked media.

## Building the Windows application (developers)

Double-click **`install.bat`** in the repository root. It:

1. Finds 64-bit Python 3.12 or 3.13. If neither is found, it offers to download
   Python 3.12.10 from python.org. It checks the installer's SHA-256 checksum and
   its Python Software Foundation Authenticode signature, then installs it for the
   current user only (no administrator rights).
2. Creates the local virtual environment `.venv`, or reuses it if it is healthy.
3. Installs the pinned dependencies from `requirements-build.txt` (wheels only).
4. Checks that the toolchain imports correctly.
5. Runs the automated tests, then builds the executable with PyInstaller.

The finished application is in **`dist\AAF Audio Extractor\`**. Copy that whole
folder to any 64-bit Windows 10/11 PC; Python is not needed there. The script
can be run again at any time and never touches the application's saved settings.
Output goes to `logs\install.log`.

| Script | Purpose |
|---|---|
| `install.bat` | Single entry point: set up the environment, test and build |
| `build.bat` | Test and rebuild only (`/skiptests`, `/nopause` options) |
| `run.bat` | Run from source in the `.venv` (handy while developing) |

To develop on another OS: `python3.12 -m venv .venv`, then
`.venv/bin/pip install -r requirements-build.txt`, then `.venv/bin/pytest`, then
`.venv/bin/python launcher.py`.

## What it does to the audio

* The record timeline of the chosen sequence is rebuilt for each selected track
  from its SourceClips and Fillers. Gaps become digital silence. If a track starts
  late or ends early, it is padded with silence. The output always spans the full
  sequence duration.
* Source offsets come from the AAF clip chain (sequence → master clip → file
  source mob). Only the samples inside each clip's boundaries are used; handles
  are never included.
* Samples are copied bit-exactly. 24-bit sources pass through unchanged. 16-bit
  sources are padded to 24 bits (a shift of 8 bits, which loses nothing). There is
  no gain, normalisation, dither, fades or resampling.
* Processing is streamed in 4-second blocks, so memory use stays flat for
  programmes of any length.
* The left and right channels always have the same sample count.

### Timecode

* The record start comes from the sequence's own timecode track, never from
  source clip timecode. If the sequence has several timecode tracks that
  disagree (Avid can add, for example, a 24 fps TC2), TC1 is used and the others
  are listed in the warnings. If there is no TC1, the file needs attention.
* Positions are converted with exact rational arithmetic (`fractions.Fraction`),
  so nothing accumulates floating-point error.
* `TimeReference = round(frames_since_midnight × 48000 / real_frame_rate)`. For
  example, 10:00:00:00 at 25 fps gives 1,728,000,000. 10:00:00;00 at 29.97 DF is
  frame 1,078,920, which gives 1,727,998,272.
* 23.976, 24, 25, 29.97 DF/NDF, 30, 50, 59.94 DF/NDF and 60 are implemented.
  The automated tests check 23.976, 24, 25, 29.97 DF/NDF and 30.
* If the timecode is missing or ambiguous, the file is marked *Needs attention*
  and you can enter it manually. The app never falls back to 00:00:00:00.
* The BWF TimeReference does not record the frame rate or drop-frame mode. Those
  are written to the `bext` Description and to the CSV report.

### Output file

RIFF/WAVE containing `bext` (EBU Tech 3285 v1), `fmt ` (PCM, 2 ch, 48 kHz, 24-bit)
and `data`. The `bext` chunk holds:

* Description: AAF name, sequence, tracks, and timecode with rate.
* Originator: "AAF Audio Extractor".
* OriginationDate and OriginationTime: when the file was written, not the
  programme timecode.
* TimeReference.
* CodingHistory.

Every file is first written as `name.wav.partial`. It is then read back by an
independent parser that checks the RIFF sizes, chunk set, format, sample count
and TimeReference. Only after that check is it renamed to the final name.

## Architecture

```
src/aaf_extractor/
  aaf/        inspector.py  AAF → sequences, tracks, segments, record timecode (pyaaf2)
              model.py      thread-safe dataclasses describing what was found
  media/      resolver.py   embedded essence / locator / search-folder resolution (MXF by UMID)
              containers.py WAVE, AIFF/AIFC, MXF (KLV) header parsing
              reader.py     chunked PCM reading → 24-bit int32 samples
  audio/      render.py     sample-accurate placement plan + streaming interleaved renderer
  bwf/        writer.py     streaming BWF writer      reader.py  independent verifier
  batch/      models.py     queue/job state           preflight.py matching + all checks
              runner.py     sequential export, cancellation, CSV report
              naming.py     Windows-safe output names
  gui/        main_window.py, workers.py (QThread), style.py (palette, Inter font)
  timecode.py exact timecode / sample arithmetic
  appinfo.py  resource paths (source + PyInstaller), logging, diagnostic report
```

Dependencies (pinned): PySide6-Essentials 6.12.0, numpy 2.5.4, pyaaf2 1.7.1;
PyInstaller 6.22.3 and pytest 9.2.0 to build and test. The app works completely
offline and needs no Avid, Pro Tools or proprietary SDK.

## Supported AAF structures (v0.1)

Supported:

* One or several consecutive SourceClips per track, Filler gaps, and non-zero
  source offsets.
* Avid stereo (multichannel) tracks, stored as an `Audio Channel Combiner` over a
  master clip with one mono source per channel. Each channel can be mapped to
  Left or Right on its own (`A31 ch1`, `A31 ch2`).
* Auto-detection of the mix (optional). Per file, the app picks the usable
  stereo track whose audio spans at least 90% of the sequence. If several
  qualify, the one whose clip or track name contains "MIX" wins. If it is still
  ambiguous, or nothing qualifies, the file is marked *Needs attention* with the
  candidates listed. The app never guesses.
* Avid's 4 KiB padding of embedded essence streams: nothing past the declared
  media length is ever read.
* Tracks with a frame edit rate or an audio-rate edit rate.
* Embedded PCM essence (PCMDescriptor, WAVEDescriptor, AIFCDescriptor).
* Linked WAV/AIFF files, and linked MXF OP-Atom PCM files that are matched by
  their package UMID.
* A Mono Audio Gain operation at exactly unity. It is treated as pass-through and
  noted in the warnings.
* A Mono Audio Pan operation. It is ignored with a warning, because pan does not
  change the samples of an extracted mono track.

Refused with a clear message. The affected file is marked Unsupported and the
rest of the batch continues:

* Non-zero Transitions (crossfades), effects (EQ, dynamics, AudioSuite), gain other
  than unity, and volume or pan automation.
* Nested sequences, multi-choice essence groups, and multi-descriptor media.
* AES3-wrapped MXF, compressed codecs, float or 32-bit PCM, and sample rates other
  than 48 kHz (no resampling in v0.1).

## Known limitations

* **Verified on one real Media Composer export** (Love Island S5, LI_510.aaf:
  embedded audio, stereo mix on A31, 25 fps). The exported WAV is bit-identical to
  the AAF's embedded essence across all clips, and the length and TimeReference
  are correct (see [docs/TESTING.md](docs/TESTING.md)). Placement in Pro Tools,
  and a comparison against an Avid- or Pro Tools-rendered reference, still need to
  be checked by an operator.
* MXF OP-Atom reading is tested on synthetic KLV files only. Matching by UMID
  relies on pyaaf2's MXF header parser.
* Output files are limited to 4 GiB (about 4 h 8 min of 48 kHz / 24-bit stereo).
  RF64 is not written.
* Only 48 kHz sources are accepted. 16-bit and 24-bit integer PCM are supported.
* Files are exported one after another; there is no parallel rendering.
* There is no headless or command-line batch mode yet.
* The Windows build has only been checked as far as this repository can: the
  dependency pins are verified to have Windows wheels, and the same spec builds
  and launches on Linux. Run `install.bat` on Windows to produce the real `.exe`.

## Logs and diagnostics

* Log file: `%LOCALAPPDATA%\AAF Audio Extractor\logs\aaf_audio_extractor.log`
  (rotating). It records each file, sequence, timecode, edit rate, tracks, source
  media IDs, source in-points, timeline offsets, sample counts and TimeReference.
* **Save Diagnostic Report…** writes one text file with the full inspection and
  export plan for every queued AAF, plus the recent log. Send this file when
  reporting an incorrect export.
* An example CSV report is in [docs/example_batch_report.csv](docs/example_batch_report.csv).

## Licences

The Inter font (`resources/fonts`) is © The Inter Project Authors and is used under
the SIL Open Font License 1.1 (see `resources/fonts/Inter-OFL.txt`). pyaaf2 is MIT
licensed. PySide6 is LGPLv3; the one-folder build keeps the Qt libraries as
separate, replaceable DLLs.
