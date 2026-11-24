# Operator guide

## Load and prepare a script

1. The operator page opens the previous server script at its saved position. Choose **Open Script** to select another saved script, **Import file** for a local UTF-8 `.md` or `.txt` file, or paste into the editor.
2. Put `*#` on its own line wherever a new cue should begin. **Insert cue** adds a marker at the selection or caret. Both displays show a blank line between cues and preserve ordinary paragraph breaks.
3. Select text and use **B**, **I** or **U** to format it. **Save** writes to the server using the current filename. **Save As** saves a new server file under a different name. Both keep the formatting, presentation settings and reading position. Use **Download .md** for a portable copy or **Export .txt** for a plain manuscript with cue markers.
4. Collapse **Script** when you need a larger preview.

Markdown files saved by KråtaPrompter reopen paused at the saved position. Scripts with no settings open at the beginning with the application defaults. Presentation edits mark the script as unsaved. Save again to record a new reading position. **Reset Presentation Settings** restores the defaults for the current script and keeps your place.

Click the bold script name in the header to edit it. Press **Enter** to accept or **Escape** to cancel. Save stores the edited name with the script while keeping the existing server filename. The header shows the last successful save as **Version YY.MM.DD HH:MM** in the operator workstation’s local time.

## Find and zoom in the editor

Select **Find** or press **Ctrl+F** or **Command+F** while editing. **Enter** moves to the next match and **Shift+Enter** moves to the previous one. **Escape** closes the panel and selects the current match in the manuscript.

Use **−** and **+** to zoom the editor text from 70% to 200%. Select the percentage to reset to 100%. Presenter text size is set in **Display & speed**.

If another operator saves a newer revision of the same file, use **Save As** to keep your work as a separate script or **Open Script** to read the newer copy.

## Put the presenter on air

1. Select **Open presenter**. Allow pop-ups for the app if your browser blocks the window.
2. Drag the window to the presenter monitor. Double-click the black area or press **F** to enter fullscreen. Exiting fullscreen pauses the script.
3. Use the presenter’s horizontal or vertical mirror controls to suit the glass and display mounting. The preview has its own mirror controls. Move, resize or hide the reading guide for both views using **Guide position**, **Guide arrow size** and **Reading guide**. The guide flips with vertically mirrored text.
4. Adjust font, colours, spacing, alignment, width and speed in **Display & speed**. The panel sits to the right of the preview on desktop and below it on narrower screens. Text size goes up to 200 px at 1080p. Paragraph spacing and scroll speed also use the 1080p reference. Side margins set a minimum inset and text width can narrow the column further. Try a cue jump and a short scroll before the presenter goes on air.

Select **Close presenter** to close the companion window. Opening it again restores the live position and settings from the operator window. Keep the operator window open during the session.

The script editor highlights the line at the presenter’s reading guide. The scrollbar moves as playback reaches each new paragraph or a line moves out of view. It follows the preview when the presenter is closed. The editor keeps its scroll position and caret while it has keyboard focus.

## Transport

| Key | Action |
|---|---|
| Space | Play or pause |
| Right | Next cue |
| Left | Previous cue |
| Up | Increase speed |
| Down | Decrease speed |
| Home | Pause and return to the beginning |
| Escape | Pause |

The transport buttons and speed slider also work with the mouse. Click out of the script editor to use the transport shortcuts. The presenter window forwards them to the operator. Play eases up to reading speed and Pause eases to a stop. The selected speed stays steady through line wraps and paragraph breaks. At the end the screen clears and playback stops. **Replay** starts again from the beginning.
