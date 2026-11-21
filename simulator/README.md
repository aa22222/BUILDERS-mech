# Approximate local simulator

Run from the kit root (Python standard library only):

```powershell
python simulator/simulate.py --seed 1 --bots 16 --seconds 120 --out simulator/results/match-seed1
python simulator/simulate.py --scenario rooftop --bots 1 --seconds 480 --out simulator/results/rooftop
python simulator/simulate.py --scenario pursuit --bots 2 --seconds 120 --out simulator/results/pursuit
python -m unittest discover -s simulator -p "test_*.py"
```

The default bot is `python/avoid_bot.py` in the kit, or `avoid_bot.py` in the flattened submission repository. Use `--bot simulator/baseline_bot.py` to run the frozen original bot. A bot must expose `Bot(hello)` and `act(observation)` and guard its protocol loop with `if __name__ == '__main__'`. Each run loads fresh state. Reusing an output directory overwrites its previous trace and summary.

Outputs:

- `summary.json`: death coordinates and time, damage by weapon, time outside the zone, idle decisions, exceptions and measured decisions over 50 ms.
- `trace.jsonl`: snapshots every match-second and at death, including all actor positions/HP, zone, bot action, damage events and cumulative damage. A trace is diagnostic data, not an official replay format. Events between snapshots are included in damage totals but not all are retained individually.

Implemented approximations: actual map terrain and building polygons, roof/bridge support, cylinder clearance samples, axis sliding, acceleration, falling, energy expenditure/recovery, torso turning, field of view and five-second tracking, health regeneration, zone phases with seeded nested centers, and simple scanning/chasing opponents that fight each other as well as the bot. Rooftop and pursuit scenarios deliberately arrange diagnostic starting positions. Random spawns use a 65 m separation (not the official default 130 m).

Combat uses instant 55%-chance gun hits at configured damage/range/cooldown. It does not simulate bullets, ammo, reloads, rear armor, weapon loot, cubes, upgrades, NPC drones, sounds, trees, jumps/jets, mech-to-mech collision, or accurate opponent tactics. Geometry and sight use sampled approximations and reuse the bot's map-query helpers, so this is not independent validation of those helpers. The subject bot's firing is ignored: this harness is for the current passive bot. Late decisions are measured but still applied; timing and subprocess transport are validated separately with the official conformance checker. Alive-at-timeout results are unfinished simulations, not official placements. A single-actor test's `place: 1` is not a victory.

Do not interpret these outcomes as predicted competition scores or evidence about an actual submitted match. Use them to reproduce navigation failures and compare behavior under identical seeds.

Initial findings with the submitted bot:

- Rooftop scenario, seed 1: stationary for 205.3 seconds, then dies to zone damage at approximately (-37.4, -291.64, 24.27).
- Random 16-actor scenario, seed 1: dies to gun damage at 14.7 seconds near (509.53, -326.05, -1.28), close to the southeast map edge; simulated placement 14. This illustrates exposure near the boundary, not a verified competition death.


## Regression and comparison tools

The simulator now uses a frozen copy of the original geometry helper in `baseline_bot.py`, so editing the current bot does not silently change simulator collision or visibility rules. Roof-edge support was corrected after the initial smoke tests. It remains an approximation, not the official engine.

```powershell
python -m unittest discover -s simulator -p "test_*.py"
python simulator/run_suite.py --bot simulator/baseline_bot.py --label baseline --seeds 1 2 3
python simulator/run_suite.py --label candidate --seeds 1 2 3 4 5 --include-roof
python simulator/stress_bot.py
python simulator/render_trace.py simulator/results/candidate/random-1/trace.jsonl
```

A suite saves each trace separately and writes `suite.json` after each completed scenario. By default combat scenarios run for 120 seconds; the optional rooftop/zone test runs for 350 seconds. The SVG renderer marks deaths and paths over the actual map, plus the final safe circle. Timing stress uses 27 tracked actors and six simultaneous sounds. Simulation decisions near the wall-clock cutoff can vary with machine load; seeds fix random spawns and shot rolls, not CPU scheduling.

Current bot changes retain the one-second steering horizon and never fire. Strategic navigation now uses a cached ground grid and incremental A* to route around buildings. It models its current elevation and roof-edge support, checks route midpoints for exposure, preserves energy with separate boost start/stop thresholds, avoids physical map edges, and completes full torso scans. It revalidates navigation clearance after size changes. The wrapper fails explicitly if initialization fails rather than reporting ready and silently idling.
