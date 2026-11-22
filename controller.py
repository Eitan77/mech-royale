"""Resource-first controller with cover-aware movement and a timed endgame."""
import math
import time

from arena import Arena
from pilot import choose_movement
import mechfight as mf
from mobility import GroundBoost, defensive_yaw, jet_pulse, project_ascent, rear_laser_bonus

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
    name = "clover-v4-pilot"

    def __init__(self, hello):
        self.config = hello["config"]
        self.arena = Arena(hello["map"]["dir"])
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
                if event.get("bearing") is not None:
                    self.damage_bearing = event["bearing"]
            elif kind == "hit":
                self.last_hit = now
            elif kind == "kill":
                self.memory["mechs"].pop(event["target"], None)
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

    def objective(self, obs, enemies, weapon, p, zone, now, weapon_values):
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
                score = 17 + (1 - hp) * 36 - 2.3 * eta - 0.6 * max(0, drop["lands_in"] - eta - 3)
                if score > best_score:
                    best, best_score = ("drop", drop["id"], q), score
        for group in ("cubes", "pickups", "crates", "mechs"):
            for ident, (item, seen) in self.memory[group].items():
                q = item["pos"]
                d = distance(p, q)
                if d > 130 or distance(q, zone["next_center"]) > zone["next_radius"] + max(0, zone["shrink_end"] - now) * 3:
                    continue
                if abs(q[2] - self.arena.ground(*q[:2])) > 5 and abs(q[2] - p[2]) > 4:
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
        return best

    def gun_solution(self, origin, actor, stats):
        p = actor["pos"]
        kind = actor.get("kind", "crate")
        size = 1 + 0.05 * actor.get("cubes", 0)
        height = {"mech": 4.5 * size, "npc": self.config["npc"]["height"] * 0.5, "crate": 0.8}[kind]
        body = (p[0], p[1], p[2] + height)
        lead = intercept(origin, body, actor.get("vel", (0, 0, 0)), stats["speed"])
        return body, lead

    def combat(self, act, obs, origin, target, retreat, urgent, final, primary_threat):
        me = obs["self"]
        cfg = self.config["mech"]
        gun = next((w for w in me["weapons"] if w and w["kind"] == "gun"), None)
        secondary = next((w for w in me["weapons"] if w and w["kind"] in ("laser", "lightning")), None)
        charge = secondary.get("charge", 0) if secondary else 0
        if not target:
            act["reload"] = bool(gun and gun.get("ammo", 0) <= 6)
            self.laser_target = None
            return
        d = distance(origin, target["pos"])
        body, lead = self.gun_solution(origin, target, gun["stats"] if gun else self.config["weapons"]["gun"])
        laser = secondary and secondary["kind"] == "laser"
        lightning = secondary and secondary["kind"] == "lightning"
        aim_point = body if laser and (charge or not retreat and secondary["cooldown"] <= 0.15) else lead
        if lightning and d < secondary["stats"]["range"] - 1 and not gun:
            aim_point = body
        yaw = bearing(origin, aim_point)
        pitch = math.atan2(aim_point[2] - origin[2], distance(origin, aim_point))
        act["aim"] = [yaw, max(cfg["min_pitch"], min(cfg["max_pitch"], pitch))]
        error = angle_delta(yaw, me["aim"][0])
        pitch_error = abs(pitch - me["aim"][1])
        allowed_pitch = cfg["min_pitch"] <= pitch <= cfg["max_pitch"]
        hit_tolerance = max(0.019, min(0.38, 2.3 / max(1, d)))
        if target.get("kind") == "mech":
            hit_tolerance *= 1 + 0.05 * target.get("cubes", 0)
        aligned = max(error, pitch_error) < hit_tolerance and allowed_pitch
        clear = allowed_pitch and self.arena.shot(origin, aim_point)
        finishing = target.get("kind") == "mech" and target.get("hp", 1400) < 145 and d < 60
        is_rear_duel = target.get("kind") == "mech" and angle_delta(target["aim"][0], bearing(target["pos"], origin)) > 2.0
        offensive = not (urgent or final) and (not retreat or is_rear_duel) or finishing
        is_mech = target.get("kind") == "mech"
        # Running and firing the arm gun are independent. Only preserve silence
        # for an actual disengagement or committed final-circle recovery.
        return_fire = is_mech and (not final or urgent) and d < 225
        if gun and aim_point != lead:
            gun_yaw = bearing(origin, lead)
            gun_pitch = math.atan2(lead[2] - origin[2], distance(origin, lead))
            gun_aligned = max(angle_delta(gun_yaw, me["aim"][0]), abs(gun_pitch - me["aim"][1])) < hit_tolerance
            gun_clear = gun_aligned and self.arena.shot(origin, lead)
        else:
            gun_aligned, gun_clear = aligned, clear
        for i, weapon in enumerate(me["weapons"]):
            if not weapon:
                continue
            kind, stats = weapon["kind"], weapon["stats"]
            if kind == "gun":
                act["fire"][i] = bool((offensive or return_fire) and gun_aligned and gun_clear and d < stats["range"] - 3)
            elif kind == "lightning":
                short = target.get("charging", False) and "laser" in target.get("weapons", ())
                reserve = 18 if retreat else 12
                act["fire"][i] = bool((offensive or return_fire or short) and error < math.radians(stats["cone_deg"]) * 0.38
                                      and d < stats["range"] - 0.5 and self.arena.shot(origin, body)
                                      and me["energy"] > stats["energy"] + (3 if short else reserve))
            elif kind == "laser":
                same_target = self.laser_target == target["id"]
                if charge:
                    act["fire"][i] = bool(offensive and same_target and clear and (
                        charge < stats["charge"] - 0.05 or (not aligned and error < 0.12 and not urgent)
                    ))
                else:
                    act["fire"][i] = bool(offensive and not urgent and clear and allowed_pitch and error < 0.10
                                          and 2 < d < stats["range"] - 3 and weapon["cooldown"] <= 0.1
                                          and (target.get("kind") == "mech" or not primary_threat))
                    if act["fire"][i]:
                        self.laser_target = target["id"]
        if gun and gun.get("ammo", 0) <= 4 and (not gun_clear or not is_mech) and not any(act["fire"]):
            act["reload"] = True

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
        flight_window = 2 < remain < min(17, energy / stats["jet_drain"] * 1.35)
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
            self.launching = protected > exposed and clear_ascent and reserve > 2
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
        enemies.sort(key=lambda a: distance(p, a["pos"]) - (28 if "laser" in a.get("weapons", ()) else 0)
                     - (24 if a.get("charging") else 0))
        visible = enemies[0] if enemies else None
        threats = [(a, 2.4 if a.get("charging") else 1.6 if "laser" in a.get("weapons", ()) else 1)
                   for a in enemies if distance(p, a["pos"]) < 235]
        if not threats and now - self.last_damage < 4:
            old = [(a, seen) for a, seen in self.memory["mechs"].values() if a["kind"] == "mech"]
            if old:
                a, _ = min(old, key=lambda entry: distance(p, entry[0]["pos"]))
                threats.append((a, 1.3))
        nearest = min((distance(p, a["pos"]) for a in enemies), default=999)
        slot = next((i for i, w in enumerate(me["weapons"]) if w and w["kind"] != "gun"), 1)
        second = me["weapons"][slot]
        kind = second["kind"] if second else None
        weapon_values = dict(WEAPONS, laser=3 if nearest > 85 else 1)
        final = zone["next_radius"] <= 0
        goal = tuple(zone["next_center"])
        margin = zone["radius"] - distance(p, zone["center"])
        next_margin = zone["next_radius"] - distance(p, goal)
        remain = max(0, zone["shrink_end"] - now)
        walk_speed = stats["walk_speed"]
        transit = max(0, -next_margin + 16) / max(1, walk_speed * 0.72)
        pressure_margin = 4 if not threats else 9 + min(14, len(threats) * 3)
        urgent = not me["in_zone"] or (not final and (
            margin < 13 or next_margin < 10 and transit + pressure_margin > remain
        ))
        if not final and not urgent:
            d = distance(p, goal)
            safe_radius = max(0, zone["next_radius"] - min(38, zone["next_radius"] * 0.4))
            if d > 0.1:
                offset = min(d, safe_radius) / d
                goal = (goal[0] + (p[0] - goal[0]) * offset, goal[1] + (p[1] - goal[1]) * offset)
        anchor = goal
        laser_threat = any("laser" in a.get("weapons", ()) for a, _ in threats)
        estimates = {enemy["id"]: duel(me, enemy, self.config["weapons"], len(threats)) for enemy in enemies}
        favorable = bool(visible and len(enemies) == 1 and estimates[visible["id"]][0] < 8
                         and estimates[visible["id"]][1] < min(me["hp"] * 0.33, 420))
        retreat = bool(threats and not favorable and (hp < 0.52 or len(enemies) >= 3 or laser_threat and (hp < 0.68 or len(enemies) >= 2)))
        if hp < 0.7 and now - max(self.last_damage, self.last_hit) < stats.get("regen_delay", 5) + 3 and threats:
            retreat = retreat or not favorable
        objective = None
        if retreat and not urgent and (not final or distance(p, goal) < 6 and remain > 20):
            cover = self.cover_point(p, threats, zone, size, anchor, now, started + 0.009)
            if cover is not None and (not final or distance(cover, anchor) < 7):
                goal = cover
            elif visible and not final:
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
        elif not urgent and not final and time.perf_counter() < started + 0.013:
            objective = self.objective(obs, enemies, kind, p, zone, now, weapon_values)
            if objective:
                group, _, q = objective
                d = distance(p, q)
                if group in ("crates", "mechs") and d > 0:
                    scale = min(d, 24 if group == "crates" else 32) / d
                    goal = (q[0] + (p[0] - q[0]) * scale, q[1] + (p[1] - q[1]) * scale)
                elif group in ("crates", "mechs"):
                    goal = p[:2]
                else:
                    goal = q[:2]
            elif nearest > 95 and now < 325 and distance(goal, p) < 8:
                cx, cy = zone["next_center"]
                phase = int(now / 9) * 2.399963 + me["id"]
                radius = min(75, zone["next_radius"] * 0.48)
                goal = (cx + math.cos(phase) * radius, cy + math.sin(phase) * radius)
        if visible and not retreat and not urgent and not final and 13 < nearest < 145:
            # Fight while moving across the enemy's aim, with an outward bias
            # against short-range weapons and an inward bias with our lightning.
            enemy_pos = visible["pos"]
            away = bearing(enemy_pos, p)
            if now >= self.evade_until:
                self.evade_side *= -1
                self.evade_until = now + 0.85 + (me["id"] % 4) * 0.13
            radial = 0.3 if nearest < 38 and kind != "lightning" else -0.32 if kind == "lightning" and nearest > 29 else 0
            for side in (self.evade_side, -self.evade_side):
                angle = away + (math.pi / 2 - radial) * side
                q = p[0] + 14 * math.cos(angle), p[1] + 14 * math.sin(angle)
                if distance(q, zone["center"]) < zone["radius"] - 18 and self.arena.walk(p[:2], q, size):
                    goal = q
                    break
        if obs["offer"]:
            priorities = {"nanites": 100 if now < 340 else 35, "plating": 92, "servos": 77, "armor": 75,
                          "gun_mag": 74 if now < 205 else 61, "jets": 67 if now < 360 else 82,
                          "lightning_range": 70, "gun_damage": 65, "laser_charge": 66, "capacitor": 65,
                          "reactor": 60, "sensors": 49, "gyros": 48, "laser_damage": 62, "gun_rate": 59}
            choices = obs["offer"]["choices"]
            act["pick"] = max(range(len(choices)), key=lambda i: priorities.get(choices[i]["id"], 40))
        pickups = [item for item in obs["pickups"] if distance(p, item["pos"]) < self.config["loot"]["pickup_radius"] - 0.1
                   and abs(p[2] - item["pos"][2]) < 3.9 and weapon_values[item["kind"]] > weapon_values.get(kind, 0)]
        if pickups and not (second and second.get("charge")) and (
            not second or kind == "mortar" or nearest > 35 and now - self.last_damage > 3
        ):
            act["take"] = max(pickups, key=lambda item: weapon_values[item["kind"]])["id"]
            if second:
                act["drop"] = slot
        roof = self.arena.roof(*anchor) if final else -math.inf
        flight = False
        if final:
            flight, goal = self.final_movement(act, me, threats, p, anchor, goal, roof, remain,
                                               zone, size, now, started + 0.019)
        target = None
        if not flight:
            if enemies:
                target = min(enemies, key=lambda a: distance(p, a["pos"]) * 0.28
                             + min(40, estimates[a["id"]][0]) * 2 + min(1200, estimates[a["id"]][1]) * 0.02
                             - (rear_laser_bonus(a, p, self.config["sound"]["range"]["laser_charge"],
                                                 math.radians(self.config["vision"]["fov_deg"])) if kind == "laser" else 0)
                             - (55 if kind == "lightning" and a.get("charging") and distance(p, a["pos"]) < 44 else 0))
            if objective and objective[0] in ("mechs", "crates") and (not target or nearest > 120 and not laser_threat):
                group, ident, _ = objective
                resource = next((a for a in obs[group] if a["id"] == ident), None)
                if resource:
                    target = resource
            if not target and (not final or remain > 18):
                nuisance = [a for a in obs["mechs"] if a["kind"] == "npc" and distance(a["pos"], p) < 43]
                if nuisance:
                    target = min(nuisance, key=lambda a: distance(p, a["pos"]))
        self.combat(act, obs, origin, target, retreat, urgent, final and (hp < 0.86 or remain < 12) and (not target or target.get("kind") != "npc"), visible)
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
        if threats and (retreat or flight or urgent) and not any(act["fire"]):
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
            waypoint = goal
            if not flight and me["grounded"] and d < 140 and not self.arena.walk(p[:2], goal, size):
                replan = self.path_goal is None or distance(goal, self.path_goal) > 10 or now - self.path_update > 1.1
                if replan and time.perf_counter() < started + 0.021:
                    self.path = self.arena.route(p[:2], goal, round(size, 2), started + 0.026)
                    self.path_goal, self.path_update = goal, now
                while self.path and distance(p, self.path[0]) < 3.0:
                    self.path.pop(0)
                for node in reversed(self.path[:3]):
                    if self.arena.walk(p[:2], node, size):
                        waypoint = node
                        break
                else:
                    if self.path:
                        waypoint = self.path[0]
            elif not flight and me["grounded"] and d >= 140:
                short = (p[0] + (goal[0] - p[0]) * 80 / d, p[1] + (goal[1] - p[1]) * 80 / d)
                if not self.arena.walk(p[:2], short, size):
                    if (not self.path or now - self.path_update > 0.8) and time.perf_counter() < started + 0.021:
                        self.path = self.arena.route(p[:2], short, round(size, 2), started + 0.026)
                        self.path_update, self.path_goal = now, short
                    while self.path and distance(p, self.path[0]) < 3:
                        self.path.pop(0)
                    if self.path:
                        waypoint = self.path[0]
            straight = distance(p, waypoint)
            dx, dy = waypoint[0] - p[0], waypoint[1] - p[1]
            if final and not me["grounded"]:
                dx = 0.30 * dx - 0.24 * me["vel"][0]
                dy = 0.30 * dy - 0.24 * me["vel"][1]
            length = math.hypot(dx, dy)
            divisor = max(6 if flight and final else 3.3, length)
            act["move"] = [dx / divisor, dy / divisor]
        if not flight and me["grounded"] and (not final or urgent) and time.perf_counter() < started + 0.028:
            direction, tactical_boost = choose_movement(
                self.arena, me, zone, act["move"], threats, obs["projectiles"], size, urgent, started + 0.032
            )
            act["move"] = list(direction)
            act["boost"] = bool(tactical_boost or urgent and d > 4 and me["energy"] > 7)
        elif not flight and urgent and me["grounded"] and d > 6 and me["energy"] > 6:
            act["boost"] = True
        charging = bool(second and second.get("charge"))
        safe_travel = (me["grounded"] and not flight and not final and not retreat and not urgent and
                       not charging and not any(act["fire"]) and nearest > 110 and now - self.last_damage > 4
                       and straight > 23 and self.arena.walk(p[:2], (
                           p[0] + act["move"][0] * 17, p[1] + act["move"][1] * 17), size))
        reserve = min(62, me["max_energy"] * 0.58)
        if self.ground_boost.active(now, me["energy"], stats, reserve, safe_travel):
            act["boost"] = True
        if retreat and not visible and not urgent and not flight and now - self.last_damage > 2.0:
            act["move"] = [value * 0.38 for value in act["move"]]
        if me["grounded"] and d > 10 and not flight:
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
