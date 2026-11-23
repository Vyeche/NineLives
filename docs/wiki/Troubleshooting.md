# Troubleshooting

**First step for anything:** `bash scripts/check.sh` runs every check on the repository, and
`bash scripts/install.sh` ends with kitty's own config check (`Config check found problems` names the setting).

### --when-idle never restarts
It says when you start it which tabs it's waiting for, and the log
(`~/.cache/ninelives/kitty-relaunch.log`) records the list whenever it changes.
`bash scripts/kitty-relaunch.sh --status` checks again: working, needs you, spinner, or a running
command. Answer or finish those, or restart now without `--when-idle`.

### The restart says "no kitty to restart" or "several kitty windows"
- **No kitty to restart:** no kitty has a remote-control socket that answers. NineLives' `kitty.conf`
  gives every kitty one, but only from its next start: close kitty and open it again once after
  installing. Also check that `$XDG_RUNTIME_DIR` is set (`echo $XDG_RUNTIME_DIR`): the socket lives there.
- **Several kitty windows:** more than one kitty has a socket and the script was run from outside
  them. Run it from a tab of the kitty you want to restart.

### No sound
- Muted? `ls ~/.config/kitty/sounds-off` (Ctrl+Alt+M or `kitty-sounds on`).
- Volume set very low? `kitty-sounds volume` shows it.
- The tab you're looking at doesn't chime when it finishes or fails: that's on purpose.
- `kitty-sounds` plays each sound; if that is silent too, check `paplay` and the system volume.
- Sounds missing from `~/.config/kitty/sounds/`? Re-run `bash scripts/install.sh`. Without them it falls back to the desktop's sounds.

### Sounds too loud or too quiet
`kitty-sounds volume 30` (or any 5–100). To change one sound, see [Sounds](Sounds#changing-a-sound).

### The sidebar looks like plain kitty, or shows only a bare "+"
`tab_bar.py` didn't load or failed. Start a kitty from another terminal to see its messages:
```bash
kitty --hold sh -c 'echo test' 2>&1 | grep -iv transparency
```
Then restart the main window with `bash scripts/kitty-relaunch.sh --when-idle`.
If one tab shows just its number and title, drawing that tab failed and NineLives fell back to a plain line
instead of breaking the whole sidebar.

### A change to tab_bar.py doesn't show
Restart kitty (`bash scripts/kitty-relaunch.sh --when-idle`). Ctrl+Shift+F5 runs the new file, but the
patches it puts into kitty (dragging, the "+ New tab" label, click areas) keep their old version until a restart.

### Dragging a tab does nothing
On COSMIC Wayland NineLives handles the drag itself. If a kitty update renamed something it relies on, the
patch switches itself off; **Ctrl+Shift+← / →** still moves tabs. Note which kitty version broke it.

### A quest won't count
- Quests only count shortcuts, not shell commands.
- Quests are off? `ls ~/.config/kitty/quests-off`.
- A mouse drag counts for Shuffler only when the drag finishes inside the sidebar.

### No tip under the prompt
Check the `tips.sh` line in `~/.bashrc` ([Installing](Installing#prompt-tips)) and `~/.config/kitty/tips-off`.

### The prompt is plain white
Not NineLives: Ubuntu's default `~/.bashrc` only colours the prompt for `*-256color` terminals, and
kitty's `TERM` is `xterm-kitty`. Uncomment `force_color_prompt=yes` near the top of `~/.bashrc`.

### The status icon is wrong
- A plain tab spins while any command is in the foreground (but not vim, less, htop or an idle agent).
- omp/opencode count as working while their title has a spinner.
- ✓ stays until you look at the tab.
