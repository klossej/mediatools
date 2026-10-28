# Testing

Run all tests:

```
.venv\Scripts\python -m pytest -q          (Windows)
.venv/bin/python -m pytest -q              (macOS / Linux)
```

`install.bat` and `build.bat` run the full suite and refuse to build if any test
fails. It takes about one minute.

## Coverage of the required scenarios

The fixtures are synthetic AAFs written with pyaaf2 by `tests/aafgen.py`. Their
structure follows Media Composer: a top-level CompositionMob with a TC1 timecode
track, sound tracks with PhysicalTrackNumber, then MasterMob, then a file
SourceMob holding PCM essence. Every audio check compares sample-for-sample
against the exact samples placed in the fixture.

| # | Requirement | Tests |
|---|---|---|
| 1 | One embedded mono PCM clip per track | `test_extraction::test_single_embedded_mono_clip_per_track` |
| 2 | Different source in-points | `test_extraction::test_different_source_in_points` |
| 3 | Different record start positions | `test_extraction::test_different_record_start_positions_and_gaps` |
| 4 | Gaps become silence | same as 3, plus `test_29_97_drop_frame_sequence` |
| 5 | Different track durations | `test_programme_length_follows_longest_track_and_picture` |
| 6 | Multiple consecutive clips | `test_multiple_consecutive_clips_are_contiguous`, `test_29_97_drop_frame_sequence` |
| 7 | Non-zero record timecode | `test_non_zero_record_timecode_written_to_time_reference`, `test_batch::test_thirty_two_episode_batch` |
| 8 | BWF TimeReference readback | `test_bwf::*`, `test_timecode::test_time_reference` |
| 9 | Stereo interleaving | `test_stereo_interleaving_left_right_assignment` |
| 10 | Missing track | `test_preflight::test_missing_track`, `test_ambiguous_track_name` |
| 11 | Missing media | `test_preflight::test_missing_external_media`, `test_media::test_missing_media_error_is_specific`, `test_ambiguous_search_folder_match` |
| 12 | Unsupported components | `test_preflight::test_unsupported_effect`, `test_non_unity_gain_is_unsupported`, `test_transition_is_unsupported`, `test_unsupported_sample_rate` |
| 13 | Batch with successes and failures | `test_batch::test_batch_with_success_and_failures`, `test_failure_during_render_does_not_stop_batch` |
| 14 | Batch cancellation | `test_batch::test_cancellation_mid_render` |
| 15 | Output filename collisions | `test_preflight::test_output_filename_collisions`, `test_case_insensitive_collision`, `test_batch::test_collision_does_not_block_other_files` |
| — | Avid stereo track (Channel Combiner), channel mapping, padding | `test_stereo::*` |
| — | Auto-detect stereo mix (coverage, MIX tie-break, ambiguity, mix on different tracks per episode) | `test_detect::*`, `test_gui::test_auto_detect_checkbox_exports_mix_from_any_track` |
| 16 | Long-file streaming / RAM | `test_streaming::test_ninety_minute_render_memory_is_bounded` (90 min, peak < 48 MB), `test_ten_minute_embedded_export_end_to_end` |

Also covered:

* 29.97 drop-frame and audio-rate edit rates.
* Embedded WAVE and AIFC essence, and 16-bit to 24-bit promotion.
* Linked WAV media, including media found in a search folder.
* MXF frame- and clip-wrapped PCM, with AES3 rejected.
* Matching tracks by name, per-file overrides and manual timecode overrides.
* AAFs with several sequences.
* Overwrite, skip and rename policies, retrying without re-rendering, and the CSV
  report contents.
* An offscreen GUI end-to-end export.

## Validation against a real Media Composer export

**LI_510.aaf** (Love Island S5, 4.6 GB, embedded audio, 25 fps, 32 audio tracks),
checked on 2026-10-28:

* Structure found: the stereo mix is on A31 as three `Audio Channel Combiner`
  clips (main mix, a 1,935-frame insert, main mix again). Each channel is a
  separate mono 48 kHz / 24-bit embedded PCM source. A32 is empty. TC1 is
  00:00:00:00 at 25 fps; TC2 is an extra 24 fps timecode track.
* Avid pads every embedded essence stream to 4 KiB. The padding is excluded.
* The export of A31 ch1 → L and ch2 → R took about 15 s for 71:33.68
  (206,096,640 samples per channel). An independent script compared the WAV data
  byte-for-byte with the six embedded essence streams read directly through
  pyaaf2: **0 differing samples**. Both lengths equal the sequence duration, and
  TimeReference = 0 (00:00:00:00).
* Other tracks are correctly refused: clip gain of −10 dB and others, pan
  automation, crossfades, AudioSuite and track effects, and a nested sequence.
  The master fader carries a Maxim limiter. It is not part of A31 and is not
  applied, so the export is the mix file exactly as it was delivered to the
  editor.

Auto-detect on this file picks A31 (stereo, audio over 100% of the sequence).
The other stereo tracks (A20, A22, A27: music and SFX) are excluded because they
carry gain changes.

`tests/test_stereo.py` reproduces this structure synthetically.

## What synthetic tests cannot prove

The following need **real Avid Media Composer exports** and have not been
verified:

* That Media Composer's AAF uses the structures assumed here: which sequence is
  marked TopLevel, where TC1 sits, the track edit rates, and the slot names and
  numbers.
* Avid's embedded-audio flavour: whether it writes PCM, WAVE or AIFC descriptors,
  and the exact stream layout.
* How Avid writes clip gain, track volume and pan: the operation definitions and
  the units of their parameter values. The app only accepts gain that is exactly
  1.0 and refuses anything it cannot interpret. If real exports store unity gain
  differently (for example as 0 dB), those tracks will show as Unsupported until
  this is adapted.
* Avid OP-Atom MXF from the Avid MediaFiles folder: matching by UMID and the
  essence key layout.
* Placement on a Pro Tools timeline.

## Critical acceptance procedure (do this before production use)

1. In Media Composer, prepare a sequence with:
   * two known mono mix tracks (for example A1 and A2);
   * an explicit record start (for example 10:00:00:00) at the project rate;
   * ideally, one track that starts later than the sequence, a gap, and a clip
     with a non-zero source in-point.
2. Export an AAF (Embed media, or linked to the MXF media if you will use linked
   media in production).
3. From Avid or Pro Tools, export the same two tracks as reference WAVs covering
   exactly the sequence duration from its first frame. Use 48 kHz / 24-bit, no
   dither, no processing.
4. Process the AAF with AAF Audio Extractor (A1 → Left, A2 → Right).
5. Compare sample-for-sample:

   ```
   .venv\Scripts\python tools\compare_reference.py "out\EP_MIX.wav" --left REF_A1.wav --right REF_A2.wav
   ```

   It prints the first non-silent sample of each file, the first mismatch and the
   TimeReference. Exit code 0 means the files are identical. If the reference was
   exported with pre-roll, pass `--ref-offset <samples>`.
6. In Pro Tools, import the output, spot it to its original timestamp, and check
   that it lines up with the reference and with the picture at the expected
   record timecode.
7. Save the diagnostic report together with the result, for the records.

If the samples match after any documented format conversion, Avid
interoperability is verified for that export type. Repeat the procedure for each
frame rate used in production, and for 29.97 drop-frame if it applies.
