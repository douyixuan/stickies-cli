# stickies-cli

`stk` is a small command-line wrapper for the macOS Stickies app. It lets you and your coding agents read notes, arrange them in a grid, and prepare experimental offline note creation. It does not use UI automation.

## Why

Stickies has no API. Agents usually operate it with screen automation. That method is slow and takes the keyboard focus. `stk` reads the note files directly, so a read is fast and does not touch the screen.

## Requirements

- macOS (tested on macOS 26.6)
- Python 3.9 or later (standard library only)

## Install

```bash
git clone https://github.com/douyixuan/stickies-cli.git
ln -s "$PWD/stickies-cli/stk" /usr/local/bin/stk
```

## Commands

| Command | Function |
| --- | --- |
| `stk ls [--json]` | List all notes with their numbers. |
| `stk show <id-or-text>` | Print the full text of one note. |
| `stk find <text>` | Search the text of all notes. |
| `stk create TITLE --url URL [--body TEXT] [--apply]` | Preview or store a new note while Stickies is closed. |
| `stk open` | Bring Stickies and all its notes to the front. |
| `stk tile [options]` | Arrange all notes in a grid on one screen. |

`<id>` is the number that `stk ls` shows. The numbers follow the position of the notes on the screen: the top row first, then left to right. Stickies saves positions only when it quits, so the numbers can be out of date after you move a note by hand.

### Arrange notes

`stk tile` prints a preview of the numbered grid and changes nothing. Add `--coords` to print the coordinates instead:

```bash
stk tile --screen 1 --cols 4
```

Add `--apply` to use the plan:

```bash
stk tile --screen 1 --cols 4 --apply
```

`--apply` quits Stickies, saves a backup of the window state to `~/.stk/backups/`, writes the new positions, and starts Stickies again. Stickies reads window positions only at startup, so the restart is necessary.

| Option | Default | Function |
| --- | --- | --- |
| `--screen N` | `0` | Index of the display. |
| `--cols N` | automatic | Number of columns. |
| `--width`, `--height` | `300`, `200` | Largest size of each note. |
| `--gap` | `8` | Space between notes. |
| `--top` | `0` | More space at the top of the screen. `stk` already leaves space for the menu bar. |
| `--sort` | `pos` | Order: `pos` (keep the current order), `mtime`, `title`, or `z`. |

All notes stay on the screen that you select. If the notes do not fit at the given size, `stk tile` makes them smaller and prints the new size. If you do not give `--cols`, `stk tile` selects the number of columns that keeps the notes largest. If the notes cannot fit at a readable size, `stk tile` stops and changes nothing.

### Restore positions

```bash
osascript -e 'tell application "Stickies" to quit'; sleep 2
cp ~/.stk/backups/SavedStickiesState.<timestamp> \
  ~/Library/Containers/com.apple.Stickies/Data/Library/Stickies/.SavedStickiesState
open -a Stickies
```

## Hotkey

`raycast-show-stickies.sh` is a [Raycast](https://www.raycast.com/) script command that shows all notes. Add its folder in Raycast (Settings > Extensions > Script Commands), then assign a hotkey.

## Limits

- `stk create` can write a new RTF bundle and append its index while Stickies is closed. One real note was subsequently observed in Stickies with its hyperlink control. The user confirmed the actual link click; one guarded restart passed sampled focus, clipboard and saved-layout checks. It cannot change existing note text.
- `stk` cannot move notes between Spaces. To show the notes on all desktops, right-click the Stickies icon in the Dock, then select Options > All Desktops.
- `stk tile` does not change the collapsed state or the float-on-top state of a note.
- The task commands (`add`, `set`, `done`, `link`, `tasks`) are experimental. They keep a task list in `~/.stk/tasks.json` (or `$STK_TASKS`).
- The note file format is not a public interface. A later macOS release can change it.

## License

MIT

## Experimental background creation

`stk create` writes files directly. It does not use the clipboard, send keys, activate an app, quit Stickies, or restart it. The default is a read-only preview:

```bash
stk create '项目｜任务' --body '进展与下一步' --url 'https://example.com/task/123'
```

Add `--apply` only while Stickies is closed. Keep it closed throughout the import. A running-app check rejects an active Stickies process, but cannot prevent a person from starting the app between the check and the write.

The command stores `TXT.rtf` in a new UUID bundle and appends one entry to `.SavedStickiesState`. It keeps existing entries unchanged and backs up the index under `.stk-backups/`. It preserves Unicode, line breaks, and a named RTF hyperlink. The URL is also the deduplication key: a repeat request does not replace the original note. New notes use a 300 × 200 frame at (40, 40); their actual screen placement is unverified.

Use `--store /absolute/path/to/isolated-directory --apply` to test against an existing sandbox directory. This does not import anything into the real app.

Results distinguish `planned`, `stored`, and `exists`. `stored` only confirms file creation. `ui_verified` remains false, and the app must load the files on a later launch. One real import was observed on screen with an AXLink and correct text. This does not guarantee every future import or sub-sampling-interval focus behavior. The user confirmed link activation, and a guarded restart passed preservation checks. The guarded task hook calls this writer only under the checks described below.

The file format is private. Back up your notes before a real import. An interrupted import can leave an unindexed bundle; the command detects a matching orphan and stops instead of creating a duplicate. It does not claim a two-file crash-atomic transaction.

Run the macOS file-format regression tests:

```bash
python3 -m unittest discover -s tests -v
```

## Guarded task hook

The local task hook now uses `background_runtime.py` under `focus_guard.swift`. The guard samples the foreground app, its focused accessibility element, and the clipboard change count every 20 ms. It never reads clipboard contents or restores focus. This is sampled detection, not a guarantee against every sub-interval transition. A user switching focus also causes a failed report.

On this Mac, a real restart completed with 167 samples and no foreground, focused-element or clipboard-count change. Existing content and saved window state remained unchanged. The new note was visible, and the user confirmed its link returned to the intended chat. An earlier run detected focus changes; an idle control also detected a dialog-to-web-area transition. Those failures remain in the validation record.

`integrations/stickies-hook/` contains the installed hook sources and tests, without receipts, note content, backups or reports. The local installation uses `~/code/stickies-cli` and `~/.stk/focus_guard`; adapt the runtime path for another machine. Build the guard with:

```bash
swiftc focus_guard.swift -o ~/.stk/focus_guard
```

The hook holds a desktop lease, deduplicates existing task links without restarting, and latches failed imports for inspection. New imports back up the current store, verify old notes before and after the restart, and require an exact local AX snapshot with a link. It never clicks task links during automatic creation. The entry point records success only after the guard passes. Existing notes remain user-maintained.
