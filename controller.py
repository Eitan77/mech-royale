"""Resource-first controller with cover-aware movement and a timed endgame."""
import math
import time

from arena import Arena
from firing import firing_delay, project_position, shot_connects
from pilot import choose_movement
from storm_tactics import mortar_shot, storm_screen
import mechfight as mf
from mobility import GroundBoost, defensive_yaw, jet_pulse, project_ascent, rear_laser_bonus
from tactics_v5 import (classify_danger, next_mode, candidate_resource_target,
                        energy_floor, zone_eta, should_commit_resource,
                        should_skirmish)
from scoremax_v8 import (npc_pressure, immediate_npc_escape,
                         upgrade_scoremax)
from foliage_v9 import Foliage, should_ghost, stealth_vector
from mechanics_v9 import (one_shot_laser_ambush, easy_laser_drone,
                          contest_center, storm_finish)
from tactical_v10 import (imminent_projectile, sniper_choice,
                          resource_laser_silence)

ANGLES = tuple((math.cos(i * math.tau / 12), math.sin(i * math.tau / 12)) for i in range(12))
WEAPONS = {"gun": 0, "mortar": 0, "laser": 1, "lightning": 2}


def distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def bearing(a, b):
    return math.atan2(b[1] - a[1], b[0] - a[0])


def angle_delta(a, b):
    return abs(math.remainder(a - b, math.tau))


def intercept(origin, target, velocity, speed):
    r = [b - a for a, b in zip(origin, target)]
    a = sum(v * v for v in velocity) - speed * speed
    b = 2 * sum(x * v for x, v in zip(r, velocity))
    c = sum(x * x for x in r)
    discriminant = b * b - 4 * a * c
    travel = 0
    if a < 0 and discriminant >= 0:
        travel = 2 * c / max(1e-6, math.sqrt(discriminant) - b)
    return tuple(p + travel * v for p, v in zip(target, velocity))


def duel(me, enemy, weapons, attackers):
    distance_xy = distance(me["pos"], enemy["pos"])

    def dps(loadout, cubes):
        total = 0
        for w in loadout:
            if not w:
                continue
            kind = w["kind"] if isinstance(w, dict) else w
            stats = w["stats"] if isinstance(w, dict) else weapons[kind]
            if distance_xy >= stats.get("range", 140):
                continue
            period = stats["cooldown"]
            confidence = 0.65
            if kind == "gun":
                period += stats["reload"] / stats["mag"]
                confidence = max(0.18, 0.74 - distance_xy * 0.003)
            elif kind == "laser":
                period += stats["charge"]
            elif kind == "lightning":
                confidence = 0.88
            else:
                confidence = 0.2
            total += confidence * stats["damage"] / period
        return total * (1 + 0.04 * min(10, cubes))

    own = [w for w in me["weapons"] if w and (w["kind"] != "lightning" or me["energy"] > 18)]
    enemy_weapons = enemy.get("weapons", ("gun",))
    outgoing = dps(own, me["cubes"])
    incoming = dps(enemy_weapons, enemy.get("cubes", 0)) * (1 - me["stats"].get("armor", 0))
    if any(w["kind"] == "lightning" and distance_xy < w["stats"]["range"] - 2 for w in own) and "laser" in enemy_weapons:
        incoming *= 0.65
    seconds = enemy.get("hp", enemy.get("max_hp", 1400)) / max(1, outgoing)
    return seconds, seconds * incoming * (1 + 0.55 * max(0, attackers - 1))


class Bot:
    name = "V13 Laser and Arc"

    def __init__(self, hello):
        self.config = hello["config"]
        self.arena = Arena(hello["map"]["dir"])
        self.foliage = Foliage(hello["map"]["dir"])
        self.memory = {name: {} for name in ("crates", "cubes", "pickups", "mechs")}
        self.last_damage = -100
        self.last_hit = -100
        self.damage_bearing = None
        self.path = []
        self.path_goal = None
        self.path_update = -100
        self.cover = None
        self.cover_update = -100
        self.last_progress = None
        self.crossing = None
        self.crossing_retry = -100
        self.detour = None
        self.launching = False
        self.laser_target = None
        self.loot_goal = None
        self.roof_plan = None
        self.roof_plan_at = -100
        self.roof_target = None
        self.roof_crossing = False
        self.roof_traversing = False
        self.ground_boost = GroundBoost()
        self.landing = None
        self.evade_side = 1
        self.evade_until = 0
        self.shorted_until = {}
        self.refuge = None
        self.refuge_scan = -100
        self.recovering = False
        self.mode = "TRAVEL"
        self.mode_since = 0.0
        self.resource_lock = None
        self.resource_lock_at = -100.0
        self.danger_cache = None
        self.danger_update = -100.0
        self.zone_eta_cache = (None, -100.0)
        self.last_enemy_seen = -100.0
        self.last_npc_damage = -100.0
        self.last_npc_attacker = None
        self.foliage_goal = None
        self.foliage_score = 0.
        self.foliage_scan_at = -100.
        self.foliage_until = -100.
        self.foliage_active = False
        self.ambush_target_id = None

    def remember(self, obs, now):
        for group, ttl in (("crates", 45), ("cubes", 18), ("pickups", 50), ("mechs", 4)):
            memory = self.memory[group]
            visible = {item["id"] for item in obs[group]}
            position = obs["self"]["pos"]
            for ident, (item, seen) in list(memory.items()):
                nearby_loot = group in ("crates", "cubes", "pickups") and distance(item["pos"], position) < 6
                if now - seen > ttl or (nearby_loot and ident not in visible):
                    del memory[ident]
            memory.update((item["id"], (item, now)) for item in obs[group])
        for event in obs["events"]:
            kind = event["type"]
            if kind == "damaged":
                self.last_damage = now
                if (event.get("weapon") == "npc" or
                        event.get("by") is not None and event["by"] >= 100):
                    self.last_npc_damage = now
                    self.last_npc_attacker = event.get("by")
                if event.get("bearing") is not None:
                    self.damage_bearing = event["bearing"]
            elif kind == "hit":
                self.last_hit = now
                if event.get("effect") == "short":
                    self.shorted_until[event["target"]] = now + self.config["weapons"]["lightning"]["short_s"]
            elif kind == "kill":
                self.memory["mechs"].pop(event["target"], None)
                self.shorted_until.pop(event["target"], None)
            elif kind in ("took", "take_failed") and event.get("reason") in (None, "gone", "have"):
                self.memory["pickups"].pop(event["id"], None)

    def cover_point(self, p, threats, zone, size, anchor, now, deadline):
        if now - self.cover_update < 0.45 and self.cover is not None and distance(p, self.cover) < 45:
            return self.cover
        self.cover_update = now
        best, best_score = None, -math.inf
        for radius in (0, 10, 18, 30):
            for dx, dy in ANGLES[:1] if radius == 0 else ANGLES:
                if time.perf_counter() > deadline:
                    self.cover = best
                    return best
                q = (p[0] + dx * radius, p[1] + dy * radius)
                z = self.arena.ground(*q)
                if distance(q, zone["center"]) > zone["radius"] - 2 or not self.arena.walk(p[:2], q, size):
                    continue
                separation = min(distance(q, a["pos"]) for a, _ in threats)
                if separation < 14 and radius > 0:
                    continue
                protected = 0
                for enemy, weight in threats[:3]:
                    eye = (*enemy["pos"][:2], enemy["pos"][2] + 7 * (1 + 0.05 * enemy.get("cubes", 0)))
                    if not self.arena.shot(eye, (*q, z + 7 * size)):
                        protected += weight
                score = 26 * protected - radius - 0.25 * distance(q, anchor) + 0.28 * min(75, separation)
                if protected and score > best_score:
                    best, best_score = q, score
        self.cover = best
        return best

    def recovery_roof(self, me, threats, zone, size, now, deadline):
        p = me["pos"]
        if self.refuge and distance(p, self.refuge) < 75:
            q = self.refuge
            if (distance(q, zone["next_center"]) < zone["next_radius"] - 5
                    and all(distance(q, e["pos"]) > 9 or q[2] - e["pos"][2] > 9 for e, _ in threats[:3])):
                return q
        self.refuge = None
        if now - self.refuge_scan < 1 or me["energy"] < 58:
            return None
        self.refuge_scan = now
        candidates = sorted((q for q in self.arena.rooftops if 8 < q[2] - p[2] < 25 and
                             distance(q, p) < 40 and distance(q, zone["next_center"]) < zone["next_radius"] - 12),
                            key=lambda q: distance(q, p) + .4 * (q[2] - p[2]))
        for q in candidates[:5]:
            if time.perf_counter() >= deadline:
                break
            if not self.arena.clear(*q, 2.5 * size, 9 * size):
                continue
            approaching = [e for e, _ in threats[:3] if distance(e["pos"], p) < 115]
            if not approaching:
                break
            sheltered = 0
            for enemy in approaching:
                x, y, z = enemy["pos"]
                muzzle = (x, y, z + 7 * (1 + .05 * enemy.get("cubes", 0)))
                if not self.arena.shot(muzzle, (q[0], q[1], q[2] + 2)):
                    sheltered += 1
            if sheltered == len(approaching):
                self.refuge = q
                return q
        return None

    def finish_capture(self, obs, enemies):
        me = obs["self"]
        if not me["grounded"]:
            return None
        weapons = self.config["weapons"]
        for drop in obs["drops"]:
            if drop["holder"] not in (None, me["id"]) or drop["lands_in"] > 0:
                continue
            center, radius = drop["pos"], drop["radius"]
            if distance(me["pos"], center) >= radius - .2:
                continue
            progress = drop["progress"] if drop["holder"] == me["id"] else 0
            remaining = max(.1, drop["capture_s"] - progress)
            # Allow for opponents with upgraded boost speed.
            if any(distance(enemy["pos"], center) < radius + remaining * 26 + 2
                   for enemy in enemies):
                continue
            danger = 0.0
            p = me["pos"]
            body = (*p[:2], p[2] + .5 * me["stats"]["height"])
            for enemy in enemies:
                reach = distance(p, enemy["pos"])
                if reach > weapons["laser"]["range"] or not self.arena.shot(
                    (*enemy["pos"][:2], enemy["pos"][2] + 7 * (1 + .05 * enemy["cubes"])), body,
                ):
                    continue
                incoming = 0.0
                for kind in enemy["weapons"]:
                    weapon = weapons[kind]
                    if kind in ("gun", "lightning") and reach <= weapon["range"]:
                        incoming += weapon["damage"] * math.ceil(remaining / weapon["cooldown"])
                    elif kind == "laser" and (enemy["charging"] or remaining >= weapon["charge"]):
                        incoming += weapon["damage"] * (1 + int(remaining / (weapon["charge"] + weapon["cooldown"])))
                    elif kind == "mortar" and reach < 170:
                        incoming += weapon["damage"] + weapon["splash"]
                danger += incoming * (1 + .04 * min(10, enemy["cubes"]))
            if me["hp"] > danger + 125:
                return drop
        return None

    def objective(self, obs, enemies, weapon, p, zone, now, weapon_values):
        # Stay committed to a safe resource; recheck that it is still visible
        # or otherwise known to exist before carrying a stale objective.
        if self.resource_lock is not None:
            group, ident, _ = self.resource_lock
            entry = self.memory[group].get(ident)
            available = entry is not None and (
                group not in ("crates", "mechs") or
                any(a["id"] == ident for a in obs[group]))
            risk = any(distance(p, e["pos"]) < 35 and e.get("charging")
                       for e in enemies)
            if should_commit_resource(now, self.resource_lock_at, available, risk):
                item, _ = entry
                if distance(p, item["pos"]) < 130:
                    self.loot_goal = ident
                    return group, ident, item["pos"]
            self.resource_lock = None
        best, best_score = None, 0
        hp = obs["self"]["hp"] / obs["self"]["max_hp"]
        stats = obs["self"]["stats"]
        size = 1 + 0.05 * obs["self"]["cubes"]

        travel_budget = time.perf_counter() + 0.004

        def travel(q, d):
            direct = time.perf_counter() < travel_budget and self.arena.walk(p[:2], q[:2], size)
            return (d if direct else 1.45 * d + 9) / stats["walk_speed"]

        count = obs["self"]["cubes"]
        nearest = min((distance(p, e["pos"]) for e in enemies), default=300)
        for drop in obs["drops"]:
            q = drop["pos"]
            d = distance(p, q)
            contested = any(distance(e["pos"], q) < drop["radius"] + 10 for e in enemies)
            if not contested and drop["holder"] in (None, obs["self"]["id"]) and d < 125:
                eta = travel(q, d)
                enemy_eta = min((distance(e["pos"], q) / stats["boost_speed"] for e in enemies),
                                default=math.inf)
                capture_window = max(eta, drop["lands_in"]) + drop["capture_s"]
                if enemy_eta + 1.5 < capture_window and drop["holder"] != obs["self"]["id"] and drop["lands_in"] < 5:
                    continue
                full_heal = (1 - hp) * 43
                breakpoint = 8 if any(count < threshold <= count + 3
                                      for threshold in self.config["cubes"]["upgrade_thresholds"]) else 0
                score = 31 + full_heal + breakpoint - 2.3 * eta - 0.8 * max(0, drop["lands_in"] - eta - 5)
                if drop["holder"] == obs["self"]["id"]:
                    score += 14 + 3 * drop["progress"]
                if score > best_score:
                    best, best_score = ("drop", drop["id"], q), score
        for group in ("cubes", "pickups", "crates", "mechs"):
            for ident, (item, seen) in self.memory[group].items():
                q = item["pos"]
                d = distance(p, q)
                if d > 130 or distance(q, zone["next_center"]) > zone["next_radius"] + max(0, zone["shrink_end"] - now) * 3:
                    continue
                if (abs(q[2] - self.arena.ground(*q[:2])) > 5 and abs(q[2] - p[2]) > 4
                    and (group not in ("pickups", "cubes") or nearest < 95 or d > 45
                         or obs["self"]["energy"] < 70 or q[2] - p[2] > 78)):
                    continue
                if group == "mechs" and item["kind"] != "npc":
                    continue
                if group == "pickups" and weapon_values[item["kind"]] <= weapon_values.get(weapon, 0):
                    continue
                if group in ("crates", "mechs") and (nearest < 62 or hp < 0.65 or count >= 10):
                    continue
                if group in ("cubes", "pickups") and any(distance(e["pos"], q) < min(24, d * 0.7) for e in enemies):
                    continue
                value = {"cubes": 32 if count < 10 else 5, "pickups": 38, "crates": 17, "mechs": 22}[group]
                if weapon == "laser" and group in ("crates", "mechs"):
                    laser = next(w for w in obs["self"]["weapons"] if w and w["kind"] == "laser")
                    damage = laser["stats"]["damage"] * (1 + 0.04 * min(10, count))
                    if damage >= item.get("hp", 350):
                        # A full-charge laser one-shots 300-HP crates from
                        # zero cubes, and 350-HP drones after 3 cubes.
                        # The real payoff is the cubes and upgrades, not the
                        # nominal damage. Prefer accessible free resources.
                        if d < 90 and nearest > 115 and now < 245 and count < 10:
                            value += 26 if group == "mechs" else 20
                        else:
                            value += 12
                if group == "cubes" and count + 1 in self.config["cubes"]["upgrade_thresholds"]:
                    value += 9
                score = value - 2.8 * travel(q, d) - 0.29 * (now - seen)
                if group == "mechs":
                    exposed = max(0, 5 - (hp - 0.65) * 10)
                    score -= exposed
                if self.loot_goal == ident:
                    score += 4
                if score > best_score:
                    best, best_score = (group, ident, q), score
        self.loot_goal = best[1] if best else None
        # Supply drops are not in self.memory; never lock a non-memory group.
        if best is not None and best[0] in self.memory:
            self.resource_lock = best
            self.resource_lock_at = now
        else:
            self.resource_lock = None
        return best

    def resource_waypoint(self, p, target, group, size, stats, deadline):
        """Choose a reachable firing perch with a path to collect the cubes."""
        desired = 23 if group == "crates" else 33
        body = (*target[:2], target[2] + (0.8 if group == "crates" else self.config["npc"]["height"] * .5))
        if distance(p, target) <= desired and self.arena.shot((*p[:2], p[2] + stats["muzzle_height"]), body):
            return p[:2]
        facing = bearing(target, p)
        best, best_cost = None, math.inf
        for radius in (desired, desired * .6, desired * .35):
            for offset in (0, .55, -.55, 1.05, -1.05, 1.60, -1.60):
                if time.perf_counter() >= deadline:
                    return best or target[:2]
                q = (target[0] + radius * math.cos(facing + offset), target[1] + radius * math.sin(facing + offset))
                z = self.arena.ground(*q)
                if not self.arena.clear(*q, z, 2.5 * size + .25, 9 * size):
                    continue
                if not self.arena.shot((*q, z + stats["muzzle_height"]), body):
                    continue
                direct = self.arena.walk(p[:2], q, size)
                collecting = self.arena.walk(q, target[:2], size)
                cost = distance(p, q) * (1 if direct else 1.55) + radius * (0.7 if collecting else 1.4)
                if cost < best_cost:
                    best, best_cost = q, cost
        return best or target[:2]

    def target_body(self, actor):
        p = actor["pos"]
        kind = actor.get("kind", "crate")
        size = 1 + 0.05 * actor.get("cubes", 0)
        height = {"mech": 4.5 * size, "npc": self.config["npc"]["height"] * 0.5, "crate": 0.8}[kind]
        return p[0], p[1], p[2] + height

    def combat(self, act, obs, origin, target, retreat, urgent, final, primary_threat):
        me = obs["self"]
        cfg = self.config["mech"]
        gun = next((w for w in me["weapons"] if w and w["kind"] == "gun"), None)
        laser = next((w for w in me["weapons"] if w and w["kind"] == "laser"), None)
        lightning = next((w for w in me["weapons"] if w and w["kind"] == "lightning"), None)
        charge = laser.get("charge", 0) if laser else 0
        if not target:
            act["reload"] = bool(gun and gun.get("ammo", 0) <= 6)
            self.laser_target = None
            self.ambush_target_id = None
            return
        d = distance(origin, target["pos"])
        body = self.target_body(target)
        velocity = target.get("vel", (0, 0, 0))
        gun_delay = firing_delay(gun) if gun else .05
        gun_origin = project_position(origin, me["vel"], gun_delay)
        gun_speed = (gun["stats"] if gun else self.config["weapons"]["gun"])["speed"]
        lead = intercept(gun_origin, project_position(body, velocity, gun_delay), velocity, gun_speed)
        # The arc covers the laser's close-range counter. Preserve a charged
        # shot, but don't start a new charge inside an opposing arc's range.
        enemy_arc = d < self.config["weapons"]["lightning"]["range"] + 10 and (
            "lightning" in target.get("weapons", ())
        )
        use_laser_aim = laser and (charge or not enemy_arc and (
            not gun or not (retreat or urgent or final) and laser["cooldown"] <= .15
        ))
        aim_origin, aim_point = gun_origin, lead
        if use_laser_aim:
            delay = firing_delay(laser)
            aim_origin = project_position(origin, me["vel"], delay)
            aim_point = project_position(body, velocity, delay)
        elif lightning and d < lightning["stats"]["range"] - 1 and (not gun or target.get("charging")):
            aim_origin, aim_point = origin, body
        yaw = bearing(aim_origin, aim_point)
        pitch = math.atan2(aim_point[2] - aim_origin[2], distance(aim_origin, aim_point))
        act["aim"] = [yaw, max(cfg["min_pitch"], min(cfg["max_pitch"], pitch))]
        error = angle_delta(yaw, me["aim"][0])
        allowed_pitch = cfg["min_pitch"] <= pitch <= cfg["max_pitch"]
        clear = allowed_pitch and self.arena.shot(aim_origin, aim_point)
        kind = target.get("kind", "crate")
        scale = 1 + self.config["cubes"]["size_per_cube"] * target.get("cubes", 0)
        radius, height = {
            "mech": (cfg["radius"] * scale, cfg["height"] * scale),
            "npc": (self.config["npc"]["radius"], self.config["npc"]["height"]),
            "crate": (1.15, 1.6),
        }[kind]
        aligned = bool(laser and error < .3 and shot_connects(
            self.arena, origin, me, act["aim"], target, laser, radius, height
        ))
        finishing = target.get("kind") == "mech" and target.get("hp", 1400) < 145 and d < 60
        is_rear_duel = target.get("kind") == "mech" and angle_delta(target["aim"][0], bearing(target["pos"], origin)) > 2.0
        offensive = not (urgent or final) and (not retreat or is_rear_duel) or finishing
        is_mech = target.get("kind") == "mech"
        final_guard = (is_mech and contest_center(
            me,target,obs["zone"],obs["t"],retreat))
        all_mechs=[a for a in obs["mechs"] if a["kind"]=="mech"]
        fresh_ambush = (is_mech and not retreat and not urgent and not final and
                        one_shot_laser_ambush(me,target,all_mechs,obs["zone"],
                                             obs["t"],obs["alive"]))
        # Multi-tick laser charge: remain silent if target faces us midway.
        if fresh_ambush and not charge:
            self.ambush_target_id = target["id"]
        ambush_locked = bool(is_mech and self.ambush_target_id==target["id"]
                             and charge)
        ambush = fresh_ambush or ambush_locked
        if not ambush and not charge:
            self.ambush_target_id = None
        offensive = offensive or final_guard or ambush
        if self.recovering:
            # Avoid dealing damage during genuine escape/heal phases:
            # one successful shot resets the five-second regen timer.
            offensive = False
        # Running and firing the arm gun are independent. Only preserve silence
        # for an actual disengagement or committed final-circle recovery.
        return_fire = (is_mech and (not final or urgent) and d < 225
                       and not retreat and not self.recovering)
        # Scoremax: once ten opponents are already dead, don't start an
        # unneeded fight that jeopardizes a banked top-six placement.
        # A nearby assault or imminent charging laser still merits defense.
        banked = obs["alive"]<=6
        if banked and not final_guard and not (
                d<70 or target.get("charging") and d<165):
            offensive=False
            return_fire=False
        gun_clear = clear if aim_point is lead else self.arena.shot(gun_origin, lead)
        gun_aligned = bool(gun and gun.get("reload", 0) <= .1 and gun["cooldown"] <= .11
                           and (gun_clear or d < 35)
                           and shot_connects(self.arena, origin, me, act["aim"], target, gun, radius, height))
        one_shot_resource = resource_laser_silence(
            me,target,min((distance(me["pos"],e["pos"])
                           for e in all_mechs),default=999.),
            retreat,urgent,obs["t"])
        mortar = next((w for w in me["weapons"] if w and w["kind"] == "mortar"), None)
        zone = obs["zone"]
        outward = abs(distance(target["pos"], zone["center"]) - zone["radius"]) < 13
        mortar_finisher = (bool(mortar) and is_mech and
                           storm_finish(me,target,all_mechs,zone,obs["alive"]))
        mortar_aim = None
        if (mortar and is_mech and not urgent and not ambush and
                "laser" not in target.get("weapons", ())
                and not self.recovering and (not banked or final_guard) and
                ((mortar_finisher and not retreat) or
                 (d<100 and not gun_clear and not retreat) or
                 (d<75 and outward and me["hp"]>.85*me["max_hp"]))
                and d < 145 and mortar["cooldown"] <= .35):
            mortar_aim = mortar_shot(self.arena, (*origin[:2], me["pos"][2] + me["stats"]["height"] + .5),
                                     target["pos"], target["vel"], mortar["stats"], zone, outward)
            if mortar_aim and cfg["min_pitch"] <= mortar_aim[1] <= cfg["max_pitch"]:
                act["aim"] = list(mortar_aim)
                gun_aligned = False
            else:
                mortar_aim = None
        for i, weapon in enumerate(me["weapons"]):
            if not weapon:
                continue
            kind, stats = weapon["kind"], weapon["stats"]
            if kind == "gun":
                # Hold the loud 320m-carry gun during a 140m-silent
                # rear-laser ambush, even when we otherwise could potshot.
                act["fire"][i] = bool((offensive or return_fire) and
                                      not ambush and not one_shot_resource and
                                      gun_aligned)
            elif kind == "mortar" and mortar_aim:
                act["fire"][i] = angle_delta(mortar_aim[0], me["aim"][0]) < .035 and abs(mortar_aim[1] - me["aim"][1]) < .023
            elif kind == "lightning":
                short_left = self.shorted_until.get(target["id"], -100) - obs["t"]
                short = ("laser" in target.get("weapons", ())
                         and (target.get("charging", False) or -.4 < short_left <= .22))
                reserve = 18 if retreat else 12
                eligible = (not self.recovering and (offensive or return_fire or short) and d < stats["range"]
                            and weapon["cooldown"] <= .11 and
                            me["energy"] > stats["energy"] + (3 if short else reserve))
                if eligible:
                    act["fire"][i] = self.lightning_connects(obs, origin, target, stats)
            elif kind == "laser":
                same_target = self.laser_target == target["id"]
                if charge:
                    # Keep the same target until the actual torso can hit it.
                    # A charged laser held while the aim slews is preferable to
                    # accidentally releasing an unaligned shot.
                    max_hold = stats["charge"] + min(1.2, stats.get("hold_s", 2.0) - 0.25)
                    # A 3-cube laser needs its FULL 0.75s charge to deliver
                    # 352.8 damage to a 350HP drone. Releasing at 0.70s
                    # leaves it alive, triggers retaliation, and wastes the
                    # one-shot resource snowball opportunity.
                    full_required = bool(one_shot_resource or ambush)
                    release_at = stats["charge"] if full_required else stats["charge"] - .05
                    act["fire"][i] = bool(offensive and same_target and clear and (
                        charge < release_at or
                        (not aligned and charge < max_hold)
                    ))
                else:
                    act["fire"][i] = bool(offensive and not urgent and not enemy_arc and clear and allowed_pitch and error < 0.10
                                          and 2 < d < stats["range"] - 3 and weapon["cooldown"] <= 0.1
                                          and (target.get("kind") == "mech" or not primary_threat))
                    if act["fire"][i]:
                        self.laser_target = target["id"]
        if gun and gun.get("ammo", 0) <= 4 and (not gun_clear or not is_mech) and not any(act["fire"]):
            act["reload"] = True

    def lightning_connects(self, obs, origin, target, stats):
        # An intervening crate or drone consumes the first arc. Only spend
        # energy when the intended target can still receive a useful chain.
        turn = obs["self"]["stats"]["turn_rate"] * .05
        current = obs["self"]["aim"][0]
        desired = bearing(origin, target["pos"])
        yaw = current + max(-turn, min(turn, math.remainder(desired - current, math.tau)))
        cone = math.radians(stats["cone_deg"]) * .5
        if angle_delta(yaw, desired) > cone or distance(origin, target["pos"]) > stats["range"]:
            return False
        end = self.target_body(target)
        if not self.arena.shot(origin, end):
            return False
        nearer = []
        distance_to_target = distance(origin, target["pos"])
        for item in (*obs["mechs"], *obs["crates"]):
            if item["id"] == target["id"]:
                continue
            d = distance(origin, item["pos"])
            if d < distance_to_target and angle_delta(bearing(origin, item["pos"]), yaw) <= cone:
                point = self.target_body(item)
                if self.arena.shot(origin, point):
                    nearer.append((d, point))
        if not nearer:
            return True
        first = min(nearer)[1]
        return stats["chain"] > 0 and math.dist(first, end) < stats["chain_range"] and self.arena.shot(first, end)

    def final_movement(self, act, me, threats, p, anchor, goal, roof, remain, zone, size, now, deadline):
        stats = me["stats"]
        energy = me["energy"]
        d = distance(p, anchor)
        ground = self.arena.ground(*anchor)
        needs_roof = roof > ground + 2 and p[2] < roof - 0.25
        if self.roof_target != anchor:
            self.roof_target, self.roof_plan, self.roof_crossing = anchor, None, False
            self.roof_plan_at = -100
            self.roof_traversing = False
        if self.roof_plan is not None and not self.roof_crossing:
            _, launch, _, fuel = self.roof_plan
            if energy < fuel or d > 115 or not needs_roof:
                self.roof_plan = None
        if needs_roof and self.roof_plan is None and d < 110 and now - self.roof_plan_at > 1:
            self.roof_plan_at = now
            self.roof_plan = self.arena.roof_route(p, anchor, size, stats, energy, deadline)
        if self.roof_plan:
            _, launch, altitude, _ = self.roof_plan
            if not self.roof_crossing and (distance(p, launch) > 1.9 or math.hypot(*me["vel"][:2]) > 2):
                return False, launch if distance(p, launch) > 1.9 else p[:2]
            self.roof_crossing = True
            if energy < 1 or (d < 1.2 and p[2] >= roof - 0.25):
                self.roof_plan = None
                self.roof_crossing = self.roof_traversing = False
                return False, anchor
            act["jump"] = bool(me["grounded"])
            act["boost"] = not me["grounded"] and jet_pulse(me["vel"][2], energy, stats)
            self.roof_traversing |= p[2] >= altitude - 0.4
            return True, anchor if self.roof_traversing else launch

        horizontal_speed = math.hypot(*me["vel"][:2])
        high_roll = energy >= 170 and stats["jet_drain"] <= 9 and remain < 37
        flight_window = 2 < remain < min(37 if high_roll else 17, energy / stats["jet_drain"] * 1.35)
        if not self.launching and flight_window and d < 2.0 and horizontal_speed <= 2 and me["hp"] > zone["dps"]:
            climb, reserve = project_ascent(remain, me["vel"][2], energy, stats, me["grounded"])
            attained = p[2] + climb
            slope = math.tan(self.config["mech"]["max_pitch"])
            protected, exposed = 0.0, 0.0
            for enemy, weight in threats:
                enemy_pos = enemy["pos"]
                reach = distance(anchor, enemy_pos)
                equipment = enemy.get("weapons", ("gun",))
                muzzle = enemy_pos[2] + self.config["mech"]["muzzle_height"] * (1 + enemy.get("cubes", 0) * 0.05)
                if "mortar" in equipment and reach < 175:
                    exposed += weight
                if ("gun" in equipment or "laser" in equipment) and reach < 280:
                    ceiling = muzzle + slope * (reach + 2.5 * size + 5)
                    if attained > ceiling + 6 and ceiling - p[2] < 0.65 * (attained - p[2]):
                        protected += weight
                    elif self.arena.shot((*enemy_pos[:2], muzzle), (*anchor, attained + 4)):
                        exposed += weight
                if "lightning" in equipment and reach < 45:
                    exposed += weight
            clear_ascent = all(self.arena.clear(*p[:2], z, 2.5 * size, 9 * size)
                               for z in range(math.ceil(p[2]), math.ceil(attained), 3))
            range_denial = high_roll and threats and all(
                attained - (a["pos"][2] + 7 * (1 + .05 * a.get("cubes", 0))) >
                self.config["weapons"]["laser"]["range"] + 10
                and "mortar" not in a.get("weapons", ()) for a, _ in threats
            )
            self.launching = (protected > exposed or range_denial) and clear_ascent and reserve > 2
        if self.launching and (remain <= 0 or energy < 0.8 or d > max(3.5, zone["radius"] * 0.75)):
            self.launching = False
            self.landing = anchor
        if self.landing is not None:
            if me["grounded"]:
                self.landing = None
            else:
                # If the center is obstructed at this height, descend toward the
                # closest reachable point on the inward side of the storm.
                if time.perf_counter() < deadline and not self.arena.air_lane(p[:2], self.landing, p[2], size):
                    candidates = [(p[0] + 4 * dx, p[1] + 4 * dy) for dx, dy in ANGLES]
                    valid = [q for q in candidates if time.perf_counter() < deadline and self.arena.air_lane(p[:2], q, p[2], size)]
                    self.landing = min(valid, key=lambda q: distance(q, anchor), default=p[:2])
                return True, self.landing
        if self.launching:
            act["jump"] = bool(me["grounded"])
            act["boost"] = not me["grounded"] and jet_pulse(me["vel"][2], energy, stats)
            return True, anchor
        return False, goal

    def travel_waypoint(self, p, goal, size, now, start):
        """Prefer a clear segment and retain detours long enough to round a wall."""
        d = distance(p, goal)
        if d < .1:
            return goal
        span = min(d, 65)
        limit = (p[0] + (goal[0] - p[0]) * span / d, p[1] + (goal[1] - p[1]) * span / d)
        if self.arena.walk(p[:2], limit, size) and (span == d or not self.path):
            self.detour = None
            self.path.clear()
            return goal
        changed = self.path_goal is None or distance(goal, self.path_goal) > 15
        if changed:
            self.path.clear()
            self.detour = None
        if (changed or not self.path or now - self.path_update > 1.6) and time.perf_counter() < start + .023:
            new_path = self.arena.route(p[:2], goal, round(size, 2), start + .028)
            if new_path or changed:
                self.path = new_path
            self.path_goal, self.path_update = goal, now
        while self.path and distance(p, self.path[0]) < 1.5:
            self.path.pop(0)
        for node in reversed(self.path[:4]):
            if self.arena.walk(p[:2], node, size):
                return node
        if self.detour and distance(p, self.detour) > 2 and self.arena.walk(p[:2], self.detour, size):
            return self.detour
        ideal = bearing(p, goal)
        best, value = None, -math.inf
        for radius in (9, 4):
            for dx, dy in ANGLES:
                if time.perf_counter() >= start + .033:
                    break
                q = p[0] + dx * radius, p[1] + dy * radius
                if self.arena.walk(p[:2], q, size):
                    score = d - distance(q, goal) + .3 * radius
                    if score > value:
                        best, value = q, score
            if best is not None:
                break
        if best is not None:
            self.detour = best
            return best
        return self.path[0] if self.path else (p[0] + math.cos(ideal), p[1] + math.sin(ideal))

    def cross_obstacle(self, act, me, goal, zone, size, now, deadline):
        p, stats = me["pos"], me["stats"]
        if self.crossing is None:
            if (not me["grounded"] or now < self.crossing_retry or me["energy"] < 52
                    or not self.last_progress or now - self.last_progress[0] < 1.4):
                return False, goal
            self.crossing_retry = now + 7
            plan = self.arena.jet_crossing(p, goal, size, stats, me["energy"], zone, deadline)
            if plan is None:
                return False, goal
            landing, height = plan
            self.crossing = (p[:2], landing, height, now, False)
            act["jump"] = True
            return True, p[:2]

        start, landing, height, since, traversing = self.crossing
        d = distance(p, landing)
        if now - since > 6 or me["grounded"] and now - since > .25:
            self.crossing = None
            return False, goal
        traversing = traversing or p[2] >= height - .4
        self.crossing = start, landing, height, since, traversing
        if not me["grounded"] and d > 1.5 and me["energy"] > 8:
            act["boost"] = (p[2] < height + 1
                            and jet_pulse(me["vel"][2], me["energy"], stats))
        return True, landing if traversing or me["energy"] < 8 else start

    @staticmethod
    def center_control(me, anchor):
        """Brake on approach instead of crossing a small circle at full speed."""
        p, vel, stats = me["pos"], me["vel"], me["stats"]
        accel = stats["ground_accel"] if me["grounded"] else stats["air_accel"]
        speed = stats["walk_speed"]
        dx, dy = anchor[0] - p[0], anchor[1] - p[1]
        d = math.hypot(dx, dy)
        lookahead = (0.12 if me["grounded"] else .4)
        want_x, want_y = dx / lookahead, dy / lookahead
        limit = min(speed, math.sqrt(2 * accel * d) * .85)
        magnitude = math.hypot(want_x, want_y)
        if magnitude > limit and magnitude > 0:
            want_x *= limit / magnitude
            want_y *= limit / magnitude
        # Compensate for inertia when the current velocity points across the goal.
        if d < 1.5:
            want_x -= min(1, 1.5 - d) * .20 * vel[0]
            want_y -= min(1, 1.5 - d) * .20 * vel[1]
        scale = max(speed, math.hypot(want_x, want_y))
        return [want_x / scale, want_y / scale]

    def act(self, obs):
        started = time.perf_counter()
        now, me, zone = obs["t"], obs["self"], obs["zone"]
        p, stats = me["pos"], me["stats"]
        size = 1 + 0.05 * me["cubes"]
        hp = me["hp"] / me["max_hp"]
        origin = (p[0], p[1], p[2] + stats["muzzle_height"])
        self.remember(obs, now)
        act = {"tick": obs["tick"], "move": [0, 0], "fire": [False, False]}
        enemies = [a for a in obs["mechs"] if a["kind"] == "mech"]
        if enemies:
            self.last_enemy_seen = now
        enemies.sort(key=lambda a: distance(p, a["pos"]) - (28 if "laser" in a.get("weapons", ()) else 0)
                     - (24 if a.get("charging") else 0))
        visible = enemies[0] if enemies else None
        attacking_npcs = npc_pressure(me, obs["mechs"], self.arena, now,
                                     self.last_npc_damage, self.last_npc_attacker)
        threats = [(a, 2.4 if a.get("charging") else 1.6 if "laser" in a.get("weapons", ()) else 1)
                   for a in enemies if distance(p, a["pos"]) < (
                       280 if "laser" in a.get("weapons", ()) else 235)]
        for npc in attacking_npcs[:3]:
            threats.append((npc,.9))
        if not threats and now - self.last_damage < 4:
            old = [(a, seen) for a, seen in self.memory["mechs"].values() if a["kind"] == "mech"]
            if old:
                a, _ = min(old, key=lambda entry: distance(p, entry[0]["pos"]))
                threats.append((a, 1.3))
        nearest = min((distance(p, a["pos"]) for a in enemies), default=999)
        slots = {weapon["kind"]: i for i, weapon in enumerate(me["weapons"]) if weapon}
        slot = next((slots[k] for k in ("laser", "lightning", "mortar") if k in slots), 1)
        second = me["weapons"][slot]
        kind = second["kind"] if second else None
        arc = me["weapons"][slots["lightning"]] if "lightning" in slots else None
        own_laser_charging = bool(kind=="laser" and second.get("charge",0)>0)
        weapon_values = dict(WEAPONS, laser=4 if nearest > 85 else 2,
                             lightning=3, mortar=int(nearest > 50 and not any(
                                 "laser" in e.get("weapons", ()) for e in enemies)))
        if kind in ("laser", "lightning"):
            for complementary in ("laser", "lightning"):
                if complementary not in slots:
                    weapon_values[complementary] = 5
        if arc and kind == "laser":
            weapon_values["lightning"] = 0
        final = zone["next_radius"] <= 0
        goal = tuple(zone["next_center"])
        margin = zone["radius"] - distance(p, zone["center"])
        next_margin = zone["next_radius"] - distance(p, goal)
        remain = max(0, zone["shrink_end"] - now)
        walk_speed = stats["walk_speed"]
        # Forecast *routed* time into the NEXT circle, not just Euclidean
        # distance. Cache expensive path checks to protect the 50-ms deadline.
        needed = max(0.0, -next_margin + 16.0)
        transit = needed / max(1.0, walk_speed * .72)
        if not final and needed > 0:
            if now - self.zone_eta_cache[1] < 1.2:
                transit = self.zone_eta_cache[0]
            else:
                dcenter = max(.01, distance(p, zone["next_center"]))
                radius = max(0.0, zone["next_radius"] - 16)
                q = (zone["next_center"][0] + (p[0]-zone["next_center"][0])*radius/dcenter,
                     zone["next_center"][1] + (p[1]-zone["next_center"][1])*radius/dcenter)
                direct = False
                path_points = None
                if time.perf_counter() < started + .008:
                    direct = self.arena.walk(p[:2], q, size)
                    if not direct and time.perf_counter() < started + .009:
                        partial = self.arena.route(p[:2], q, round(size, 2), started + .012)
                        if partial and self.arena.walk(partial[-1], q, size):
                            path_points = [p[:2]] + partial + [q]
                transit = zone_eta(needed, direct, path_points, walk_speed)
                if not direct:
                    transit = max(transit, zone_eta(needed, False, None, walk_speed))
                self.zone_eta_cache = (transit, now)
        pressure_margin = 4 if not threats else 9 + min(14, len(threats) * 3)
        urgent = not me["in_zone"] or (not final and (
            margin < 12 or (next_margin < 16 and transit + pressure_margin >= remain)
        ))
        if not final and not urgent:
            d = distance(p, goal)
            safe_radius = max(0, zone["next_radius"] - min(38, zone["next_radius"] * 0.4))
            if d > 0.1:
                offset = min(d, safe_radius) / d
                goal = (goal[0] + (p[0] - goal[0]) * offset, goal[1] + (p[1] - goal[1]) * offset)
        anchor = goal
        # Only open enemy firing lanes count toward immediate danger.
        # Visible-but-occluded house bots must not permanently disable farming.
        charging_now = any(a.get("charging") for a in enemies)
        if (self.danger_cache is None or now-self.danger_update > .25 or charging_now):
            if time.perf_counter() < started + .014:
                self.danger_cache = classify_danger(me, enemies, self.arena)
                self.danger_update = now
        danger = self.danger_cache or {
            "exposed":len(threats), "near":len(threats),
            "lasers":0, "charging":int(charging_now), "closest":nearest}
        laser_threat = danger["lasers"] > 0
        estimates = {enemy["id"]: duel(me, enemy, self.config["weapons"], len(threats)) for enemy in enemies}
        new_mode = next_mode(self.mode, hp, danger, urgent, now,
                             self.last_damage, self.last_hit,
                             has_objective=self.resource_lock is not None,
                             has_cover=danger["exposed"] == 0)
        # Keep V5's more aggressive, higher-scoring baseline. Only override
        # when a nearby NPC would continually reset the regeneration timer.
        if attacking_npcs and not urgent:
            if hp < .72:
                new_mode="EVADE"
            elif not enemies and hp > .78:
                new_mode="FIGHT"
        # HEAL is not safe when a bullet/shell is on a collision course.
        if (new_mode=="HEAL" and not urgent and not final and
                imminent_projectile(me,obs["projectiles"],zone)):
            new_mode="EVADE"
        if new_mode != self.mode:
            self.mode, self.mode_since = new_mode, now
        retreat = self.mode in ("EVADE", "HEAL")
        # EVADE is active defense, not a regeneration hold. Permit a
        # close-range lightning short to stop a charging laser. Only HEAL
        # requires absolute no-fire discipline to restart regeneration.
        self.recovering = self.mode == "HEAL"
        objective = None
        self.foliage_active = False
        if retreat and threats and not urgent and (not final or distance(p, goal) < 6 and remain > 20):
            cover = self.cover_point(p, threats, zone, size, anchor, now, started + 0.009)
            if cover is not None and (not final or distance(cover, anchor) < 7):
                goal = cover
            elif visible and not final:
                # A dense canopy can hide the entire nine-meter mech from
                # distant FOV vision, even when a normal hard cover path
                # is unavailable. Proximity sensors ignore the canopy.
                if (not attacking_npcs and not charging_now and
                        not own_laser_charging and
                        nearest>54 and hp<.82 and now<325 and
                        zone["next_radius"]>70 and me["grounded"]):
                    if (now-self.foliage_scan_at>1.5 and
                            time.perf_counter()<started+.012):
                        self.foliage_scan_at=now
                        found=self.foliage.refuge(
                            me,enemies,zone,self.arena,started+.022)
                        if found is not None:
                            self.foliage_score,self.foliage_goal,_=found
                            self.foliage_until=now+8.
                    if (self.foliage_goal is not None and
                            now<self.foliage_until and
                            distance(p,self.foliage_goal)<35 and
                            distance(self.foliage_goal,zone["next_center"])
                            <zone["next_radius"]-15):
                        goal=self.foliage_goal
                        self.foliage_active=True
                if not self.foliage_active:
                    away = bearing(visible["pos"], p)
                    options = [(p[0] + 14 * math.cos(away + off), p[1] + 14 * math.sin(away + off))
                               for off in (0.85, -0.85, 1.45, -1.45, 0)]
                    if now >= self.evade_until:
                        self.evade_side *= -1
                        self.evade_until = now + 0.75 + (me["id"] % 4) * 0.12
                    side = bearing(visible["pos"], p) + self.evade_side * 1.30
                    options.insert(0, (p[0] + 17 * math.cos(side), p[1] + 17 * math.sin(side)))
                    allowed = [q for q in options if distance(q, zone["center"]) < zone["radius"] - 7
                               and self.arena.walk(p[:2], q, size)]
                    if allowed:
                        goal = min(allowed, key=lambda q: distance(q, anchor) * 0.85
                                   - 0.95 * distance(q, visible["pos"]) - (6 if q == options[0] and laser_threat else 0))
        elif (not urgent and not final and not (obs["alive"]<=6 and now>220)
              and self.mode in ("TRAVEL","FARM") and
              (danger["exposed"] == 0 or
               danger["exposed"] == 1 and nearest > 130 and not laser_threat and hp > .8) and
              time.perf_counter() < started + 0.013):
            objective = self.objective(obs, enemies, kind, p, zone, now, weapon_values)
            if objective:
                self.mode = "FARM"
                group, _, q = objective
                if group in ("crates", "mechs"):
                    goal = self.resource_waypoint(p, q, group, size, stats, started + .016)
                else:
                    goal = q[:2]
            elif nearest > 95 and now < 325 and distance(goal, p) < 8:
                cx, cy = zone["next_center"]
                phase = int(now / 9) * 2.399963 + me["id"]
                radius = min(75, zone["next_radius"] * 0.48)
                goal = (cx + math.cos(phase) * radius, cy + math.sin(phase) * radius)
        if (should_skirmish(self.mode, visible, retreat, urgent, final, nearest)
                and not attacking_npcs):
            # Close with lightning only when we can shut down an isolated
            # laser. Otherwise hold arc range or regain space.
            enemy_pos = visible["pos"]
            away = bearing(enemy_pos, p)
            if now >= self.evade_until:
                self.evade_side *= -1
                self.evade_until = now + 0.85 + (me["id"] % 4) * 0.13
            radial = -0.30 if nearest < 38 else 0.0
            if arc:
                arc_range = arc["stats"]["range"]
                equipment = visible.get("weapons", ())
                can_short = (danger["exposed"] == 1 and len(threats) == 1 and
                             hp > .75 and me["energy"] > arc["stats"]["energy"] + 20 and
                             "laser" in equipment and "mortar" not in equipment)
                if can_short and .67 * arc_range < nearest < arc_range + 14:
                    radial = .46
                elif "mortar" not in equipment and .60 * arc_range <= nearest < arc_range - 3:
                    radial = 0.0
            for side in (self.evade_side, -self.evade_side):
                angle = away + (math.pi / 2 + radial) * side
                q = p[0] + 14 * math.cos(angle), p[1] + 14 * math.sin(angle)
                if distance(q, zone["center"]) < zone["radius"] - 18 and self.arena.walk(p[:2], q, size):
                    goal = q
                    break
        # Persist the hiding contract after opponents disappear from our
        # observations. They may still have perfect tracked positions for
        # the five-second memory window; abandoning concealment immediately
        # would make the entire maneuver pointless.
        if (self.foliage_goal is not None and now<self.foliage_until and
                not urgent and not final and zone["dps"]<100 and
                me["in_zone"] and not attacking_npcs and nearest>=51 and
                (hp<.96 or now-self.last_enemy_seen<5.6) and
                not danger.get("charging") and
                not own_laser_charging and
                (now-self.last_damage>1.2 or
                 distance(p,self.foliage_goal)>4.)):
            self.foliage_active=True
            goal=self.foliage_goal
            objective=None
            if distance(p,self.foliage_goal)<4:
                self.mode="HEAL"
                retreat=True
                self.recovering=True
        if self.foliage_active and (nearest<51 or attacking_npcs or
                                    own_laser_charging or
                                    urgent or final or zone["dps"]>=100):
            self.foliage_active=False
            self.foliage_until=now
        if retreat and attacking_npcs and not urgent and not final:
            escape = immediate_npc_escape(me, attacking_npcs[0],
                                          zone, self.arena, size)
            if escape is not None:
                goal = escape
        if retreat and not urgent and not final and hp > .38 and nearest > 23:
            safe_cubes = [cube["pos"] for cube in obs["cubes"]
                          if 3 < distance(p, cube["pos"]) < 9 and abs(p[2] - cube["pos"][2]) < 3.8
                          and distance(cube["pos"], zone["next_center"]) < zone["next_radius"]
                          and all(distance(cube["pos"], e["pos"]) > 18 for e, _ in threats[:3])
                          and self.arena.walk(p[:2], cube["pos"][:2], size)]
            if safe_cubes:
                goal = min(safe_cubes, key=lambda q: distance(q, p))[:2]
        if (retreat and visible and not attacking_npcs and
                not self.foliage_active and not urgent and not final and
                objective is None and time.perf_counter()<started+.014):
            screened = storm_screen(self.arena, p, visible, zone, size, started + .016)
            if screened is not None:
                goal = screened
        if obs["offer"]:
            priorities = {"nanites": 100 if now < 340 else 35, "plating": 92, "servos": 77, "armor": 75,
                          "gun_mag": 74 if now < 205 else 61, "jets": 67 if now < 360 else 82,
                          "lightning_range": 70, "gun_damage": 65, "laser_charge": 66, "capacitor": 65,
                          "reactor": 60, "sensors": 49, "gyros": 48, "laser_damage": 62, "gun_rate": 59}
            choices = obs["offer"]["choices"]
            act["pick"] = upgrade_scoremax(choices, me, now, zone)
        pickups = [item for item in obs["pickups"] if distance(p, item["pos"]) < self.config["loot"]["pickup_radius"] - 0.1
                   and abs(p[2] - item["pos"][2]) < 3.9 and weapon_values[item["kind"]] > weapon_values.get(kind, 0)]
        if kind == "mortar" and laser_threat and not pickups:
            act["drop"] = slot
        if pickups and not own_laser_charging and (
            not second or kind == "mortar" or nearest > 35 and now - self.last_damage > 3
        ):
            pickup = max(pickups, key=lambda item: weapon_values[item["kind"]])
            act["take"] = pickup["id"]
            if len(slots) == len(me["weapons"]):
                keeps_pair = {kind, pickup["kind"]} == {"laser", "lightning"}
                act["drop"] = slots.get("gun", slot) if keeps_pair else slot
        capture = self.finish_capture(obs, enemies) if not urgent and not final else None
        if capture:
            goal = tuple(capture["pos"][:2])
            self.foliage_active = False
        roof = self.arena.roof(*anchor) if final else -math.inf
        flight = False
        if final:
            flight, goal = self.final_movement(act, me, threats, p, anchor, goal, roof, remain,
                                               zone, size, now, started + 0.019)
        elif not capture and objective and objective[0] in ("cubes", "pickups") and not threats:
            elevated = objective[2]
            if elevated[2] - p[2] > 4 and elevated[2] - self.arena.ground(*elevated[:2]) > 4:
                flight, goal = self.final_movement(act, me, [], p, tuple(elevated[:2]), goal,
                                                   self.arena.roof(*elevated[:2]), max(18, remain),
                                                   zone, size, now, started + .019)
        if (not capture and not self.foliage_active and retreat and
                not final and not urgent and hp<.68 and
                time.perf_counter()<started+.017):
            refuge = self.recovery_roof(me, threats, zone, size, now, started + .019)
            if refuge is not None:
                q = tuple(refuge[:2])
                level = self.arena.roof(*q)
                if p[2] >= level - .3 and distance(p, q) < 4 and me["grounded"]:
                    goal = q
                    self.recovering = True
                else:
                    airborne, safe_goal = self.final_movement(
                        act, me, [], p, q, q, level, max(18, remain), zone, size, now, started + .022
                    )
                    if airborne or self.roof_plan:
                        flight, goal = airborne, safe_goal
                        self.recovering = True
        elif not retreat or hp > .8:
            self.refuge = None
        if not capture and not final and not flight and (self.crossing or
                                          (not laser_threat and distance(p, goal) > 12 and nearest > 36)):
            flight, goal = self.cross_obstacle(act, me, goal, zone, size, now, started + .022)
        target = None
        if not flight:
            # A charging laser must retain its target while it slews/charges.
            if second and second["kind"] == "laser" and second.get("charge", 0) and self.laser_target is not None:
                target = next((a for a in (*obs["mechs"], *obs["crates"])
                               if a["id"] == self.laser_target), None)
            # The selected resource must be the thing we shoot, otherwise
            # the bot circles a crate while shooting a 1400-HP house bot.
            if target is None and self.mode == "FARM":
                target = candidate_resource_target(objective, obs)
            # Resource routes are not an excuse to aggro the cooperative
            # house squad. When FARM is collecting loose cubes, a weapon or
            # a supply drop, do not shoot a mech just because it is visible.
            # An exposed attacker already forces a transition out of FARM.
            scavenging = self.mode == "FARM" and objective is not None and (
                objective[0] in ("cubes", "pickups", "drop"))
            if target is None and enemies and not scavenging:
                # Final-center contest is a territory fight: an enemy whose
                # collision cylinder can displace us outranks distant DPS.
                contesting = [a for a in enemies if
                              contest_center(me,a,zone,now,retreat)]
                candidates = sorted(enemies, key=lambda a: distance(p, a["pos"]) * .28
                             + min(40, estimates[a["id"]][0]) * 2 + min(1200, estimates[a["id"]][1]) * .02
                             - (rear_laser_bonus(a, p, self.config["sound"]["range"]["laser_charge"],
                                                 math.radians(self.config["vision"]["fov_deg"])) if kind == "laser" else 0)
                             - (55 if arc and a.get("charging") and distance(p, a["pos"]) < arc["stats"]["range"] - 1 else 0))
                if contesting:
                    candidates = (sorted(contesting,
                        key=lambda e: distance(e["pos"],zone["next_center"]))+
                        [e for e in candidates if e not in contesting])
                # The ambush must actually be selected as the target.
                if kind=="laser" and not retreat and now<320:
                    sniper=sniper_choice(me,enemies,zone,now,obs["alive"],
                                         one_shot_laser_ambush)
                    if sniper is not None and sniper["id"]!=candidates[0]["id"]:
                        candidates=[sniper]+[e for e in candidates if e["id"]!=sniper["id"]]
                target = next((enemy for enemy in candidates[:3] if self.arena.shot(
                    origin, (*enemy["pos"][:2], enemy["pos"][2] + 4.5 * (1 + .05 * enemy.get("cubes", 0)))
                )), candidates[0])
            if target is None and objective and objective[0] in ("mechs", "crates"):
                target = candidate_resource_target(objective, obs)
            if target is None and not scavenging and (not final or remain > 18):
                nuisance = [a for a in obs["mechs"] if a["kind"] == "npc"
                            and distance(a["pos"], p) < (65 if attacking_npcs else 43)]
                if nuisance:
                    target = min(nuisance, key=lambda a: distance(p, a["pos"]))
        priority_enemy = None if (target is not None and target.get("kind") in ("npc", "crate")
                                  and self.mode == "FARM") else visible
        self.combat(act, obs, origin, target, retreat, urgent,
                    final and (hp < .86 or remain < 12) and
                    (not target or target.get("kind") != "npc"), priority_enemy)
        if (self.foliage_active and nearest>100 and
                not danger.get("charging") and not attacking_npcs):
            # No weapon report may betray our silent canopy retreat.
            # Enemies with a direct close-range threat override this.
            act["fire"]=[False,False]
            act["reload"]=False
        if not target:
            if threats:
                act["aim"] = [bearing(p, threats[0][0]["pos"]), 0]
            elif any(sound["kind"] in ("laser", "gun", "lightning") and sound["dist"] == "near" for sound in obs["sounds"]):
                recent = min((sound for sound in obs["sounds"] if sound["kind"] in ("laser", "gun", "lightning")
                              and sound["dist"] == "near"), key=lambda sound: sound["age"])
                act["aim"] = [recent["bearing"], 0]
            elif now - self.last_damage < 3 and self.damage_bearing is not None:
                act["aim"] = [self.damage_bearing, 0]
            else:
                sweep = (now % 7) * math.tau / 1.8 if now % 7 < 1.8 and not urgent else 0
                act["aim"] = [bearing(p, goal) + sweep, 0]
        if threats and (retreat or flight or urgent) and not any(act["fire"]) and kind != "mortar":
            risks = [(bearing(p, a["pos"]), weight / (1 + distance(p, a["pos"]) / 120)) for a, weight in threats]
            for projectile in obs["projectiles"][:12]:
                q, v = projectile["pos"], projectile["vel"]
                if distance(p, q) < 55 and (p[0] - q[0]) * v[0] + (p[1] - q[1]) * v[1] > 0:
                    risks.append((math.atan2(-v[1], -v[0]), 1.5 if projectile["kind"] == "mortar" else 0.4))
            yaw = defensive_yaw(me["aim"][0], risks, stats["turn_rate"])
            # Keep tracking a viable return shot when it also faces incoming fire.
            if not target or angle_delta(yaw, act["aim"][0]) > 1.0:
                act["aim"] = [yaw, 0]
        goal = tuple(goal)
        d = distance(p, goal)
        straight = 0.0
        if d > 0.18 or final and not me["grounded"]:
            waypoint = self.travel_waypoint(p, goal, size, now, started) if not flight and me["grounded"] else goal
            straight = distance(p, waypoint)
            dx, dy = waypoint[0] - p[0], waypoint[1] - p[1]
            if (final or flight) and not me["grounded"]:
                dx = 0.30 * dx - 0.24 * me["vel"][0]
                dy = 0.30 * dy - 0.24 * me["vel"][1]
            length = math.hypot(dx, dy)
            divisor = max(6 if flight and final else 3.3, length)
            act["move"] = [dx / divisor, dy / divisor]
        center_lock = (final and distance(goal, anchor) < .05 and distance(p, anchor) < 4
                       and (not me["grounded"] or self.arena.walk(p[:2], anchor, size)))
        if center_lock:
            act["move"] = self.center_control(me, anchor)
        if not center_lock and not flight and me["grounded"] and (not self.recovering or math.hypot(*act["move"]) > .1) and (not final or urgent) and time.perf_counter() < started + 0.028:
            holding_laser = kind == "laser" and act["fire"][slot] and (
                own_laser_charging or second["cooldown"] <= .1
            )
            speed_scale = self.config["mech"]["charge_move_mult"] if holding_laser else 1.0
            direction, tactical_boost = choose_movement(
                self.arena, me, zone, act["move"], threats, obs["projectiles"],
                size, urgent, started + 0.032, capture, now, speed_scale=speed_scale,
            )
            act["move"] = list(direction)
            emergency_storm = not me["in_zone"] or (zone["dps"] >= 100 and margin < 3)
            floor = energy_floor(me, emergency_storm)
            act["boost"] = bool((tactical_boost and me["energy"] > min(floor, 20)) or
                                (urgent and d > 4 and me["energy"] > floor))
        elif not center_lock and not flight and urgent and me["grounded"] and d > 6:
            act["boost"] = me["energy"] > energy_floor(
                me, not me["in_zone"] or (zone["dps"] >= 100 and margin < 3))
        charging = bool(second and second.get("charge"))
        safe_travel = (not capture and me["grounded"] and not flight and not final and not retreat and not urgent and
                       not charging and not any(act["fire"]) and nearest > 110 and now - self.last_damage > 4
                       and straight > 20 and self.arena.walk(p[:2], (
                           p[0] + act["move"][0] * 17, p[1] + act["move"][1] * 17), size))
        reserve = energy_floor(me)
        if self.ground_boost.active(now, me["energy"], stats, reserve, safe_travel):
            act["boost"] = True
        # Canopy approach: move quickly into optical cover, then stay silent
        # for the five-second shared tracking window. Do not fire/reload/
        # jet/boost while actually hiding, or sound reveals our position.
        if (self.foliage_active and self.foliage_goal is not None and
                distance(p,self.foliage_goal)<3.5 and
                nearest>51 and not attacking_npcs and
                not urgent and me["in_zone"]):
            act["move"]=stealth_vector(me,self.foliage_goal)
            act["boost"]=False
            act["jump"]=False
            act["fire"]=[False,False]
            act["reload"]=False
            self.recovering=True
        if not capture and me["grounded"] and d > 10 and not flight:
            if self.last_progress is None or distance(p, self.last_progress[1]) > 3:
                self.last_progress = (now, p)
            elif now - self.last_progress[0] > 1 and me["energy"] > 43:
                act["jump"] = True
                self.last_progress = (now, p)
        else:
            self.last_progress = None
        return act


if __name__ == "__main__":
    mf.run(Bot)
