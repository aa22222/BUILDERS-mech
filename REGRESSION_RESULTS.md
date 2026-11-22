> Historical results for the previous passive bot. These do not validate the deployed cube hunter. The legacy simulator does not model hunter attacks, loot progression, or the coordinated practice opponents.

# Regression results

These are approximate simulations, not results from the competition server.

Bot SHA-256: `03d7d8bf3f0245cc41e108d6a56c6a9aa000795d6b13e225c16f901a20cf18b7`

| Test | Original bot | Revised bot |
| --- | --- | --- |
| pursuit, seeds 1-3, survives 120 s | 1/3 | 3/3 |
| random, seeds 1-3, survives 120 s | 2/3 | 3/3 |

The revised bot survived all ten 120-second combat scenarios (five pursuit seeds and five 16-actor seeds). It also survived the 350-second rooftop/zone scenario with full health and no zone damage. All 15,500 decisions across this suite were under 50 ms, and no bot exceptions occurred. These observations do not prove that all match failures have been eliminated.

Validation on the selected revision:

- 12 focused tests passed, including roof escape, zone re-entry, completed scans, size changes, ray geometry, initialization failure, and consistent refuge selection under short CPU slices.
- Linux/AMD64 Docker build succeeded with the pinned base image.
- Docker conformance: 300/300 on time, no protocol errors; maximum response 32.0 ms.
- Docker stress: 27 tracked actors and six sounds, 50 decisions, maximum 32.25 ms, none over 50 ms.

Full-length results (480-second limit, ending earlier on death or last survivor):

| Scenario | Seed | Outcome | End time | Damage received |
| --- | --- | --- | --- | --- |
| pursuit | 1 | Last survivor | 374.8 s | {'gun': 1035} |
| pursuit | 2 | Last survivor | 278.2 s | {'gun': 315} |
| pursuit | 3 | Last survivor | 217.4 s | {'gun': 270} |
| random | 1 | Died to gunfire | 157.6 s | {'gun': 1935} |
| random | 2 | Last survivor | 375.3 s | {'gun': 45} |
| random | 3 | Died to gunfire | 35.4 s | {'gun': 1800} |

The selected revision finished alive in 4/6 full-length scenarios. It still died to gunfire in two multi-bot runs (seeds 1 and 3). The result is an improvement, not a claim that every failure is fixed. Short and full runs can diverge before the cutoff because CPU scheduling affects bounded planning and simulation interactions. There were no bot exceptions or over-budget decisions in these full-length runs.

Remaining modeling limits: sampled terrain and collision approximation; simplified instant probabilistic gunfire; no NPC drones, loot, rear armor, jumps/jets, or projectile physics. The bot remains passive and cannot guarantee survival when cover is inaccessible or the safe circle collapses.

Death-location maps for the remaining full-run losses: [seed 1](evaluation/full-random-1.svg), [seed 3](evaluation/full-random-3.svg). Seed 1 died at 157.6 s near (311.13, 3.51, 4.30); seed 3 died at 35.4 s near (-19.05, -87.16, -0.59). Both were gunfire deaths with no zone damage. These are simulator locations, not verified competition deaths.
