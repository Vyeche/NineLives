#!/usr/bin/env python3
"""Unit tests for config/cat-float.py (the floating cat, stage 3): the pure parts only (placement,
layout, dragging, the state file, the speech memory, sounds, mouse reports). No kitty, no display."""
import importlib.util
import os
import tempfile
import unittest
import unittest.mock

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("cat_float", os.path.join(HERE, "..", "config", "cat-float.py"))
cf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cf)


class Geometry(unittest.TestCase):
    def test_home_on_the_floor_above_the_dock(self):
        x, y = cf.home(1920, 1200)
        self.assertEqual(y, 1200 - cf.DOCK - cf.CAT_PX)
        self.assertLessEqual(x + cf.CAT_PX, 1920)

    def test_clamp_keeps_it_on_screen(self):
        self.assertEqual(cf.clamp(-180444, 5000, 128, 128, 1920, 1200), (0, 1072))

    def test_restore(self):
        self.assertEqual(cf.restore({}, 1920, 1200), cf.home(1920, 1200))
        self.assertEqual(cf.restore({"x": 300, "y": 10, "floor": True}, 1920, 1200), (300, cf.floor_y(1200)))
        self.assertEqual(cf.restore({"x": 5000, "y": 50}, 1920, 1200), (1920 - 128, 50))

    def test_layout_cat_stays_put_and_bubble_on_the_side_with_room(self):
        cat = cf.home(1920, 1200)
        lay = cf.layout(cat, (300, 120), (9, 18), (1920, 1200))
        self.assertEqual(lay["side"], "left")
        mx, my = lay["margin"]
        self.assertEqual((mx + lay["cat"][0], my + lay["cat"][1]), cat)
        self.assertGreaterEqual(lay["cols"] * 9, 300)
        right = cf.layout((10, 900), (300, 120), (9, 18), (1920, 1200))
        self.assertEqual(right["side"], "right")
        alone = cf.layout(cat, None, (9, 18), (1920, 1200))
        self.assertEqual((alone["cols"], alone["rows"], alone["margin"]), (15, 8, cat))

    def test_cell_pos_and_drag(self):
        self.assertEqual(cf.cell_pos(100, 40, 9, 18), (11, 2, 1, 4))
        self.assertEqual(cf.drag_to((500, 600), (20, 30), (25, 10)), (505, 580))

    def test_walk_target_in_range(self):
        import random
        rng = random.Random(1)
        for _ in range(50):
            t = cf.walk_target(1700, 1920, 128, rng)
            self.assertTrue(0 <= t <= 1792 and abs(t - 1700) <= cf.WALK_MOST)


class Memory(unittest.TestCase):
    def test_fresh_and_remember(self):
        tip = {"kind": "tip", "key": "tip:abc", "text": "x"}
        said = cf.remember({}, tip, 1000.0)
        self.assertEqual(cf.fresh([tip], said, 1000.0 + 60), [])
        self.assertEqual(cf.fresh([tip], said, 1000.0 + 86400), [tip])

    def test_state_file_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s", "cat-float.json")
            cf.save_json(p, {"x": 1, "y": 2})
            self.assertEqual(cf.load_json(p), {"x": 1, "y": 2})
            self.assertEqual(cf.load_json(os.path.join(d, "none.json")), {})


class Sounds(unittest.TestCase):
    def test_switches(self):
        with tempfile.TemporaryDirectory() as conf:
            os.makedirs(os.path.join(conf, "sounds"))
            open(os.path.join(conf, "sounds", "meow.oga"), "w").close()
            self.assertEqual(cf.sound_argv("meow", conf, {})[:2], ["paplay", "--volume=40000"])
            self.assertIsNone(cf.sound_argv("meow", conf, {}, demo=True))
            self.assertIsNone(cf.sound_argv("meow", conf, {"NINELIVES_QUIET": "1"}))
            with open(os.path.join(conf, "sounds-volume"), "w") as f:
                f.write("50")
            self.assertEqual(cf.sound_argv("meow", conf, {})[1], "--volume=20000")
            for off in ("sounds-off", "cat-sounds-off", "sounds-classic"):
                open(os.path.join(conf, off), "w").close()
                self.assertIsNone(cf.sound_argv("meow", conf, {}))
                os.unlink(os.path.join(conf, off))


class Input(unittest.TestCase):
    def test_mouse_reports(self):
        evs = cf.mouse_events("\x1b[<0;10;20M\x1b[<32;15;22M\x1b[<0;15;22m\x1b[<35;1;2M\x1b[I")
        self.assertEqual([e[0] for e in evs], ["press", "drag", "release", "move", "focus"])
        self.assertEqual(cf.hit([(0, 0, 10, 10, "cat")], 5, 5), "cat")
        self.assertIsNone(cf.hit([(0, 0, 10, 10, "cat")], 15, 5))


class Pictures(unittest.TestCase):
    def test_clearing_the_cells_keeps_the_pictures(self):
        # ESC[2J would free every picture with no placement (kitty's grman_clear): the frames sent
        # once at the start, so the cat (and a new bubble) would vanish after the first move
        import io
        import types
        with tempfile.TemporaryDirectory() as d, unittest.mock.patch.dict(
                os.environ, {"NINELIVES_STATE": d, "KITTY_CONFIG_DIRECTORY": d}):
            out = io.StringIO()
            cat = cf.FloatCat(types.SimpleNamespace(demo=0, seed=1, main_socket="", cells=True, theme="dark"), out)
            cat.cw, cat.chh, cat.out_wh, cat.cat_xy = 9, 18, (1920, 1200), [100, 900]
            cat.set_panel = lambda lay, force=False: None
            cat.lay = cf.layout(cat.cat_xy, None, (9, 18), cat.out_wh)
            cf.FRAME_IDS.setdefault("idle", 1)
            cat.place_all()
            cat.open_bubble([{"kind": "tip", "key": "tip:x", "title": "Tip", "text": "hi", "action": None}])
            cat.place_all()
        sent = out.getvalue()
        self.assertIn("a=p,i=1", sent)                              # the cat was placed
        for erase in ("\x1b[2J", "\x1b[3J", "\x1b[22J", "a=d,d=A", "a=d,d=a"):
            self.assertNotIn(erase, sent)


class Launcher(unittest.TestCase):
    def test_refuses_outside_the_real_desktop(self):
        self.assertTrue(cf.refuse_reason({}))
        self.assertTrue(cf.refuse_reason({"WAYLAND_DISPLAY": "w", "NINELIVES_QUIET": "1"}))
        self.assertTrue(cf.refuse_reason({"WAYLAND_DISPLAY": "w", "NL_TEST_DIR": "/t"}))
        self.assertEqual(cf.refuse_reason({"WAYLAND_DISPLAY": "w"}), "")

    def test_panel_never_takes_focus(self):
        argv = cf.panel_argv("/run/x.sock", ["true"])
        self.assertIn("--focus-policy=not-allowed", argv)
        self.assertIn("background_opacity=0", argv)

    def test_theme_contrast(self):
        for t in cf.THEMES.values():
            self.assertGreaterEqual(cf.contrast(t["text"], t["fill"]), 4.5)
            self.assertGreaterEqual(cf.contrast(t["border"], t["fill"]), 3.0)
            for k in t["kinds"].values():
                self.assertGreaterEqual(cf.contrast(k, t["fill"]), 4.5)
            for fill, fg in (t["do"], t["next"]):
                self.assertGreaterEqual(cf.contrast(fg, fill), 4.5)


if __name__ == "__main__":
    unittest.main()
