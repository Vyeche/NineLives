## What and why
<!-- What changes for someone using NineLives, and why. Link the issue if there is one. -->

## How it was tested
<!-- The Gauntlet runs scripts/check.sh on this PR. Say what else you checked by hand. -->

- [ ] `bash scripts/check.sh` passes locally (the Gauntlet runs it too)
- [ ] New behaviour has a unit test in `tests/` or a check in `scripts/check.sh`
- [ ] Sidebar or overlay changes: screenshots in **both** the dark and the light theme
      (`bash scripts/test-kitty.sh start dark|light`, then `shot NAME`), attached below

## Keeps the promises (PRODUCT.md, AGENTS.md)
- [ ] Status still reads at a glance; text ≥ 4.5:1 and icons ≥ 3:1 in both themes
- [ ] Nothing interrupts a working session; anything new can be turned off
- [ ] Sounds stay subtle (`python3 scripts/make-sounds.py`; check.sh checks loudness)
- [ ] Patches to kitty internals check what they rely on and switch themselves off if it's missing
- [ ] Docs in step: README, `docs/wiki/` (with a line in Whats-New), the F1 sheet, the tips

## Screenshots
