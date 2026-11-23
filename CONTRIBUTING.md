# Contributing to NineLives

Thanks for helping! Issues and pull requests are welcome. Everyone taking part follows the
[Code of Conduct](CODE_OF_CONDUCT.md). Security problems go through [SECURITY.md](SECURITY.md),
not a public issue.

## Before you start
- What NineLives is for, and the promises every change keeps: [PRODUCT.md](PRODUCT.md).
- How it works inside: [docs/wiki/How-It-Works.md](docs/wiki/How-It-Works.md).
- The working rules (also for AI coding agents): [AGENTS.md](AGENTS.md).

```bash
git clone https://github.com/Vyeche/NineLives.git && cd NineLives
```

## Test your change
Everything runs from one command, without touching your own kitty:
```bash
bash scripts/check.sh           # syntax, unit tests, install, sounds, links, and a hidden test kitty
bash scripts/check.sh --quick   # the same without the test kitty (no Xvfb needed)
```
The hidden test kitty needs `Xvfb`, `ffmpeg` and kitty 0.50+ (the official build). For sidebar
changes, take screenshots in both themes: `bash scripts/test-kitty.sh start dark` (or `light`), then
`bash scripts/test-kitty.sh shot NAME`. More in [docs/wiki/Testing.md](docs/wiki/Testing.md).

Don't run `scripts/kitty-relaunch.sh` against your own kitty to test a change: it restarts the kitty
you run it in. `bash scripts/test-kitty.sh relaunch` runs it on the test kitty only.

**Every fix ships with a regression test**: a unit test in `tests/` or a check in `scripts/check.sh`
that fails without the fix.

## The Gauntlet
Every pull request runs the **Gauntlet** (`.github/workflows/gauntlet.yml`) on a clean Ubuntu runner:
actionlint over the workflows, `check.sh --quick`, then the full `check.sh` with a real kitty on a
hidden display (screenshots and logs are kept as an artifact). Its `required` check sums them up. A
PR's code runs with a read-only token and no secrets. HOL Guard's repository scan runs on `main`
(and weekly), not on pull requests. A PR is merged once the Gauntlet is green and the change has
been reviewed.

## Style
- Plain, friendly, short words in everything people read (docs, tips, messages).
- Keep README, the wiki (`docs/wiki/`, with a line in `Whats-New.md`), the F1 sheet
  (`config/shortcuts.sh`) and the tips (`config/tips.sh`) in step with behaviour.
