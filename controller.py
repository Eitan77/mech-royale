"""Resource-first controller with cover-aware movement and a timed endgame."""
import math
import time

from arena import Arena
import mechfight as mf

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


class Bot:
    name = "clover-v3"

    def __init__(self, hello):
        self.config = hello["config"]
        self.arena = Arena(hello["map"]["dir"])
        self.memory = {name: {} for name in ("crates", "cubes", "pickups", "mechs", "projectiles")}
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
        self.jet_roof = False

    def remember(self, obs, now):
        for group, ttl in (("crates", 45), ("cubes", 18), ("pickups", 50), ("mechs", 4), ("projectiles", 0.25)):
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
        if now - self.cover_update < 0.7 and self.cover is not None and distance(p, self.cover) < 45:
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
                protected = 0
                for enemy, weight in threats[:2]:
                    eye = (*enemy["pos"][:2], enemy["pos"][2] + 7 * (1 + 0.05 * enemy.get("cubes", 0)))
                    if not self.arena.shot(eye, (*q, z + 7 * size)):
                        protected += weight
                score = 33 * protected - radius - 0.12 * distance(q, anchor)
                if protected and score > best_score:
                    best, best_score = q, score
        self.cover = best
        return best

    def objective(self, obs, enemies, weapon, p, zone, now):
        best, best_score = None, 0
        hp = obs["self"]["hp"] / obs["self"]["max_hp"]
        count = obs["self"]["cubes"]
        nearest = min((distance(p, e["pos"]) for e in enemies), default=300)
        for drop in obs["drops"]:
            q = drop["pos"]
            d = distance(p, q)
            contested = any(distance(e["pos"], q) < drop["radius"] + 10 for e in enemies)
            if not contested and drop["holder"] in (None, obs["self"]["id"]) and d < 125:
                score = 17 + (1 - hp) * 36 - 0.20 * d - 0.6 * max(0, drop["lands_in"] - d / 12 - 3)
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
                if group == "pickups" and WEAPONS[item["kind"]] <= WEAPONS.get(weapon, 0):
                    continue
                if group in ("crates", "mechs") and (nearest < 62 or hp < 0.65 or count >= 10):
                    continue
                if group in ("cubes", "pickups") and any(distance(e["pos"], q) < min(24, d * 0.7) for e in enemies):
                    continue
                value = {"cubes": 27 if count < 10 else 4, "pickups": 35, "crates": 13, "mechs": 22}[group]
                score = value - 0.24 * d - 0.29 * (now - seen)
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
        height = {"mech": 4.5 * size, "npc": 1, "crate": 0.8}[kind]
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
        firing_now = charge >= (secondary["stats"]["charge"] - 0.05) if laser else False
        aim_point = body if firing_now else lead
        if lightning and d < secondary["stats"]["range"] - 1 and not gun:
            aim_point = body
        yaw = bearing(origin, aim_point)
        pitch = math.atan2(aim_point[2] - origin[2], distance(origin, aim_point))
        act["aim"] = [yaw, max(cfg["min_pitch"], min(cfg["max_pitch"], pitch))]
        error = angle_delta(yaw, me["aim"][0])
        pitch_error = abs(pitch - me["aim"][1])
        allowed_pitch = cfg["min_pitch"] <= pitch <= cfg["max_pitch"]
        hit_tolerance = max(0.014, min(0.36, 1.65 / max(1, d)))
        if target.get("kind") == "mech":
            hit_tolerance *= 1 + 0.05 * target.get("cubes", 0)
        aligned = max(error, pitch_error) < hit_tolerance and allowed_pitch
        clear = allowed_pitch and self.arena.shot(origin, aim_point)
        finishing = target.get("kind") == "mech" and target.get("hp", 1400) < 145 and d < 60
        offensive = not (retreat or urgent or final) or finishing
        for i, weapon in enumerate(me["weapons"]):
            if not weapon:
                continue
            kind, stats = weapon["kind"], weapon["stats"]
            if kind == "gun":
                act["fire"][i] = bool(offensive and aligned and clear and d < min(stats["range"] - 3, 205))
            elif kind == "lightning":
                short = target.get("charging", False) and "laser" in target.get("weapons", ())
                reserve = 18 if retreat else 12
                act["fire"][i] = bool((offensive or short) and error < math.radians(stats["cone_deg"]) * 0.38
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
                                          and 12 < d < stats["range"] - 10 and weapon["cooldown"] <= 0.1
                                          and (target.get("kind") == "mech" or not primary_threat))
                    if act["fire"][i]:
                        self.laser_target = target["id"]
        if gun and gun.get("ammo", 0) <= 5 and (not clear or retreat):
            act["reload"] = True

    def dodge(self, obs, p, direction, size, now, deadline):
        dangers = []
        for projectile, seen in self.memory["projectiles"].values():
            if len(dangers) >= 8 or time.perf_counter() > deadline:
                break
            q, v = projectile["pos"], projectile["vel"]
            age = now - seen
            dx, dy = q[0] + age * v[0] - p[0], q[1] + age * v[1] - p[1]
            speed2 = v[0] * v[0] + v[1] * v[1]
            if speed2 < 1:
                continue
            eta = -(dx * v[0] + dy * v[1]) / speed2
            if 0.08 < eta < 1.1 and math.hypot(dx + eta * v[0], dy + eta * v[1]) < 9:
                z = q[2] + (age + eta) * v[2]
                if projectile["kind"] == "mortar":
                    z -= 0.5 * self.config["weapons"]["mortar"]["gravity"] * (age + eta)**2
                if p[2] - 3 < z < p[2] + size * 9 + 2:
                    dangers.append((dx, dy, v, eta, projectile["kind"] == "mortar"))
        if not dangers:
            return direction, False
        speed = obs["self"]["stats"]["walk_speed"]
        best, best_score = direction, -math.inf
        for cx, cy in (tuple(direction), *ANGLES):
            if time.perf_counter() > deadline:
                break
            endpoint = p[0] + cx * 5, p[1] + cy * 5
            if distance(endpoint, obs["zone"]["center"]) > obs["zone"]["radius"] - 1 or not self.arena.walk(p[:2], endpoint, size):
                continue
            score = 3 * (cx * direction[0] + cy * direction[1])
            for dx, dy, v, eta, mortar in dangers:
                mx = eta * speed * cx
                my = eta * speed * cy
                miss = math.hypot(dx + eta * v[0] - mx, dy + eta * v[1] - my)
                score += min(10, miss) - (10 if miss < (7 if mortar else 3 * size) else 0)
            if score > best_score:
                best, best_score = (cx, cy), score
        return best, True

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
                   for a in enemies[:2] if distance(p, a["pos"]) < 235]
        if not threats and now - self.last_damage < 4:
            old = [(a, seen) for a, seen in self.memory["mechs"].values() if a["kind"] == "mech"]
            if old:
                a, _ = min(old, key=lambda entry: distance(p, entry[0]["pos"]))
                threats.append((a, 1.3))
        nearest = min((distance(p, a["pos"]) for a in enemies), default=999)
        slot = next((i for i, w in enumerate(me["weapons"]) if w and w["kind"] != "gun"), 1)
        second = me["weapons"][slot]
        kind = second["kind"] if second else None
        final = zone["next_radius"] <= 0
        goal = tuple(zone["next_center"])
        margin = zone["radius"] - distance(p, zone["center"])
        next_margin = zone["next_radius"] - distance(p, goal)
        remain = max(0, zone["shrink_end"] - now)
        urgent = not me["in_zone"] or (not final and (margin < 13 or -next_margin > max(0, remain - 7) * stats["walk_speed"] * 0.72))
        if not final and not urgent:
            d = distance(p, goal)
            safe_radius = max(0, zone["next_radius"] - min(38, zone["next_radius"] * 0.4))
            if d > 0.1:
                offset = min(d, safe_radius) / d
                goal = (goal[0] + (p[0] - goal[0]) * offset, goal[1] + (p[1] - goal[1]) * offset)
        anchor = goal
        laser_threat = any("laser" in a.get("weapons", ()) for a, _ in threats)
        favorable = kind == "lightning" and nearest < 43 and len(enemies) == 1 and me["energy"] > 22 and hp > 0.58
        retreat = bool(threats and not favorable and (laser_threat or hp < 0.72 or len(enemies) >= 2 or nearest < 35))
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
                allowed = [q for q in options if distance(q, zone["center"]) < zone["radius"] - 7
                           and self.arena.walk(p[:2], q, size)]
                if allowed:
                    goal = min(allowed, key=lambda q: distance(q, anchor) - 0.65 * distance(q, visible["pos"]))
        elif not urgent and not final and time.perf_counter() < started + 0.013:
            objective = self.objective(obs, enemies, kind, p, zone, now)
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
        if obs["offer"]:
            priorities = {"nanites": 100 if now < 340 else 35, "plating": 92, "servos": 77, "armor": 75,
                          "gun_mag": 74 if now < 205 else 61, "jets": 67 if now < 360 else 82,
                          "lightning_range": 70, "gun_damage": 65, "laser_charge": 66, "capacitor": 65,
                          "reactor": 60, "sensors": 49, "gyros": 48, "laser_damage": 62, "gun_rate": 59}
            choices = obs["offer"]["choices"]
            act["pick"] = max(range(len(choices)), key=lambda i: priorities.get(choices[i]["id"], 40))
        pickups = [item for item in obs["pickups"] if distance(p, item["pos"]) < self.config["loot"]["pickup_radius"] - 0.1
                   and abs(p[2] - item["pos"][2]) < 3.9 and WEAPONS[item["kind"]] > WEAPONS.get(kind, 0)]
        if pickups and not (second and second.get("charge")):
            act["take"] = max(pickups, key=lambda item: WEAPONS[item["kind"]])["id"]
            if second:
                act["drop"] = slot
        roof = self.arena.roof(*anchor) if final else -math.inf
        roof_trip = final and roof > self.arena.ground(*anchor) + 2 and p[2] < roof - 0.25
        if roof_trip:
            launch_distance = min(32, 9 + max(0, roof - p[2]) * 0.9)
            if distance(p, anchor) < launch_distance and me["energy"] > 30:
                self.jet_roof = True
        if not roof_trip or me["energy"] < 3:
            self.jet_roof = False
        jet_seconds = me["energy"] / stats["jet_drain"]
        loiter = final and distance(p, anchor) < 5 and remain < min(10, jet_seconds + 0.6)
        loiter = loiter and remain > 0.8 and jet_seconds > 4.0 and hp > 0.18 and nearest < 110
        if loiter and not self.jet_roof and (laser_threat or nearest < 40) and (zone["radius"] < 12 or stats["jet_drain"] < 12):
            self.launching = True
        if not final or remain <= 0 or me["energy"] <= 0.8:
            self.launching = False
        flight = (self.launching or self.jet_roof) and me["energy"] > 0.8
        if flight:
            goal = anchor
            act["jump"] = bool(me["grounded"])
            act["boost"] = bool(not me["grounded"])
        target = None
        if not flight:
            if enemies:
                target = min(enemies, key=lambda a: distance(p, a["pos"]) * 0.50
                             + a.get("hp", a.get("max_hp", 1400)) * 0.045
                             - (55 if kind == "lightning" and a.get("charging") and distance(p, a["pos"]) < 44 else 0))
            if objective and objective[0] in ("mechs", "crates") and (not target or nearest > 125):
                group, ident, _ = objective
                resource = next((a for a in obs[group] if a["id"] == ident), None)
                if resource:
                    target = resource
            if not target and not final:
                nuisance = [a for a in obs["mechs"] if a["kind"] == "npc" and distance(a["pos"], p) < 43]
                if nuisance:
                    target = min(nuisance, key=lambda a: distance(p, a["pos"]))
        self.combat(act, obs, origin, target, retreat, urgent, final and (hp < 0.86 or remain < 12), visible)
        if not target:
            if threats:
                act["aim"] = [bearing(p, threats[0][0]["pos"]), 0]
            elif now - self.last_damage < 3 and self.damage_bearing is not None:
                act["aim"] = [self.damage_bearing, 0]
            else:
                sweep = (now % 7) * math.tau / 1.8 if now % 7 < 1.8 and not urgent else 0
                act["aim"] = [bearing(p, goal) + sweep, 0]
        goal = tuple(goal)
        d = distance(p, goal)
        if d > 0.18 or flight and not me["grounded"]:
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
            dx, dy = waypoint[0] - p[0], waypoint[1] - p[1]
            if final and flight and not me["grounded"]:
                dx -= me["vel"][0] * 0.55
                dy -= me["vel"][1] * 0.55
            length = math.hypot(dx, dy)
            divisor = max(1.3 if final else 3.3, length)
            act["move"] = [dx / divisor, dy / divisor]
        if not flight and not final and me["grounded"] and time.perf_counter() < started + 0.027:
            direction, dodge = self.dodge(obs, p, act["move"], size, now, started + 0.031)
            act["move"] = list(direction)
            act["boost"] = bool((dodge or urgent or retreat and d > 12 and nearest < 75) and
                                d > 4 and me["energy"] > (5 if urgent else 25))
        elif not flight and urgent and me["grounded"] and d > 6 and me["energy"] > 6:
            act["boost"] = True
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
