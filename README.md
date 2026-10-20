# Girderdash

A fullscreen, offline barrel-dodging climbing platformer for Raspberry Pi and Linux terminals. A repair bot dashes up a half-built tower of girders to relight the sky-beacon at the top. The tower's grumpy caretaker machine wants a quiet night shift, so it rolls barrel after barrel down the structure. Run the girders, ride the ladders, jump the barrels for bonus points, and stand at the beacon to clear the tower. Every tower you clear rises taller and rolls faster.

Original name, characters, art, and code, in the spirit of classic barrel-climbing arcade platformers. This is an original terminal game: it shares no assets, names, or code with any commercial game and does not claim to be a port.

## Run

```
python3 girderdash.py
```

Python 3 with curses. No dependencies, no network, no install. Saves your best score to `~/.girderdash-best.json`. Needs a terminal at least 76x22.

## Controls

- **Arrows / WASD** - run, climb ladders (up/down at a ladder)
- **Space** - jump (clear a barrel for +10)
- **P** - pause
- **Q** - quit

## Rules

- Barrels roll along each girder, drop through the gap at the end, and cascade to the floor below. The pit at the bottom eats them.
- Touch a barrel (or fall in the pit) and you lose one of 3 lives. Clear a tower for 100 x level points.
- Falling through a gap just drops you to the girder below - unless it's the bottom one.
- Towers grow from 3 girders up to 7, with faster spawns every level.

## Tests

```
python3 -m unittest test_girderdash
```

32 tests cover the layout generator, walking, climbing, jump arcs, gap falls, barrel rolling/dropping/despawning, collisions, jump-over scoring, level clears, respawns, the render grid, and a real terminal (PTY) boot/move/quit run.

Built with AI assistance from my design.
