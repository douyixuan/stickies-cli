# stickies-cli

`stk` is a small command-line wrapper for the macOS Stickies app. It lets you and your coding agents read the notes and arrange them in a grid. It does not use UI automation.

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

- `stk` cannot create a note or change note text. Stickies must do that.
- `stk` cannot move notes between Spaces. To show the notes on all desktops, right-click the Stickies icon in the Dock, then select Options > All Desktops.
- `stk tile` does not change the collapsed state or the float-on-top state of a note.
- The task commands (`add`, `set`, `done`, `link`, `tasks`) are experimental. They keep a task list in `~/.stk/tasks.json` (or `$STK_TASKS`).
- The note file format is not a public interface. A later macOS release can change it.

## License

MIT
