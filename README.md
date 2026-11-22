# Cube Hunter

The Docker entrypoint is `hunter_bot.py`. It follows the mechfight wrapper/example structure and uses `avoid_bot.py` only as its map-aware navigation and hiding component.

## Strategy

1. Below 10 cubes, collect safe loose cubes, destroy crates, fight drones, and hunt weaker mechs. Explore when nothing suitable is visible.
2. At 10 cubes, switch to hiding. Stop seeking crates and distant farming targets.
3. Attack a nearby weaker opponent when the fight looks favorable, collect its dropped cubes, then return to hiding. Nearby drones can also be opportunistic targets.
4. Zone escape and health recovery override farming or fighting. Recover below 50% HP and resume hunting after reaching 85% HP.

"Weaker" means our estimated health-times-sustained-damage advantage is at least 1.5x. This accounts for current HP, known weapons, armor on our mech, and cube damage scaling. Enemy upgrades are not fully visible, so this is a conservative estimate, not a guarantee. Missing enemy HP means we do not initiate that fight. Nearby supporting mechs can veto an attack.

The bot leads gun shots, waits for the actual torso aim to align, checks geometry before firing, and reloads. It keeps the starter gun and can take a nearby lightning weapon into an empty slot. It does not deliberately acquire lasers or mortars. Cubes are collected automatically by walking into pickup range; their vertical pickup limit is respected. Delayed kills and loot locations are remembered briefly.

Debug drawings show FARM, HUNT, LOOT, EXPLORE, HIDE, AMBUSH, RECOVER, or ZONE, plus cube count, HP, target, navigation goal, and aim line. The protocol says these drawings are private and may not be displayed on the competition page.

## Build and verify

```sh
docker build --platform linux/amd64 -t cube-hunter .
python check/check.py -- python -u hunter_bot.py
python -m unittest discover -s tests -p "test_*.py"
python tests/stress_hunter.py
```

Run the checker inside Linux to avoid Windows converting `/arena` to a Windows path:

```sh
docker run --rm --platform linux/amd64 --network none --cpus 1 --memory 512m --read-only --tmpfs /tmp:rw,size=64m --user 65534:65534 -v "${PWD}/arena:/arena:ro" -v "${PWD}/check:/check:ro" -v "${PWD}/mechfight.schema.json:/mechfight.schema.json:ro" --entrypoint python3 cube-hunter /check/check.py --map-dir /arena -- python3 -u /bot/hunter_bot.py
```

The Python base image is pinned; no extra dependencies are required. Runtime map files come from the server mount. The repository's arena files are development fixtures.

## Evidence and limitations

The tests cover the 10-cube transition, favorable/unfavorable fights, supporting opponents, recovery, zone priority, aiming, reloads, cube priority, delayed kills, and returning to hiding after loot collection. A controlled policy test kills five stationary drones and collects ten cubes. It is not a realistic match: it uses flat movement, ideal registered hits, and no enemy attacks.

The older simulator and `REGRESSION_RESULTS.md` are historical passive-bot artifacts. They do not validate this hunter. In particular, practice uses 15 house bots sharing vision and never fighting each other, as documented in `instructions.md`; the old free-for-all simulator did not model that. Passing checks does not establish a practice win rate. Navigation still uses approximate geometry and ground routes rather than general jet-based rooftop access.

## Current validation

- 16 policy/combat tests passed inside the restricted Linux/AMD64 Docker container.
- Official conformance fixture: 300/300 responses on time; maximum 31.8 ms; 300 debug drawings within caps.
- Crowded synthetic observations (27 actors, 36 crates, 60 loose cubes): 50/50 decisions within budget; maximum 38.8 ms.
- No real practice match score has been measured for this hunter yet.

The live rule defaults cap the basic cube HP/damage bonuses at 10 cubes. Further cubes still grow the mech and can unlock additional upgrade offers; this bot continues collecting them after opportunistic kills as requested.
