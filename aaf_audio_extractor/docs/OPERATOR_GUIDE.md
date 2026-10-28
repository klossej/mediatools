# AAF Audio Extractor — Operator Guide

## The window

| Area | What it is for |
|---|---|
| **Input files** (top) | The queue of AAF files, with sequence, record timecode, duration, chosen tracks and status |
| **Tracks** (bottom left) | The tracks of the file selected in the queue, and the left/right assignment |
| **Export** (bottom right) | Output folder, file naming, existing-file behaviour, media folder, export buttons and progress |

## Standard batch (for example, 32 episodes)

1. **Add the files.** Drag the AAFs, or their folder, onto the window, or use
   **Add AAF Files…** or **Add Folder…**. Each file is inspected in the
   background; the status reads *Inspecting* until it has been read.
2. **Pick the tracks.** Click any file. In **Tracks**, set **Left channel** and
   **Right channel**. The table shows each track's number, name, format, duration
   and whether its media is available.
3. **Choose how files are matched.** *Match tracks across files by*:
   * **Track number**: A1 is A1 in every file. This is the best choice when
     every episode has the same track layout.
   * **Track name**: use this when the mix tracks have consistent names in Avid
     (for example "MIX L" / "MIX R") but sit on different track numbers.
4. Click **Apply to All Files**. Every file is checked at once:
   * **Ready**: it will export.
   * **Needs attention**: something must be decided, such as a missing track, a
     missing timecode, several sequences, an output name collision or missing
     media. Hover over the row to see the details.
   * **Unsupported**: the AAF contains something this version cannot reproduce
     faithfully, such as crossfades, effects, gain changes or non-48 kHz media.
     It will not be exported.
5. Set the **Output folder** and check the **Filename** preview
   (`501.aaf → 501_MIX.wav`).
6. Click **Export All**, or select some rows and click **Export Selected**.
   Files that are not Ready are skipped; the others are still exported.

When the batch finishes, a summary shows the totals, the elapsed time and the
output folder. `AAF_Export_Report_<date>_<time>.csv` is written to the output
folder.

## Auto-detect the stereo mix (recommended when the mix track moves)

Tick **Auto-detect stereo mix track in every file**. Each AAF is then searched
for its mix:

* a stereo track the app can extract faithfully (no effects, gain changes or
  fades on it);
* with audio over at least 90% of the sequence, which rules out stereo music or
  effects beds;
* if several tracks qualify, the one whose clip or track name contains "MIX".

Channel 1 goes to Left and channel 2 to Right. The Left/Right columns show, for
example, `A31 ch1 (auto)`. The CSV report has a "Track selection" column, and
the reason for each choice is in the row tooltip and in the diagnostic report.

If a file has no such track, or several equally likely ones, it is marked
*Needs attention* with the candidates named. Pick its tracks by hand and click
**This File Only**; a per-file choice always wins over auto-detect.

Workflow for a series: add the 32 AAFs, tick auto-detect, set the output folder,
click **Export All**.

## Stereo tracks (e.g. a stereo mix on A31)

An Avid stereo track appears once in the track table, with "stereo" in its
format, and twice in the Left/Right lists: `A31 ch1 (stereo L)` and
`A31 ch2 (stereo R)`. Choosing ch1 as Left sets Right to ch2 automatically. Then
click **Apply to All Files**. The batch mapping becomes "Left A31 ch1 · Right A31
ch2" and is applied to every episode.

If, in some episode, that track is mono or has a different layout, the file is
marked *Needs attention* rather than exported with the wrong channel. An empty
track (for example A32 when the mix is on A31) is also reported, never exported
as silence.

## Per-file adjustments

* **This File Only**: choose different left/right tracks for the selected file
  and click this. The file's tracks are marked `*` in the queue. Use **Revert to
  Batch Mapping** to undo it. **Apply to All Files** clears all overrides.
* **Sequence**: if an AAF contains several sequences, choose the right one here.
  The file stays *Needs attention* until you do.
* **Set Timecode…**: if the AAF has no usable record timecode, enter it here
  (for example `10:00:00:00` at `25`). The override is marked "(manual)"
  everywhere and in the report. **Use AAF Timecode** removes it.

## Existing files, retries and cancelling

* **If file exists**:
  * *Skip* (default) keeps the existing file and reports it as skipped.
  * *Add a number* writes `501_MIX_1.wav`.
  * *Overwrite* replaces the existing file.
* **Retrying**: fix the problem, then click **Export All** again. Completed files
  are not exported again.
* **Cancel**: stops the file being exported and deletes its incomplete output.
  Files already finished are kept. Files not yet started stay *Ready*.
* To export a completed file again, remove it from the list, add it back, and
  choose *Overwrite* or *Add a number*.

## Linked (non-embedded) media

AAFs exported with embedded audio need nothing else. If the AAF links to media
files instead:

* The app first looks at the path stored in the AAF.
* If the files have moved, set **Media folder** to a folder that contains them
  (subfolders are searched too).
* MXF files are matched by their internal media ID, not by name.
* WAV/AIFF files are matched by name, but only when the sample format and length
  also match the AAF. If two files could match, the app stops and asks rather
  than guess.

## Checking a result in Pro Tools

1. Import the WAV into a session at the same frame rate.
2. Use **Spot** / *Original Time Stamp* (or drag with *Spot to original timestamp*).
3. The region should start at the sequence's record start (for example 10:00:00:00).

The rate and drop-frame mode are in the file's Description and in the CSV
report, because the BWF timestamp itself is only a sample count.

## When something is wrong

Click **Save Diagnostic Report…** and send the text file. It lists, for every
queued AAF: its sequences, tracks, every clip and gap, the source media IDs and
in-points, the computed sample positions, the timecode and the TimeReference,
plus the recent log.
