# V10 — BANGER AUDIT (actual code fixes, official scoring still unmeasured)

Branch: \`v10-banger-audit\`

## Audited sources
- Original Mech Royale \`mechfight/1\` protocol, observation schema, rules and Ohio State world.json/terrain.i16 from the official starter kit.
- Exact code on \`v9-exploit-stack\`, \`v9x-upgrade-lottery\`, their CI tests and existing scripts.
- Live track rules (on Nov 22, 2026) list scorer \`builders-4\`, **96 private fresh-seed practice matches**, four submissions per hour and 50ms per decision. See https://www.joinbuilders.org/buildathon/tracks/builders .
- No local game engine is provided in the starter kit, only a **non-reactive 300-observation** checker. Do not claim any observed placement improvement without an official score.

## Critical defects fixed in this branch

1. **Multi-tick laser ambush noise leak.** V9 evaluated whether the rear one-hit assassination was valid on *each* decision. If a victim turned while our laser was charging, the arm gun resumed firing. Added \`ambush_target_id\` to retain quiet action for the charge; also actually prioritizes a qualified assassination target among visible mechs.
2. **Laser 350HP NPC damage breakpoint.** Laser's full 315 damage at three cubes is 352.8; release 0.05 sec before full charge is insufficient (roughly 337HP). For one-hit resource farming and assassinations, wait for \`stats.charge\` full, then release. Regression tests check both .70s held and .75s released.
3. **Laser farming silently disables gun during 1.65-second cooldown.** One-hit resource quieting is now enabled only if the laser is ready or actively charging, avoiding inactivity after a missed shot.
4. **Recovery allowed obvious projectile impacts.** Added a bounded relative-motion intercept detector for nearby incoming gun/NPC/mortar projectiles. It interrupts passive HEAL with EVADE when the hit is imminent; near the 160–260DPS final safe circle it rejects needless gun-dodges that would surrender much more HP to the storm. This is heuristic, not engine-perfect.
5. **Foliage model only looked at crown centers.** Added tree-shadow candidates *behind* each crown relative to the nearest shooter, including left/right offsets, and verifies optical attenuation of both the mech's middle and top, walking reachability, near-range sensor clearance, next-zone safety and a strict decision deadline.
6. **Foliage mode could release an active laser.** Pressing \`fire=false\` after hiding begins releases any charging laser and makes a loud sound. V10 forbids entering or maintaining GHOST while its own laser is charging.

## Reviewed, deliberately unmerged high-variance strategy
V9X's upgrade offer manipulation temporarily drops only the secondary; it keeps the gun equipped. At an unstacked starting loadout there are nine universal upgrades, four gun upgrades, and three secondary-specific upgrades (total 16). Dropping secondary reduces 16 to 13 candidates.

Under uniform, three-distinct-offer sampling before stack eligibility changes:
- Nanites chance increases **18.75% -> 23.08%**, a mere **+4.33 percentage points**.
- Either nanites/plating increases **35.00% -> 42.31%**, **+7.31 percentage points**.
This does not account for eligibility, upgrade caps, weapon loss risk, opportunity cost, or hidden game-score consequences. **DO NOT MERGE V9X** without a demonstrated real-match positive effect.

## Preserved existing V9 mechanics
Canopy GHOST concealment, endgame center collision guarding, late-storm mortar concussion, one-hit rear laser ambush, early 300HP crate and 350HP drone laser breakpoints, pulsed-jet conditional ascent, 3-cube/full-heal drops, cover-aware routing, and 10-bank placement safeguards. Not every mechanism is scientifically validated by the kit.

## Validation
Latest passing V10 code-only GitHub Actions:
https://github.com/Eitan77/mech-royale/actions/runs/44998872676

- 107/107 unit and integration tests
- Native recorded protocol: 300/300, zero late
- 1-CPU/512MB/read-only container recorded protocol: 300/300, zero late
- Container p99: 15.7ms, max: 20.8ms of 50ms limit
- All existing V5/V8/V9 baseline regressions still pass
- **No official game score for V10 yet.**

## Submit / compare carefully
1. \`git fetch origin\` then check out \`v10-banger-audit\`. Pin the exact SHA shown on its green GitHub Actions run.
2. Be sure the contest uses that SHA, **not** \`main\` (which historically pointed to the original starter).
3. Obtain the real practice score under the current \`builders-4\` 96-match scorer.
4. Keep the user's officially scored 3.79 V5 and 3.01 V7 builds as rollback points; cross-scorer comparisons are imperfect.
5. Do not confuse qualification-entry selection text with proof of ranking top-32.
6. Avoid chasing an unproved 10/15 prediction. The public board was roughly 5.5–6.4 for the stronger entries at the time of this audit; a 10 mean would be a substantial breakthrough.

## Codex prompt
\`\`\`
Repo: https://github.com/Eitan77/mech-royale
Branch: v10-banger-audit
Preserve all pre-existing versions and do not force push or overwrite main.
Review the V10 changes and 107 passing tests including
tactical_v10.py, test_tactical_v10.py, test_v10_integration.py,
foliage_v9.py, controller.py, and the original mechfight/1 kit.
Run Docker sandbox conformance before any submission.
Confirm the portal shows the exact pinned V10 SHA.
Get the REAL 96-match practice score under current scorer builders-4.
Never report protocol tests as placement results.
If it scores below the best previously measured result under the same scorer,
keep the better scored submission.
\`\`\`
