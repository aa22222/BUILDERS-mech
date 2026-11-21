# Quiet Border

Passive Mechfight bot: avoid opponents, seek solid cover, and stay inside the shrinking safe circle. It never fires. Local steering predicts one second of movement; an incremental A* planner supplies longer routes around buildings.

The runtime reads the map mounted by the match server, follows live position and zone observations, accounts for rooftop height, and checks both destination and midpoint exposure. Boosting uses separate start/stop energy thresholds to allow regeneration. Torso scans complete a full sweep rather than repeatedly resetting toward nearby threats. Navigation clearance updates when mech size changes.

## Build and check

```sh
docker build --platform linux/amd64 -t quiet-border .
python check/check.py -- python -u avoid_bot.py
```

To avoid the Windows checker's `/arena` path conversion, run the checker inside the Linux container. This also works on Linux:

```sh
docker run --rm --platform linux/amd64 --network none --cpus 1 --memory 512m --read-only --tmpfs /tmp:rw,size=64m --user 65534:65534 -v "${PWD}/arena:/arena:ro" -v "${PWD}/check:/check:ro" -v "${PWD}/mechfight.schema.json:/mechfight.schema.json:ro" --entrypoint python3 quiet-border /check/check.py --map-dir /arena -- python3 -u /bot/avoid_bot.py
```

The Docker image copies only `avoid_bot.py` and `mechfight.py`. The map and simulator in this repository are local development fixtures, not bundled runtime map assets. The Python base image is pinned by digest, and no additional packages are needed.

## Reproduce the simulation checks

```sh
python -m unittest discover -s simulator -p "test_*.py"
python simulator/run_suite.py --label candidate --seeds 1 2 3 4 5 --include-roof --workers 3
python simulator/run_suite.py --bot simulator/baseline_bot.py --label baseline --seeds 1 2 3
python simulator/stress_bot.py
python simulator/render_trace.py simulator/results/candidate/random-1/trace.jsonl
```

See [simulator/README.md](simulator/README.md) for assumptions and outputs. Simulation is diagnostic, not a recreation of the authoritative game engine. Surviving a timed scenario is not a match win. There is no guarantee of avoiding all opponents, all damage, or the final zero-radius zone. The bot cannot locate opponents the server has never revealed, and ground-route planning does not actively jet over otherwise impassable buildings.

Recorded validation and simulation outcomes: [REGRESSION_RESULTS.md](REGRESSION_RESULTS.md).
