"""cat_ctl.py: drive the sidebar's drawn cat inside a test kitty (check.sh, record.sh). A kitten,
run in kitty's own process over the TEST kitty's socket only:

    bash scripts/test-kitty.sh k kitten "$PWD/tests/cat_ctl.py" walk 120

Commands (tab_bar.py's _cat_ctl): walk X (px from the sidebar's left edge), visit (the tab waiting
for you), home, freeze / thaw (no dice, no wandering), day (no night nap), say (speak up about the
waiting tab now), pace N (walk to and fro N times), state. Prints the cat's state.
"""


def main(args):
    pass


def handle_result(args, answer, target_window_id, boss):
    import kitty.tab_bar as kt
    ctl = getattr(kt, "_vye_cat_ctl", None)
    if ctl is None:
        return "no cat here (tab_bar.py not loaded?)"
    return ctl(boss, list(args[1:]))


handle_result.no_ui = True
