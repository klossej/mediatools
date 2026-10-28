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
