#!/usr/bin/env bash
# check.sh — run every NineLives check before committing. Touches nothing outside a temp folder.
#   bash scripts/check.sh          everything (the last step needs Xvfb, ffmpeg and kitty)
#   bash scripts/check.sh --quick  skip the test-kitty step
# Steps: syntax · unit tests (tests/, no kitty needed) · install + kitty's config check · sound files
# and loudness · wiki/README links · a hidden test kitty (no errors, the right sounds, a working cat).
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
QUICK=0; [ "${1:-}" = --quick ] && QUICK=1
TMP="$(mktemp -d)"
# stop the test kitty first: its pid files live in $TMP
trap '[ -n "${NL_STARTED:-}" ] && bash scripts/test-kitty.sh stop; rm -rf "$TMP"' EXIT
fails=0
ok()   { printf '  \e[32mok\e[0m    %s\n' "$1"; }
fail() { printf '  \e[31mFAIL\e[0m  %s\n' "$1"; fails=$((fails + 1)); }
skip() { printf '  \e[2mskip  %s\e[0m\n' "$1"; }

echo "Syntax"
if out="$(PYTHONDONTWRITEBYTECODE=1 python3 - <<'EOF' 2>&1
import ast, sys
for f in ("config/tab_bar.py", "scripts/make-sounds.py", "scripts/vmouse.py"):
    ast.parse(open(f, encoding="utf-8").read(), f)
EOF
)"; then ok "python parses"; else fail "python: $out"; fi
bad=""; for f in config/*.sh scripts/*.sh; do bash -n "$f" 2>/dev/null || bad="$bad $f"; done
[ -z "$bad" ] && ok "shell scripts parse" || fail "shell syntax:$bad"

echo "Unit tests"
if out="$(PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests 2>&1)"; then
  ok "$(grep -oE 'Ran [0-9]+ tests?' <<< "$out") (tab_bar.py against a fake kitty; kitty-tabs.py; tips.sh)"
else fail "unit tests: $(grep -E '^(FAIL|ERROR):' <<< "$out" | head -5 | tr '\n' ' ')"; fi

echo "Install"
if command -v kitty >/dev/null; then
  out="$(KITTY_CONFIG_DIRECTORY="$TMP/inst" bash scripts/install.sh 2>&1)"; rc=$?
  if [ "$rc" = 0 ] && grep -q "Config check skipped" <<< "$out"; then
    ok "installs into a temp folder (config check skipped: kitty older than 0.50)"
  elif [ "$rc" = 0 ] && grep -q "Config check: OK" <<< "$out"; then
    ok "installs into a temp folder; kitty's config check passes"
  else fail "install: $(tail -3 <<< "$out")"; fi
  n="$(find config -type f ! -path '*/__pycache__/*' | wc -l)"; m="$(find "$TMP/inst" -type f ! -name '*.bak-*' | wc -l)"
  [ "$n" = "$m" ] && ok "every config file installed ($n, sounds included)" || fail "installed $m of $n files"
else skip "kitty not found"; fi

echo "Sounds"
missing=""; for s in done done-2 done-3 needs-you error badge rank drop; do [ -s "config/sounds/$s.oga" ] || missing="$missing $s"; done
[ -z "$missing" ] && ok "all eight sound files present" || fail "missing sounds:$missing"
if command -v ffmpeg >/dev/null; then
  # loudness targets (LUFS) from scripts/make-sounds.py, ±1.5
  loud=""
  for pair in done:-25 done-2:-25 done-3:-25 needs-you:-22 error:-25 badge:-25 rank:-24 drop:-35; do
    s="${pair%%:*}"; want="${pair#*:}"
    got="$(ffmpeg -hide_banner -nostats -i "config/sounds/$s.oga" -af "apad=pad_dur=2,ebur128" -f null - 2>&1 \
          | awk '/Summary/{f=1} f&&/I:/{print $2; exit}')"
    awk -v g="$got" -v w="$want" 'BEGIN{d=g-w; exit !(d<=1.5 && d>=-1.5)}' || loud="$loud $s=$got"
  done
  [ -z "$loud" ] && ok "loudness on target (subtle; needs-you a little louder)" || fail "loudness off target:$loud"
else skip "ffmpeg not found: loudness"; fi

echo "Docs"
if out="$(python3 - <<'EOF'
import re, os, glob
pages = {os.path.basename(p)[:-3] for p in glob.glob("docs/wiki/*.md")}
bad = []
for p in glob.glob("docs/wiki/*.md"):
    for t in re.findall(r"\]\(([^)#]+)(?:#[^)]*)?\)", open(p, encoding="utf-8").read()):
        if not t.startswith("http") and t not in pages:
            bad.append(f"{p}->{t}")
for t in re.findall(r"\]\(((?:docs|config|scripts)/[^)#]+)", open("README.md", encoding="utf-8").read()):
    if not os.path.exists(t):
        bad.append(f"README->{t}")
print(" ".join(bad))
EOF
)" && [ -z "$out" ]; then ok "wiki and README links resolve"; else fail "broken links: $out"; fi

echo "Test kitty"
if [ "$QUICK" = 1 ]; then skip "--quick"
elif ! command -v Xvfb >/dev/null || ! command -v ffmpeg >/dev/null; then skip "needs Xvfb and ffmpeg"
else
  export NL_TEST_DIR="$TMP/kitty"
  if bash scripts/test-kitty.sh start dark >/dev/null 2>&1; then
    NL_STARTED=1; sleep 4
    errs="$(grep -ci 'traceback\|invalid tab title' "$NL_TEST_DIR/kitty.log")"
    [ "$errs" = 0 ] && ok "no errors in the kitty log" || fail "$errs error(s) in $NL_TEST_DIR/kitty.log"
    snd="$(bash scripts/test-kitty.sh sounds)"
    grep -q "needs-you.oga" <<< "$snd" && ok "needs-you plays for a waiting tab" || fail "no needs-you sound: $snd"
    st="$(NL_KITTY_SOCKET=unix:@ninelives-test-kitty bash scripts/kitty-relaunch.sh --status)"
    grep -q "needs you" <<< "$st" && grep -q "working" <<< "$st" && ok "--when-idle sees working and waiting tabs" \
      || fail "relaunch --status: $st"
    bash scripts/test-kitty.sh k action toggle_layout stack >/dev/null 2>&1; sleep 1
    grep -q "^zoom" "$NL_TEST_DIR/state/badges" 2>/dev/null && ok "a shortcut earns its badge" || fail "badge not earned"
    # Ctrl+Alt+U's action: goes to the waiting tab (7) and earns First Responder
    bash scripts/test-kitty.sh k action launch --type=background --allow-remote-control \
      python3 "$NL_TEST_DIR/home/.config/kitty/tab-finder.py" waiting >/dev/null 2>&1; sleep 1.5
    act="$(bash scripts/test-kitty.sh k ls 2>/dev/null | python3 -c 'import json,sys; print([i+1 for i,t in enumerate(json.load(sys.stdin)[0]["tabs"]) if t["is_active"]])')"
    if [ "$act" = "[7]" ] && grep -q "^waiting" "$NL_TEST_DIR/state/badges" 2>/dev/null; then
      ok "Ctrl+Alt+U goes to the waiting tab (and earns its badge)"
    else fail "Ctrl+Alt+U: active tab $act, badges: $(cut -f1 "$NL_TEST_DIR/state/badges" 2>/dev/null | tr '\n' ' ')"; fi
    bash scripts/test-kitty.sh k focus-tab --match index:0 >/dev/null 2>&1; sleep 0.5
    # the search row's + opens a tab; the × on the current tab closes it again
    ntabs() { bash scripts/test-kitty.sh k ls 2>/dev/null | python3 -c 'import json,sys; print(len(json.load(sys.stdin)[0]["tabs"]))'; }
    btn() { grep "^button $1: " "$NL_TEST_DIR/state/sidebar.txt" 2>/dev/null | cut -d' ' -f3-; }
    before="$(ntabs)"; read -r bx by <<< "$(btn new)"
    python3 scripts/xclick.py "${NL_TEST_DISPLAY:-:97}" "${bx:-0}" "${by:-0}" >/dev/null 2>&1; sleep 1
    added="$(ntabs)"; read -r cx cy <<< "$(btn close)"
    python3 scripts/xclick.py "${NL_TEST_DISPLAY:-:97}" "${cx:-0}" "${cy:-0}" >/dev/null 2>&1; sleep 1
    after="$(ntabs)"
    if [ "$added" = "$((before + 1))" ] && [ "$after" = "$before" ]; then ok "sidebar buttons: + opens a tab, × closes it"
    else fail "sidebar buttons: tabs $before → + → $added → × → $after"; fi
    bash scripts/test-kitty.sh k focus-tab --match index:0 >/dev/null 2>&1; sleep 0.5
    if shot="$(bash scripts/test-kitty.sh shot check)" && cp "$shot" "${TMPDIR:-/tmp}/ninelives-check.png"; then
      ok "sidebar screenshot: ${TMPDIR:-/tmp}/ninelives-check.png"
    else fail "screenshot"; fi
    # a short window (after the screenshot: focusing tabs clears their ✓ and ● marks): the waiting
    # tab (7), the active one (11) and "+ New tab" must stay in view
    bash scripts/test-kitty.sh k focus-tab --match index:10 >/dev/null 2>&1
    bash scripts/test-kitty.sh k resize-os-window --width 1100 --height 420 --unit pixels >/dev/null 2>&1; sleep 1.5
    lay="$(cat "$NL_TEST_DIR/state/sidebar.txt" 2>/dev/null)"
    if grep -qE "^shown: .*\b7\b.*\b11 \+$" <<< "$lay" && grep -q "^hidden: [0-9]" <<< "$lay"; then
      ok "short window keeps the waiting tab, the active tab and + New tab ($(sed -n 2p <<< "$lay"))"
      read -r _ cx cy <<< "$(grep '^click: ' <<< "$lay")"      # where the "hidden: 1–2" line is
      python3 scripts/xclick.py "${NL_TEST_DISPLAY:-:97}" "${cx:-0}" "${cy:-0}" >/dev/null 2>&1; sleep 1
      act="$(bash scripts/test-kitty.sh k ls 2>/dev/null | python3 -c 'import json,sys; print([i+1 for i,t in enumerate(json.load(sys.stdin)[0]["tabs"]) if t["is_active"]])')"
      [ "$act" = "[1]" ] && ok "clicking the hidden line goes to the first hidden tab" || fail "hidden-line click at $cx,$cy: active tab $act"
    else fail "short window layout: $(tr '\n' ' ' <<< "$lay")"; fi
    # Ctrl+Shift+Space toggles: a second press in the same tab closes the box; a box left open in
    # another tab is closed, and the new one opens where you are
    boxes() { bash scripts/test-kitty.sh k ls 2>/dev/null | python3 -c 'import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("tf", "config/tab-finder.py"); tf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tf)
print(" ".join(str(i + 1) for i, t in enumerate(json.load(sys.stdin)[0]["tabs"]) for w in t["windows"]
               if any(tf._is_search_box(c) for c in [w.get("cmdline") or []] + [p.get("cmdline") or [] for p in w.get("foreground_processes") or []])))'; }
    search_key() { bash scripts/test-kitty.sh k action "$(sed -n 's/^map ctrl+shift+space *//p' config/kitty.conf)" >/dev/null 2>&1; sleep 1.2; }
    bash scripts/test-kitty.sh k focus-tab --match index:0 >/dev/null 2>&1; sleep 0.3
    search_key; b1="$(boxes)"; search_key; b2="$(boxes)"; search_key
    bash scripts/test-kitty.sh k focus-tab --match index:1 >/dev/null 2>&1; sleep 0.3
    search_key; b3="$(boxes)"; search_key; b4="$(boxes)"
    if [ "$b1" = 1 ] && [ -z "$b2" ] && [ "$b3" = 2 ] && [ -z "$b4" ]; then
      ok "the search key toggles its box, and a box left in another tab doesn't swallow it"
    else fail "search toggle: tabs with a box: '$b1' → '$b2'; from tab 2: '$b3' → '$b4'"; fi
    # A narrow window and a big font make kitty's sidebar narrower (a third of the window at
    # most): the search row must stay whole, sidebar.txt's button columns must be where kitty drew
    # ⚠, + and × (read back from the sidebar's cells), and clicking them must work
    sidebar_buttons() {  # LABEL: compare and click; prints nothing, ok/fail lines only
      local lay left top cw ch _cols b g x y col drawn bad="" t0 t1 t2 act
      lay="$(cat "$NL_TEST_DIR/state/sidebar.txt" 2>/dev/null)"
      read -r _ left top cw ch _cols <<< "$(grep '^cells: ' <<< "$lay")"
      for b in waiting:⚠ new:+ close:×; do
        g="${b#*:}"; b="${b%%:*}"
        read -r x y <<< "$(grep "^button $b: " <<< "$lay" | cut -d' ' -f3-)"
        drawn="$(grep "^drawn $g: " <<< "$lay" | cut -d' ' -f3)"
        col=$(( (${x:-0} - ${left:-0}) / ${cw:-1} ))
        [ -n "$x" ] && [ -n "$drawn" ] && [ "$col" = "$drawn" ] || bad="$bad $b(col ${col:-?}, $g drawn at ${drawn:-nowhere})"
      done
      if [ -n "$bad" ]; then fail "$1: sidebar.txt buttons don't match what kitty drew:$bad ($(tr '\n' ' ' <<< "$lay"))"; return; fi
      ok "$1: the search row is whole ($((_cols - 1)) cells) and sidebar.txt's ⚠, + and × are where kitty drew them"
      read -r x y <<< "$(grep '^button waiting: ' <<< "$lay" | cut -d' ' -f3-)"
      python3 scripts/xclick.py "${NL_TEST_DISPLAY:-:97}" "$x" "$y" >/dev/null 2>&1; sleep 1.2
      act="$(bash scripts/test-kitty.sh k ls 2>/dev/null | python3 -c 'import json,sys; print([i+1 for i,t in enumerate(json.load(sys.stdin)[0]["tabs"]) if t["is_active"]])')"
      bash scripts/test-kitty.sh k focus-tab --match index:0 >/dev/null 2>&1; sleep 0.8
      t0="$(ntabs)"; read -r x y <<< "$(btn new)"
      python3 scripts/xclick.py "${NL_TEST_DISPLAY:-:97}" "$x" "$y" >/dev/null 2>&1; sleep 1
      t1="$(ntabs)"; read -r x y <<< "$(btn close)"
      python3 scripts/xclick.py "${NL_TEST_DISPLAY:-:97}" "$x" "$y" >/dev/null 2>&1; sleep 1
      t2="$(ntabs)"
      if [ "$act" = "[7]" ] && [ "$t1" = "$((t0 + 1))" ] && [ "$t2" = "$t0" ]; then
        ok "$1: clicking ⚠ goes to the waiting tab, + opens a tab, × closes it"
      else fail "$1: ⚠ went to tab $act (want [7]); tabs $t0 → + → $t1 → × → $t2"; fi
      bash scripts/test-kitty.sh k focus-tab --match index:0 >/dev/null 2>&1; sleep 0.5
    }
    bash scripts/test-kitty.sh k resize-os-window --width 860 --height 760 --unit pixels >/dev/null 2>&1; sleep 1.5
    sidebar_buttons "860 px window"
    bash scripts/test-kitty.sh k resize-os-window --width 1100 --height 760 --unit pixels >/dev/null 2>&1
    bash scripts/test-kitty.sh k set-font-size 20 >/dev/null 2>&1; sleep 1.5
    sidebar_buttons "font size 20"
    bash scripts/test-kitty.sh k set-font-size 0 >/dev/null 2>&1; sleep 1
    # Last (it replaces the test kitty): kitty-relaunch.sh brings split tabs back. Tab 1 split
    # left | right with the right half split top / bottom (a Claude pane at the bottom, sizes not
    # even), the renamed tab 10 split top / bottom with the bottom split left | right, tab 11 split
    # and zoomed (Ctrl+Alt+Z). Compared by folder: names, layouts, split trees and sizes, panes,
    # the active pane and the active tab; tab 3's name has $ signs that must stay literal. Claude
    # and omp are stubs here (test-kitty.sh).
    k() { bash scripts/test-kitty.sh k "$@" 2>/dev/null; }
    wid() { k ls | python3 -c "import json,sys; print(json.load(sys.stdin)[0]['tabs'][$1]['windows'][0]['id'])"; }
    sp="$NL_TEST_DIR/code/split"; mkdir -p "$sp/a" "$sp/b" "$sp/c" "$sp/d" "$sp/e"
    w="$(wid 0)"; a="$(k launch --match "id:$w" --location=vsplit --cwd "$sp/a" bash --norc)"
    b="$(k launch --match "id:$a" --location=hsplit --cwd "$sp/b" bash --norc)"; sleep 0.3
    k send-text --match "id:$b" $'claude --resume abc-123\n'
    k resize-window --match "id:$w" --increment 8 --axis horizontal >/dev/null; k focus-window --match "id:$a"
    w="$(wid 9)"; c="$(k launch --match "id:$w" --location=hsplit --cwd "$sp/c" bash --norc)"
    k launch --match "id:$c" --location=vsplit --cwd "$sp/d" bash --norc >/dev/null; k focus-window --match "id:$w"
    w="$(wid 10)"; k launch --match "id:$w" --location=vsplit --cwd "$sp/e" bash --norc >/dev/null
    k focus-tab --match index:10; k action toggle_layout stack; k focus-tab --match index:9
    k set-tab-title --match "id:$(wid 2)" 'cost $HOME ${PATH} $$'; sleep 1    # kitty expands $ in a session
    # each tab without window ids: name, layout, splits tree by folder (axis, size), panes, active pane
    desc='import json, sys
out = []
for o in json.load(sys.stdin):
    for t in o["tabs"]:
        cwd = {w["id"]: w["cwd"] for w in t["windows"]}
        st = t.get("layout_state") or {}
        g2w = {g["id"]: g["window_ids"][0] for g in st.get("all_windows", {}).get("window_groups", [])}
        def norm(p):
            if isinstance(p, dict):
                return [p.get("horizontal", True), round(p.get("bias", 0.5), 2), norm(p["one"]), norm(p.get("two"))]
            return cwd.get(g2w.get(p, p)) if p is not None else None
        out.append([t["title"] if t.get("title_overridden") else "", t["layout"], norm(st.get("pairs")),
                    len(t["windows"]), next((w["cwd"] for w in t["windows"] if w["is_active"]), None), t["is_active"]])
print(json.dumps(out))'
    before="$(k ls | python3 -c "$desc")"
    if out="$(bash scripts/test-kitty.sh relaunch 2>&1)"; then
      sleep 1.5; after="$(k ls | python3 -c "$desc")"
      k focus-tab --match index:10; k action toggle_layout stack; sleep 0.5      # unzoom tab 11
      unzoomed="$(k ls | python3 -c 'import json,sys; t=json.load(sys.stdin)[0]["tabs"][10]; print(t["layout"], len(t["layout_state"].get("pairs", {})))')"
      resumed="$(grep -c "claude --resume abc-123" "$NL_TEST_DIR/agents.log" 2>/dev/null)"
      splits="$(python3 -c 'import json,sys; print(sum(1 for t in json.loads(sys.argv[1]) if t[3] > 1))' "$after")"
      if [ -n "$before" ] && [ "$before" = "$after" ] && [ "$splits" = 3 ] && [ "$unzoomed" = "splits 2" ] && [ "$resumed" = 2 ]; then
        ok "kitty-relaunch.sh brings back $splits split tabs (layout, sizes, folders, Claude pane, active pane, zoom)"
      else fail "relaunch with splits: unzoomed '$unzoomed', Claude resumed $resumed of 2; before $before; after $after"; fi
      # plain shells come back as `bash -lc 'exec bash'`, which sets no title: kitty calls them
      # "bash", and the sidebar (and the search box, same rule) must still name them by folder
      names="$(k ls | python3 -c 'import importlib.util, json, os, sys
spec = importlib.util.spec_from_file_location("tf", "config/tab-finder.py"); tf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tf)
data = json.load(sys.stdin); rows = tf.rows(data)
plain = [(r["name"], os.path.basename(next(w for w in t["windows"] if w["is_active"])["cwd"]))
         for r, t in zip(rows, data[0]["tabs"])
         if not t.get("title_overridden") and all(w["title"] == "bash" for w in t["windows"])]
print(len(plain), "ok" if plain and all(n == f for n, f in plain) else plain)')"
      if [ "${names#* }" = ok ]; then ok "restarted plain shells (titled \"bash\") are named by their folder (${names% *} tabs)"
      else fail "restarted plain shells' names: $names"; fi
      # the restart's own marker must not reach the new kitty (it did once: the next restart from a
      # tab then ran in the foreground and died with the old kitty)
      kpid="$(pgrep -f -- "[-]-listen-on unix:@ninelives-test-kitty" | head -1)"
      if [ -n "$kpid" ] && ! tr '\0' '\n' < "/proc/$kpid/environ" | grep -q "^_KR_DETACHED="; then
        ok "the restarted kitty doesn't inherit the restart's internals"
      else fail "the restarted kitty inherited _KR_DETACHED (pid ${kpid:-none})"; fi
    else fail "relaunch: $(tail -3 <<< "$out")"; fi
  else fail "test kitty did not start"; fi
fi

echo
if [ "$fails" = 0 ]; then echo "All checks passed."; else echo "$fails check(s) failed."; exit 1; fi
