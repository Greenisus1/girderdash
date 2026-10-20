import json, os, pty, select, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, '/tmp/girderdash-pkg')
import girderdash as g

def fresh(level=1, seed=7):
    return g.World(level, seed=seed)

class LayoutTests(unittest.TestCase):
    def test_floors_and_dirs(self):
        w = fresh()
        self.assertEqual(w.floors, 3)
        self.assertEqual(w.dirs, [1, -1, 1])
    def test_floors_grow_with_level(self):
        self.assertEqual(g.World(5, seed=1).floors, 7)
    def test_ladder_per_gap_clear_of_gaps(self):
        for lvl in (1, 2, 3, 4, 5):
            w = g.World(lvl, seed=3)
            self.assertEqual(len(w.ladders), w.floors - 1)
            for x, i in w.ladders:
                self.assertNotIn(x, w._gap_cells(i))
                self.assertNotIn(x, w._gap_cells(i + 1))
    def test_goal_on_top_floor_inside_span(self):
        w = fresh()
        self.assertGreater(w.goal_x, g.X0); self.assertLess(w.goal_x, g.X1)
        self.assertNotIn(w.goal_x, w._gap_cells(w.floors - 1))

class PlayerTests(unittest.TestCase):
    def test_walk_clamps_at_ends(self):
        w = fresh(); w.px = g.X0
        w.step({"left"}); self.assertEqual(w.px, g.X0)
        w.px = g.X1
        w.step({"right"}); self.assertEqual(w.px, g.X1)
    def test_walk_moves(self):
        w = fresh(); x = w.px
        w.step({"right"}); self.assertEqual(w.px, x + 1)
        w.step({"left"}); self.assertEqual(w.px, x)
    def test_climb_up_changes_floor(self):
        w = fresh()
        x, i = w.ladders[0]
        w.px, w.pf = x, i
        w.step({"up"})
        self.assertEqual(w.pstate, "climb")
        for _ in range(5): w.step({"up"})
        self.assertEqual(w.pf, i + 1); self.assertEqual(w.pstate, "walk")
    def test_climb_down(self):
        w = fresh()
        x, i = w.ladders[0]
        w.px, w.pf = x, i + 1
        w.step({"down"})
        self.assertEqual(w.pstate, "climb")
        for _ in range(5): w.step({"down"})
        self.assertEqual(w.pf, i)
    def test_no_climb_without_ladder(self):
        w = fresh()
        w.px = (g.X0 + g.X1) // 2
        if w.ladder_here(w.px, 0) is None:
            w.step({"up"})
            self.assertEqual(w.pstate, "walk")
    def test_jump_arc_and_land(self):
        w = fresh()
        w.step({"jump"})
        self.assertEqual(w.pstate, "jump")
        seen = set()
        for _ in range(len(g.ARC)):
            seen.add(w.ph); w.step(set())
        self.assertEqual(w.pstate, "walk"); self.assertEqual(w.ph, 0)
        self.assertIn(max(g.ARC), seen)
    def test_jump_moves_horizontally(self):
        w = fresh(); x = w.px
        w.step({"jump", "right"}); w.step({"right"})
        self.assertGreater(w.px, x)

class GapTests(unittest.TestCase):
    def test_player_falls_through_gap_to_lower_floor(self):
        w = fresh()
        w.pf = 1
        w.px = min(w._gap_cells(1))
        w.step(set())
        self.assertEqual(w.pf, 0)
        self.assertEqual(w.state, "play")
    def test_pit_on_bottom_gap_kills(self):
        w = fresh()
        w.pf = 0
        w.px = min(w._gap_cells(0))
        w.step(set())
        self.assertEqual(w.state, "dead")
        self.assertIn("die:pit", w.events)
        self.assertEqual(w.lives, 2)

class BarrelTests(unittest.TestCase):
    def test_spawner_makes_barrel_on_top(self):
        w = fresh()
        for _ in range(10): w.step(set())
        self.assertTrue(w.barrels)
        self.assertEqual(w.barrels[0][1], w.floors - 1)
    def test_barrel_rolls_with_floor_dir(self):
        w = fresh()
        for _ in range(10): w.step(set())
        b = w.barrels[0]; x = b[0]
        w.step(set()); w.step(set())
        self.assertEqual(w.barrels[0][0], x + w.dirs[b[1]])
    def test_barrel_drops_at_gap_and_flips_floor(self):
        w = fresh()
        top = w.floors - 1
        gap_end = max(w._gap_cells(top)) if w.dirs[top] == 1 else min(w._gap_cells(top))
        w.barrels = [[gap_end - w.dirs[top], top]]
        w._prev_barrel_x[id(w.barrels[0])] = gap_end - 2 * w.dirs[top]
        for _ in range(4): w.step(set())
        self.assertEqual(w.barrels[0][1], top - 1)
    def test_barrel_despawns_in_pit(self):
        w = fresh()
        w.barrels = [[max(w._gap_cells(0)) - 1, 0]]
        w._prev_barrel_x[id(w.barrels[0])] = max(w._gap_cells(0)) - 2
        for _ in range(4): w.step(set())
        self.assertFalse(w.barrels)
    def test_collision_kills(self):
        w = fresh()
        w.barrels = [[w.px - 1, 0]]
        w._prev_barrel_x[id(w.barrels[0])] = w.px - 2
        w.step(set()); w.step(set())
        self.assertEqual(w.state, "dead")
        self.assertIn("die:barrel", w.events)
    def test_jump_over_barrel_scores_and_survives(self):
        w = fresh()
        w.barrels = [[w.px - 1, 0]]
        w._prev_barrel_x[id(w.barrels[0])] = w.px - 1
        seen = []
        seen += w.step({"jump"})          # airborne as barrel crosses under
        seen += w.step(set()); seen += w.step(set())
        self.assertEqual(w.state, "play")
        self.assertIn("jumped", seen)
        self.assertEqual(w.score, g.JUMP_SCORE)
    def test_climbing_is_safe(self):
        w = fresh()
        x, i = w.ladders[0]
        w.px, w.pf = x, i
        w.step({"up"})
        w.barrels = [[x, i + 1]]
        w._prev_barrel_x[id(w.barrels[0])] = x
        w.step(set()); w.step(set())
        self.assertEqual(w.state, "play")

class OutcomeTests(unittest.TestCase):
    def test_goal_clears_level(self):
        w = fresh()
        w.pf = w.floors - 1
        w.px = w.goal_x
        w.step(set())
        self.assertEqual(w.state, "clear")
        self.assertIn("clear", w.events)
        self.assertEqual(w.score, g.BEACON_SCORE)
    def test_next_level_keeps_score_and_lives(self):
        w = fresh(); w.score = 50; w.lives = 2; w.state = "clear"
        n = w.next_level()
        self.assertEqual(n.level, 2); self.assertEqual(n.score, 50); self.assertEqual(n.lives, 2)
    def test_gameover_after_lives_gone(self):
        w = fresh(); w.lives = 0
        w._die("barrel")
        for _ in range(10): w.step(set())
        self.assertEqual(w.state, "gameover")
    def test_respawn_after_death(self):
        w = fresh()
        w._die("barrel")
        for _ in range(10): w.step(set())
        self.assertEqual(w.state, "play")
        self.assertEqual((w.px, w.pf), (g.X0 + 2, 0))
        self.assertFalse(w.barrels)
    def test_record(self):
        with tempfile.TemporaryDirectory() as d, patch.object(g, "RECORD", str(Path(d) / "b.json")):
            self.assertTrue(g.save(7)); g.save(2); self.assertEqual(g.best(), 7)

class RenderTests(unittest.TestCase):
    def test_grid_shape(self):
        ch, co = g.render(fresh(), 80, 26)
        self.assertEqual(len(ch), 26)
        for r in ch: self.assertEqual(len(r), 80)
    def test_floors_drawn_with_gap(self):
        w = fresh()
        ch, co = g.render(w, 80, 26)
        ox = (80 - g.WW) // 2; y = 26 - 3  # ground_y = H-3
        row = "".join(ch[y])
        self.assertIn("█", row)
        gaps = w._gap_cells(0)
        for x in gaps: self.assertEqual(ch[y][ox + x], " ")
    def test_player_barrel_goal_drawn(self):
        w = fresh()
        for _ in range(10): w.step(set())
        ch, co = g.render(w, 80, 26)
        flat = [c for row in ch for c in row]
        for sym in ("◆", "●", "⚑", "♦", "║"):
            self.assertIn(sym, flat)
    def test_hud_text(self):
        ch, co = g.render(fresh(), 80, 26)
        top = "".join(ch[0])
        self.assertIn("GIRDERDASH", top)
        self.assertIn("LEVEL 1", top)
    def test_clear_overlay(self):
        w = fresh(); w.state = "clear"
        ch, co = g.render(w, 80, 26)
        self.assertIn("BEACON LIT", "\n".join("".join(r) for r in ch))

class PtyTests(unittest.TestCase):
    def spawn(self, env_extra=None):
        master, slave = pty.openpty()
        env = dict(os.environ, TERM="xterm-256color", LINES="30", COLUMNS="90",
                   GIRDERDASH_SEED="7")
        if env_extra: env.update(env_extra)
        p = subprocess.Popen([sys.executable, "/tmp/girderdash-pkg/girderdash.py"],
                             stdin=slave, stdout=slave, stderr=slave, env=env, close_fds=True)
        os.close(slave)
        return p, master, bytearray()

    def drain(self, master, buf, until, timeout=8.0):
        end = time.time() + timeout
        while time.time() < end:
            r, _, _ = select.select([master], [], [], 0.1)
            if r:
                try: buf.extend(os.read(master, 65536))
                except OSError: break
                if until and until in bytes(buf): return True
        return bool(until and until in bytes(buf))

    def test_boots_and_quits(self):
        p, m, buf = self.spawn()
        try:
            self.assertTrue(self.drain(m, buf, b"GIRDERDASH"), bytes(buf)[-400:])
            self.assertTrue(self.drain(m, buf, b"LEVEL"))
            self.assertTrue(self.drain(m, buf, b"SCORE"))
            os.write(m, b"q")
            p.wait(timeout=5)
            self.assertEqual(p.returncode, 0)
        finally:
            if p.poll() is None: p.kill()
            os.close(m)

    def test_moves_and_pauses(self):
        p, m, buf = self.spawn()
        try:
            self.assertTrue(self.drain(m, buf, b"GIRDERDASH"))
            os.write(m, b"d" * 5 + b"w" + b"p" + b"p")
            time.sleep(1.0)
            self.drain(m, buf, None, 1.0)
            os.write(m, b"q")
            p.wait(timeout=5)
            self.assertEqual(p.returncode, 0)
        finally:
            if p.poll() is None: p.kill()
            os.close(m)

if __name__ == "__main__":
    unittest.main()
