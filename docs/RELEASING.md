# Going public on GitHub

A checklist for publishing NineLives as `github.com/Vyeche/NineLives`. Do the steps in order; the
`gh` commands assume the GitHub CLI is logged in as Vyeche (`gh auth status`).

## 1. Before pushing
- [ ] `bash scripts/check.sh` passes (the Gauntlet runs the same).
- [ ] Nothing private in the files you'll publish:
      `git grep -n -i -E '/home/[a-z]|documents/|claude-launcher|@[a-z0-9-]+\.(lan|local|net)\b'`, plus
      your own user, host and bot names, should only show deliberate mentions (test paths like
      `/home/me`, the old `~/.cache/claude-launcher` folder in Whats-New).
- [ ] Decide about the old history (section 7) **before** the first push: anything pushed to a
      public repo should be treated as published for good.

## 2. Create the repository and push
```bash
gh repo create Vyeche/NineLives --public \
  --description "A kitty setup for watching many AI coding sessions at once: live tab status, sounds, a cat, restarts that keep every tab"
git remote add github git@github.com:Vyeche/NineLives.git   # keeps your existing origin as it is
git push github main
```
(Or make GitHub `origin` and keep the old remote under another name; `scripts/publish-wiki.sh`
follows `origin` unless you set `WIKI_REMOTE`.)

## 3. Repository settings
- [ ] **Private vulnerability reporting** on (SECURITY.md sends reporters there):
      Settings → Security → *Private vulnerability reporting* → Enable, or
      `gh api -X PUT repos/Vyeche/NineLives/private-vulnerability-reporting`
- [ ] **Dependabot alerts** on: Settings → Security → *Dependabot alerts*, or
      `gh api -X PUT repos/Vyeche/NineLives/vulnerability-alerts`.
      Version updates for the pinned actions come from `.github/dependabot.yml` on their own.
- [ ] **Wiki** on: Settings → General → Features → *Wikis* (`gh repo edit Vyeche/NineLives --enable-wiki`).
      Keep *Restrict editing to collaborators only* ticked: `docs/wiki/` is the source, and every
      publish overwrites edits made on the web.
- [ ] **Sponsor button**: `.github/FUNDING.yml` shows it once GitHub Sponsors is set up for the account
      and Settings → General → Features → *Sponsorships* is ticked.
- [ ] Topics (optional): `gh repo edit Vyeche/NineLives --add-topic kitty,terminal,claude-code,linux,cosmic`

## 4. Protect main (after the first Gauntlet run)
The `required` check can only be picked once it has run, so push first (step 2) and wait for the
Gauntlet to finish. Then Settings → Rules → Rulesets → *New branch ruleset*:
- Target: the default branch (`main`); enforcement *Active*.
- **Require status checks to pass**: add `required` (source: GitHub Actions). It's the one summary
  check: new Gauntlet lanes join it without a settings change.
- **Block force pushes** and **Restrict deletions**.
- **No required pull request reviews**: with one maintainer nobody else could approve.
- Bypass list: add *Repository admin* (yourself) if you want to keep pushing straight to `main`; a
  required check otherwise blocks direct pushes, and every change then goes through a pull request
  (which is how outside contributions arrive anyway).

## 5. Publish the wiki
GitHub creates the wiki's git repository only when the first page is saved in the web UI.
1. Open the Wiki tab and save any first page (it gets replaced).
2. Publish `docs/wiki/` (it finds the wiki's branch by itself; GitHub wikis use `master`):
   ```bash
   WIKI_REMOTE=github bash scripts/publish-wiki.sh --dry-run   # or no WIKI_REMOTE if GitHub is origin
   WIKI_REMOTE=github bash scripts/publish-wiki.sh
   ```
3. Check that Home shows the sidebar image (it loads from `raw.githubusercontent.com`, so the repo must be public).

## 6. What the first Gauntlet run does
On the push to `main` (and on every pull request):
- `lint` (actionlint), `quick` (`check.sh --quick`, about a minute) and `kitty` (the full `check.sh`
  with kitty 0.51 on a hidden display, about three minutes; its screenshot and logs are kept as the
  `gauntlet-kitty-<sha>` artifact for 14 days), then `required` sums them up.
- `guard` (HOL Guard's repository scan, attestation and SARIF upload) runs on pushes to `main`,
  weekly and by hand, never on pull requests. It isn't part of `required`. Look at its log on the
  first run; its findings show under Security → Code scanning.
- Dependabot may open its first pull requests for the pinned actions within a week.

If `kitty` fails only on the runner, the artifact's `kitty.log` and screenshot usually say why.

## 7. The old history
The existing history (55 commits so far) contains private details that the current files no
longer have: local paths, the private Git host's name, the old launcher socket, and the committer
names and addresses of the bot accounts. Pushing `main` as it is publishes all of that. Check with:
```bash
git log -p | grep -n -i -E 'documents/|claude-launcher' | head   # and your host and user names
git log --format='%an <%ae>' | sort -u
```
To publish **without** the old history, start a fresh branch from the reviewed files and push only
that (the full history stays in your private repo):
```bash
git checkout --orphan public-main          # keeps every file staged
git add -A                                  # the working tree, exactly as reviewed
git commit -m "NineLives: first public release"
git push github public-main:main
git switch main                              # back to the full history locally
```
Later public commits then go on top of `public-main` (e.g. keep working there and push it to
`github main`). Commit as the identity you want shown publicly (`git config user.name` / `user.email`;
GitHub's `<id>+Vyeche@users.noreply.github.com` address keeps your e-mail private).

## 8. First release (optional)
```bash
git tag -a v1.0.0 -m "NineLives 1.0.0"
git push github v1.0.0
gh release create v1.0.0 --repo Vyeche/NineLives --title "NineLives 1.0.0" \
  --notes "First public release. Install: see the README."
```
SECURITY.md supports the latest release and `main`.

## 9. Every release after that
Work happens in the private workbench; GitHub mirrors it.
1. **Workbench:** commit, `bash scripts/check.sh` green, push.
2. **Sync:** on a `release/vX.Y.Z` branch in the public clone, run
   `bash scripts/sync-public.sh <public clone> -m "…"` (commit messages keep `Co-Authored-By` but no
   session links). It stops on private words listed in the workbench's `.private-words` (git-ignored,
   one `grep -E` pattern per line); without that file it copies everything unchecked and says so.
3. **Pull request** from the bot account (vyeduo): push the branch, `gh pr create`, then comment
   `@coderabbitai review` (CodeRabbit only reviews by itself once the repo has 10 stars). Answer its
   findings.
4. **Merge** once the Gauntlet's `required` check is green. Write the release notes to `notes.md`
   (what changed for users, how to update), then on `main`:
   `gh release create vX.Y.Z --target main --title "NineLives X.Y.Z" --notes-file notes.md`, and tag
   the same workbench commit `vX.Y.Z`. Publish the wiki if docs changed.
5. **Announce** every release (no "Generated with" footers):
   - **GitHub Discussions → Announcements:** what changed for users, how to update
     (`git pull && bash scripts/install.sh`, then `bash scripts/kitty-relaunch.sh --when-idle`).
   - **X:** one post, under 280 characters, with the release link.
   - **LinkedIn:** a short post: the one change people will notice, the release link.
   - Bigger releases: a post on the owner's blog (Yoast all green) and, when the look changed, a new
     YouTube Short (`tools/short/`).
   Small fix releases can be announced together with the next one.
