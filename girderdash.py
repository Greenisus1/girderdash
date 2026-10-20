#!/usr/bin/env python3
"""girderdash - an original barrel-dodging climbing platformer for the terminal.

A repair bot dashes up a half-built tower of girders to relight the sky-beacon
at the top. The tower's grumpy caretaker machine wants the night shift quiet,
so it rolls barrel after barrel down the structure. Run the girders, climb the
ladders, jump the barrels, and reach the beacon. Each tower you clear rises
taller and faster than the last.

An original game: original name, characters, art and code.
Built with AI assistance from my design.
MIT License - Copyright (c) 2026 Greenisus1
"""
import curses, json, os, random, time

VERSION = "1.0.0"
RECORD = os.path.expanduser("~/.girderdash-best.json")

# ---------- world constants ----------
WW = 72                 # logical world width in cells
GAP = 4                 # rows between floors
X0, X1 = 6, WW - 7      # girder span (inclusive)
GAPW = 2                # drop-gap width at each girder's roll end
ARC = [1, 2, 2, 1]      # jump height per jump tick
MAX_WRONG = None        # (unused, kept for symmetry with siblings)
BARREL_EVERY = 2        # barrels advance every N ticks
JUMP_SCORE = 10
BEACON_SCORE = 100

# color ids (shared by render grid and curses paint)
C_FLOOR, C_LADDER, C_PLAYER, C_BARREL, C_GOAL, C_TEXT, C_ACCENT, C_DIM, C_BOT = range(1, 10)

try:
    import pi18n
except ImportError:
    pi18n = None

# English UI strings; the Translations app owns every language via ~/pi-translations.
DEFAULT_STRINGS = {
    "TITLE": "GIRDERDASH",
    "HUD": "LEVEL {level}  LIVES {lives}  SCORE {score}  BEST {best}",
    "CONTROLS": "arrows/wasd move · space jump · p pause · q quit",
    "OUCH": " OUCH! ",
    "CLEAR": " BEACON LIT! TOWER CLEAR ",
    "CLEAR_SUB": " enter: next tower · q: quit ",
    "OVER": " TOWER WINS ",
    "OVER_SUB": " score {score} · enter: retry · q: quit ",
    "TOO_SMALL": "girderdash needs a terminal at least {w}x{h} (yours is {ww}x{hh}).",
}

# ---------- mechanics (pure, unit-testable) ----------

class World:
    def __init__(self, level=1, seed=None, lives=3, score=0):
        self.level = level
        self.rng = random.Random(seed if seed is not None else level * 7919)
        self.floors = 3 + min(level - 1, 4)              # 3..7 girders
        self.dirs = [1 if i % 2 == 0 else -1 for i in range(self.floors)]
        self.ladders = self._place_ladders()
        self.tick_n = 0
        self.lives = lives
        self.score = score
        self.best_level = level
        self.barrels = []
        self.spawn_in = 6
        self.state = "play"          # play | dead | gameover | clear
        self.dead_ticks = 0
        self.events = []
        # player
        self.px = X0 + 2
        self.pf = 0                  # floor index
        self.ph = 0                  # height above floor (jump)
        self.pstate = "walk"         # walk | jump | climb
        self._jumped_ids = set()
        self.jt = 0
        self.cf = 0                  # climb: lower floor index
        self.ct = 0.0                # climb progress 0..1
        self.cdir = 1
        self.goal_x = self._goal_x()
        self.bot_x = X1 - 2 if self.dirs[-1] == -1 else X0 + 2  # caretaker spot, top floor, spawn end
        self._prev_barrel_x = {}

    # --- layout ---
    def _goal_x(self):
        return (X1 - GAPW - 1) if self.dirs[-1] == 1 else (X0 + GAPW + 1)

    def _gap_cells(self, f):
        """x cells of floor f's drop gap (at the roll-direction end)."""
        if self.dirs[f] == 1:
            return set(range(X1 - GAPW + 1, X1 + 1))
        return set(range(X0, X0 + GAPW))

    def _place_ladders(self):
        """One ladder per floor gap; alternating thirds, clear of drop gaps."""
        ladders = []
        for i in range(self.floors - 1):
            lo = min(self._gap_cells(i) | self._gap_cells(i + 1))
            hi = max(self._gap_cells(i) | self._gap_cells(i + 1))
            cand = list(range(X0 + GAPW + 2, X1 - GAPW - 1))
            third = cand[len(cand) // 3] if i % 2 == 0 else cand[2 * len(cand) // 3]
            jitter = self.rng.randint(-2, 2)
            x = max(X0 + GAPW + 2, min(X1 - GAPW - 2, third + jitter))
            ladders.append((x, i))   # connects floor i to i+1
        return ladders

    def ladder_here(self, x, f):
        """Ladder index if a ladder serves (x, f) from below, else None."""
        for x_, i in self.ladders:
            if i == f and abs(x_ - x) <= 0:
                return x_
        return None

    def ladder_above(self, x, f):
        """Ladder x if climbing down from floor f is possible (ladder to f-1)."""
        for x_, i in self.ladders:
            if i == f - 1 and x_ == x:
                return x_
        return None

    # --- player ---
    def step(self, actions):
        """Advance one tick. actions: subset of {'left','right','up','down','jump'}."""
        self.events = []
        self.tick_n += 1
        if self.state in ("gameover", "clear"):
            return self.events
        if self.state == "dead":
            self.dead_ticks += 1
            if self.dead_ticks >= 8:
                if self.lives < 0:
                    self.state = "gameover"
                else:
                    self._respawn()
            return self.events

        self._step_player(actions)
        if self.tick_n % BARREL_EVERY == 0:
            self._step_barrels()
        self._step_spawner()
        self._collide()
        self._goal()
        return self.events

    def _step_player(self, a):
        if self.pstate == "walk":
            if "jump" in a:
                self.pstate, self.jt = "jump", 0
                self._jumped_ids = set()
            elif "up" in a and self.ladder_here(self.px, self.pf) is not None and self.pf < self.floors - 1:
                self.pstate, self.cf, self.ct, self.cdir = "climb", self.pf, 0.0, 1
            elif "down" in a and self.pf > 0 and self.ladder_above(self.px, self.pf) is not None:
                self.pstate, self.cf, self.ct, self.cdir = "climb", self.pf - 1, 1.0, -1
            if self.pstate == "walk":
                if "left" in a: self.px = max(X0, self.px - 1)
                if "right" in a: self.px = min(X1, self.px + 1)
                if self.px in self._gap_cells(self.pf):
                    self._fall_through()
        elif self.pstate == "jump":
            self.jt += 1
            self.ph = ARC[min(self.jt, len(ARC) - 1)]
            if "left" in a: self.px = max(X0, self.px - 1)
            if "right" in a: self.px = min(X1, self.px + 1)
            if self.jt >= len(ARC):
                self.pstate, self.ph = "walk", 0
                if self.px in self._gap_cells(self.pf):
                    self._fall_through()
        elif self.pstate == "climb":
            if "up" in a: self.ct += 0.25
            elif "down" in a: self.ct -= 0.25
            if self.ct >= 1.0:
                self.pf, self.pstate, self.ph = self.cf + 1, "walk", 0
                self.events.append("floor_up")
            elif self.ct <= 0.0:
                self.pf, self.pstate, self.ph = self.cf, "walk", 0

    def _fall_through(self):
        if self.pf == 0:
            self._die("pit")
        else:
            self.pf -= 1
            self.pstate, self.ph = "walk", 0
            if self.px in self._gap_cells(self.pf):
                self._fall_through()

    # --- barrels ---
    def _step_spawner(self):
        self.spawn_in -= 1
        if self.spawn_in <= 0 and len(self.barrels) < 3 + self.level:
            f = self.floors - 1
            x = (X0 + 2) if self.dirs[f] == 1 else (X1 - 2)
            self.barrels.append([x, f])
            self._prev_barrel_x[id(self.barrels[-1])] = x
            self.spawn_in = max(14, 42 - 5 * self.level)

    def _step_barrels(self):
        for b in list(self.barrels):
            f = b[1]
            prev = b[0]
            self._prev_barrel_x[id(b)] = prev
            b[0] += self.dirs[f]
            if b[0] in self._gap_cells(f) or b[0] < X0 or b[0] > X1:
                if f == 0:
                    self.barrels.remove(b)      # pit
                    continue
                b[1] -= 1
                b[0] = min(X1 - GAPW - 1, max(X0 + GAPW + 1, b[0]))  # land inside lower span
                self._prev_barrel_x[id(b)] = b[0]

    # --- outcomes ---
    def _collide(self):
        if self.pstate == "climb" or self.state != "play":
            return
        for b in list(self.barrels):
            if b[1] != self.pf:
                continue
            if self.pstate == "jump" and self.ph > 0:
                prev = self._prev_barrel_x.get(id(b), b[0])
                lo, hi = sorted((prev, b[0]))
                if lo <= self.px <= hi and id(b) not in self._jumped_ids:
                    self._jumped_ids.add(id(b))
                    self.score += JUMP_SCORE
                    self.events.append("jumped")
                continue
            if b[0] == self.px:
                self._die("barrel")
                return

    def _goal(self):
        if self.pstate == "walk" and self.pf == self.floors - 1 and self.px == self.goal_x:
            self.score += BEACON_SCORE * self.level
            self.state = "clear"
            self.events.append("clear")

    def _die(self, why):
        self.lives -= 1
        self.state = "dead"
        self.dead_ticks = 0
        self.events.append("die:" + why)

    def _respawn(self):
        self.px, self.pf, self.ph = X0 + 2, 0, 0
        self.pstate = "walk"
        self.barrels = []
        self._prev_barrel_x = {}
        self.spawn_in = 8
        self.state = "play"

    def next_level(self):
        nl = World(self.level + 1, seed=self.rng.randint(0, 10**6),
                   lives=max(self.lives, 0) if self.lives >= 0 else 0, score=self.score)
        nl.lives = self.lives
        return nl

# ---------- record ----------
def save(score):
    try:
        b = best()
        if score > b:
            with open(RECORD, "w") as fh: json.dump({"best": score}, fh)
        return True
    except Exception:
        return False

def best():
    try:
        with open(RECORD) as fh: return int(json.load(fh).get("best", 0))
    except Exception:
        return 0

# ---------- render (pure grid) ----------
def render(w, W, H, S=None):
    """Return (chars, colors) HxW grids for the current world state."""
    S = S or DEFAULT_STRINGS
    ch = [[" "] * W for _ in range(H)]
    co = [[0] * W for _ in range(H)]
    def put(x, y, c, k):
        if 0 <= x < W and 0 <= y < H:
            ch[y][x] = c; co[y][x] = k
    def text(x, y, s, k):
        for i, c in enumerate(s): put(x + i, y, c, k)

    ox = (W - WW) // 2
    ground_y = H - 3
    def fy(f): return ground_y - f * GAP

    # girders + gaps
    for f in range(w.floors):
        gaps = w._gap_cells(f)
        for x in range(X0, X1 + 1):
            if x not in gaps: put(ox + x, fy(f), "█", C_FLOOR)
    # ladders
    for x, i in w.ladders:
        for y in range(fy(i + 1), fy(i)):
            put(ox + x, y, "║", C_LADDER)
    # beacon goal on top floor
    put(ox + w.goal_x, fy(w.floors - 1) - 1, "⚑", C_GOAL)
    # caretaker bot on top floor at spawn end
    put(ox + w.bot_x, fy(w.floors - 1) - 1, "♦", C_BOT)
    # barrels
    for bx, bf in w.barrels:
        put(ox + bx, fy(bf) - 1, "●", C_BARREL)
    # player
    if w.pstate == "climb":
        y = fy(w.cf) - round(w.ct * GAP)
    else:
        y = fy(w.pf) - 1 - w.ph
    pc = "◆" if w.state != "dead" else "✕"
    put(ox + w.px, y, pc, C_PLAYER)

    # HUD
    text(1, 0, S["TITLE"], C_ACCENT)
    text(14, 0, S["HUD"].format(level=w.level, lives=max(w.lives, 0), score=w.score, best=max(best(), w.score)), C_TEXT)
    text(1, H - 1, S["CONTROLS"], C_DIM)
    if w.state == "dead":
        text(W // 2 - 7, H // 2, S["OUCH"], C_BARREL)
    elif w.state == "clear":
        text(W // 2 - 12, H // 2, S["CLEAR"], C_GOAL)
        text(W // 2 - 13, H // 2 + 1, S["CLEAR_SUB"], C_TEXT)
    elif w.state == "gameover":
        text(W // 2 - 9, H // 2, S["OVER"], C_BARREL)
        text(W // 2 - 15, H // 2 + 1, S["OVER_SUB"].format(score=w.score), C_TEXT)
    return ch, co

# ---------- curses front end ----------
def paint(stdscr, w, S=None):
    H, W = stdscr.getmaxyx()
    ch, co = render(w, W, H, S)
    for y in range(H):
        for x in range(W - 1):
            c, k = ch[y][x], co[y][x]
            try:
                if c != " ":
                    stdscr.addstr(y, x, c, curses.color_pair(k))
                else:
                    stdscr.addstr(y, x, " ")
            except curses.error:
                pass
    stdscr.refresh()

def init_colors():
    curses.start_color()
    curses.use_default_colors()
    pairs = [(C_FLOOR, curses.COLOR_BLUE), (C_LADDER, curses.COLOR_YELLOW),
             (C_PLAYER, curses.COLOR_CYAN), (C_BARREL, curses.COLOR_RED),
             (C_GOAL, curses.COLOR_GREEN), (C_TEXT, curses.COLOR_WHITE),
             (C_ACCENT, curses.COLOR_MAGENTA), (C_DIM, 8 if curses.COLORS > 8 else curses.COLOR_WHITE),
             (C_BOT, curses.COLOR_MAGENTA)]
    for i, fg in pairs:
        curses.init_pair(i, fg, -1)

KEYMAP = {curses.KEY_LEFT: "left", ord("a"): "left", curses.KEY_RIGHT: "right", ord("d"): "right",
          curses.KEY_UP: "up", ord("w"): "up", curses.KEY_DOWN: "down", ord("s"): "down",
          ord(" "): "jump"}

def run(stdscr):
    S = pi18n.load("girderdash", DEFAULT_STRINGS) if pi18n else DEFAULT_STRINGS
    H, W = stdscr.getmaxyx()
    if W < WW + 4 or H < 22:
        stdscr.addstr(0, 0, S["TOO_SMALL"].format(w=WW + 4, h=22, ww=W, hh=H))
        stdscr.refresh(); stdscr.getch(); return
    init_colors()
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.keypad(True)
    seed = os.environ.get("GIRDERDASH_SEED")
    seed = int(seed) if seed else None
    w = World(1, seed=seed)
    paused = False
    while True:
        actions = set()
        jump_edge = False
        while True:
            k = stdscr.getch()
            if k == -1: break
            if k in (ord("q"), ord("Q")):
                save(w.score); return
            if k in (ord("p"), ord("P")):
                paused = not paused; continue
            if w.state in ("clear", "gameover") and k in (10, 13, curses.KEY_ENTER, ord(" ")):
                if w.state == "clear":
                    w = w.next_level()
                else:
                    save(w.score); w = World(1, seed=None)
                continue
            a = KEYMAP.get(k)
            if a:
                if a == "jump": jump_edge = True
                else: actions.add(a)
        if jump_edge: actions.add("jump")
        if not paused and w.state not in ("clear", "gameover"):
            w.step(actions)
        paint(stdscr, w, S)
        time.sleep(0.06)

def main():
    curses.wrapper(run)

if __name__ == "__main__":
    main()
