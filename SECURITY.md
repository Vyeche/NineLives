# Security policy

## What NineLives is, and what could go wrong

NineLives is a kitty configuration. Everything runs locally, as you, on your own machine:

- **Inside kitty:** `config/kitty.conf` and `config/tab_bar.py`, which kitty loads as Python into its
  own process to draw the sidebar. It reads tab titles, folders and program status from kitty, writes
  quest progress to `~/.local/state/ninelives/`, plays sounds with `paplay` and sends notifications
  over the local D-Bus session bus (`gdbus`); on macOS with `afplay` and `osascript` (the
  notification's text is passed to `osascript` as arguments, never as part of its script).
- **Shell scripts and helpers** you run yourself: `scripts/install.sh`, `scripts/uninstall.sh`,
  `scripts/kitty-relaunch.sh` (with `scripts/kitty-tabs.py`), `config/tips.sh` (sourced by your
  `~/.bashrc` or `~/.zshrc`), `config/shortcuts.sh`, `config/tab-finder.py` and `config/settings.py`
  (the settings list; it writes only the switch files in kitty's config folder, and with the
  one-off remote-control connection kitty hands it, asks kitty to open `kitty.conf` in your editor).
- **Remote control:** `kitty.conf` turns on kitty's remote control over a socket only
  (`allow_remote_control socket-only`), at `$XDG_RUNTIME_DIR/ninelives-kitty-<pid>`, a folder only
  your user can open (on macOS, which has no `XDG_RUNTIME_DIR`, in your temp folder `$TMPDIR`,
  which is private to you too). The restart script uses it to read and reopen your tabs.

NineLives makes **no network connections at runtime** and has no server, account or telemetry. The
only network use is in maintainer tools: `scripts/publish-wiki.sh` (a `git push` of the wiki) and
the GitHub Actions workflow that tests it.

Realistic problems we want to hear about:
- A crafted **tab title, folder name or command line** (for example from a repository you cloned, or
  a program that sets its own title) that makes `kitty-relaunch.sh` write a session file that runs
  something you didn't run before, or makes the sidebar or the tab search misbehave.
- A file in the **state or cache folders** (`~/.local/state/ninelives/`, `~/.cache/ninelives/`)
  that makes NineLives run code or overwrite something outside them.
- `install.sh` or `uninstall.sh` **deleting or overwriting a file** that isn't NineLives' own or
  one of its own backups.
- The remote-control socket being **reachable by another user** on the same machine.

## Supported versions

| Version | Supported |
| --- | --- |
| latest `main` / latest release | yes |
| anything older | no: update first (`git pull`, then `bash scripts/install.sh`) |

## Reporting a vulnerability

**Preferred: report it privately** through GitHub's private vulnerability reporting:
[Security → Report a vulnerability](../../security/advisories/new). Only the maintainer sees it.

If you're comfortable with it being public (for example a low-risk hardening idea), a normal
[issue](../../issues) is fine too.

Please include:
- your kitty version (`kitty --version`) and the output of `ninelives` (run it in kitty);
- the steps to reproduce: the tab title, folder name or file that triggers it, and the commands you ran;
- for restart problems, the relevant lines of `~/.cache/ninelives/kitty-relaunch.log`.

## What to expect

- A first answer within a week.
- A fix in the next release, with a regression test, and a GitHub security advisory when it
  affects users.
- Credit in the advisory and in the release notes, unless you'd rather not be named.

## Out of scope

- **kitty itself**: report bugs in kitty to [kitty's issue tracker](https://github.com/kovidgoyal/kitty/issues).
- Attacks that need code already running as your user (it can change your kitty config, your
  `~/.bashrc` or anything else you own anyway).
- Turning remote control on in general: that is how the restart works; see kitty's docs on
  `allow_remote_control` if you'd rather turn it off (the restart then can't find kitty).
