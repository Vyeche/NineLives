# AGENTS.md — working on NineLives

Instructions for AI coding agents (Claude Code and others) changing this repo. What the product is
and why: [PRODUCT.md](PRODUCT.md). How it works: [docs/wiki/How-It-Works.md](docs/wiki/How-It-Works.md).
How to test: [docs/wiki/Testing.md](docs/wiki/Testing.md).

## The owner is using this machine: don't disturb them
- **Never touch the real kitty**: the one you are running in (`$KITTY_LISTEN_ON`), the owner's
  launcher socket if any, and any `$XDG_RUNTIME_DIR/ninelives-kitty-*` socket. Don't send it commands
  (not even `kitty @ ls`), don't relaunch it, don't install into `~/.config/kitty`. Installing and
  restarting it is the owner's call (`bash scripts/install.sh`, then
  `bash scripts/kitty-relaunch.sh --when-idle`).
- **Never run `scripts/kitty-relaunch.sh` without `NL_KITTY_SOCKET`** (not even `--status` or
  `--dry-run`): on its own it picks the kitty it runs in, which is the owner's. Use
  `bash scripts/test-kitty.sh relaunch`, or `NL_KITTY_SOCKET=unix:@ninelives-test-kitty`.
- **Never `kitty @` without `--to`**, or with an empty one: it falls back to `$KITTY_LISTEN_ON`.
- **No sound on the real speakers.** Tests use stubs; the dev kitty runs muted (`NINELIVES_QUIET=1`).
- **No focus stealing.** Don't focus tabs or windows on the real desktop. Update the dev kitty with
  `bash scripts/dev-kitty.sh reload` (no new window); `restart`/`start` open a window that COSMIC
  focuses, so only do that when there's no dev kitty yet.
- **No desktop-wide screenshots.** Take pixels from the hidden test kitty (`test-kitty.sh shot`).
- **No desktop attention requests.** kitty's `request_attention` makes COSMIC raise and focus kitty
  (seen 2026-11-22); NineLives must not use it.
- `pkill -f` / `pgrep -f` can match your own shell: use patterns like `"[-]-listen-on …"`.

## Where to test
| Kitty | What | How |
| --- | --- | --- |
| hidden test kitty | Xvfb display `:97`, socket `unix:@ninelives-test-kitty`, stubbed sounds, its own config and state | `bash scripts/test-kitty.sh start [dark\|light] [WxH]`, `k …`, `shot NAME`, `sounds`, `stop` |
| dev kitty | a visible window with its own config (`~/.cache/ninelives-dev`), muted | `bash scripts/dev-kitty.sh start\|reload\|stop` |
| unit tests | fake kitty modules, no display | `python3 -m unittest discover -s tests` |
| everything | syntax, unit tests, install, sounds and loudness, links, test-kitty E2E | `bash scripts/check.sh` (`--quick` skips the test kitty) |

- Only one agent at a time may use the hidden test kitty (one display, one socket).
- Click on the test display with `python3 scripts/xclick.py :97 X Y` (XTest; never the real pointer).
  `$NINELIVES_STATE/sidebar.txt` says which tabs are shown and where the buttons are.
- Run the relaunch only against the test kitty: `NL_KITTY_SOCKET=unix:@ninelives-test-kitty`.
- `bash scripts/check.sh` must pass before every commit (gate on its exit status).

## kitty internals
- `config/tab_bar.py` monkeypatches kitty internals (TabBar, TabManager, Boss). Every patch checks what
  it relies on and switches itself off if kitty renamed it, and carries a `_vye_patched` guard.
- Patches stay installed across a config reload, so they reach the current code through hooks on
  `kitty.tab_bar` (`_vye_*` attributes). New behaviour behind an existing patch needs a hook, or it only
  appears after a kitty restart.
- Read kitty's source for the installed version (0.51) before relying on an internal; don't guess.

## Hard problems go to a high-effort sub-agent
For difficult or complex work (kitty internals, tricky features, deep reviews), spawn a sub-agent with
high effort instead of working it out at medium effort. Brief it fully: the goal, the files, the rules
above, and "don't commit; report back". Routine work (docs, tests, small tweaks) stays in the main
thread. Review its changes before committing.

## After a change
- Keep README, the wiki (`docs/wiki/`), the F1 sheet (`config/shortcuts.sh`) and the tips
  (`config/tips.sh`) in step with behaviour; add a line to `docs/wiki/Whats-New.md`.
- Text ≥ 4.5:1 and icons ≥ 3:1 in both themes (check light and dark screenshots). Use palette colours,
  not SGR dim, for secondary text.
- Sounds stay subtle: rebuild with `python3 scripts/make-sounds.py`; `check.sh` checks loudness.
- Publish the wiki after doc changes: `bash scripts/publish-wiki.sh`.

## Public repo hygiene
- Before posting a commit, PR, issue or comment, scan its text and diff for local paths, host names,
  user names, e-mail addresses and tokens; leave them out.
- Test fixtures and examples use made-up names (`/w/proj`, `code/webapp`, `abc-123`), never real ones.
- The Gauntlet (`.github/workflows/gauntlet.yml`) runs `check.sh` on every PR; keep it green, keep
  every action and download pinned (commit SHA or SHA-256), and never give a job that runs PR code
  write permissions or secrets.

## Commits and pushing
- Commit as the repo's configured git user on `main`; push to `origin`. Commit or push only when the
  owner asked for it in the session.
- End commit messages with the attribution lines the session gives you.
- Never commit secrets.
