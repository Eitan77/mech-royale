"""Prioritize survival time and control of the final circle."""
import math
import time

from arena import Arena
from firing import firing_delay, project_position, shot_connects
import mechfight
from mobility import jet_pulse, project_ascent
from pilot import choose_movement
from tactical_v10 import imminent_projectile
from throne_v6 import zone_future


def distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def bearing(a, b):
    return math.atan2(b[1] - a[1], b[0] - a[0])


def direction(a, b, braking_distance=2):
    x, y = b[0] - a[0], b[1] - a[1]
    scale = max(braking_distance, math.hypot(x, y))
    return [x / scale, y / scale]


class PlacementBot:
    name = "Placement Intercepts"

    def __init__(self, hello):
        self.cfg = hello["config"]
        self.arena = Arena(hello["map"]["dir"])
        self.damage_at = -100
        self.hit_at = -100
        self.shelter = None
        self.shelter_at = -100
        self.path = []
        self.path_goal = None
        self.route_at = -100
        self.roof_plan = None
        self.roof_at = -100
        self.ascent = None
        self.final_flight = False

    def threats(self, p, obs):
        result = []
        for enemy in obs["mechs"]:
            gap = distance(p, enemy["pos"])
            if enemy["kind"] == "npc":
                if gap < 48:
                    result.append((35, enemy))
                continue
            weapons = enemy["weapons"]
            reach = max((self.cfg["weapons"][w].get("range", 170) for w in weapons), default=0)
            if gap > reach:
                continue
            yaw_error = abs(math.remainder(enemy["aim"][0] - bearing(enemy["pos"], p), math.tau))
            weight = 25 + 90 * (1 - gap / max(1, reach)) + (40 if yaw_error < .3 else 0)
            if "laser" in weapons:
                weight += 95 if enemy["charging"] else 55
            result.append((weight, enemy))
        return sorted(result, key=lambda pair: pair[0], reverse=True)[:4]

    def exposure(self, q, floor, threats, me):
        total = 0
        for weight, enemy in threats:
            p = enemy["pos"]
            muzzle = 2.8 if enemy["kind"] == "npc" else self.cfg["mech"]["muzzle_height"] * (
                1 + self.cfg["cubes"]["size_per_cube"] * enemy.get("cubes", 0)
            )
            if self.arena.shot((*p[:2], p[2] + muzzle), (*q, floor + .65 * me["stats"]["height"])):
                total += weight
        return total

    def safe_position(self, obs, threats, goal, size, deadline):
        me, zone, now = obs["self"], obs["zone"], obs["t"]
        p = me["pos"]
        healing = me["hp"] < .92 * me["max_hp"]
        if self.shelter is not None and now - self.shelter_at < 1.1:
            return self.shelter
        self.shelter_at = now
        heading = bearing(p, goal)
        points = [tuple(p[:2])]
        for radius in (11, 23, 39):
            for offset in (0, .7, -.7, 1.4, -1.4, 2.2, -2.2, math.pi):
                angle = heading + offset
                points.append((p[0] + radius * math.cos(angle), p[1] + radius * math.sin(angle)))
        best = None
        speed = me["stats"]["walk_speed"]
        for q in points:
            if time.perf_counter() >= deadline:
                break
            eta = distance(p, q) / speed
            center, radius = zone_future(zone, now, eta + (5 if healing else 2))
            if distance(q, center) > radius - 5 or not self.arena.walk(p[:2], q, size):
                continue
            exposure = self.exposure(q, self.arena.ground(*q), threats, me)
            cost = 1.6 * exposure + eta * 4 + distance(q, goal) * .38
            if best is None or cost < best[0]:
                best = cost, q
        self.shelter = best[1] if best is not None else goal
        return self.shelter

    def route(self, p, goal, size, now, deadline):
        gap = distance(p, goal)
        if gap < .1:
            return goal
        move = direction(p, goal, 1)
        direct = tuple(p[i] + move[i] * min(gap, 35) for i in range(2))
        if p[2] > self.arena.ground(*p[:2]) + 2:
            if self.arena.air_lane(p[:2], direct, p[2] + .05, size):
                return direct
        elif self.arena.walk(p[:2], direct, size):
            return direct
        changed = self.path_goal is None or distance(goal, self.path_goal) > 10
        if changed:
            self.path.clear()
        if (changed or now - self.route_at > .7) and time.perf_counter() < deadline:
            path = self.arena.route(p[:2], goal, round(size, 2), deadline)
            if path:
                self.path = path
            self.path_goal, self.route_at = goal, now
        while self.path and distance(p, self.path[0]) < 2:
            self.path.pop(0)
        for point in reversed(self.path[:4]):
            if time.perf_counter() >= deadline:
                break
            if self.arena.walk(p[:2], point, size):
                return point
        return self.path[0] if self.path else direct

    def resource(self, obs, threats, zone_goal, deadline):
        me, zone = obs["self"], obs["zone"]
        p = me["pos"]
        best = None
        held = {w["kind"] for w in me["weapons"] if w}
        close_enemy = min((distance(p, e["pos"]) for _, e in threats), default=300)
        for group, items in (
            ("drops", obs["drops"]), ("cubes", obs["cubes"]),
            ("pickups", obs["pickups"]), ("crates", obs["crates"]),
        ):
            for item in items:
                q = item["pos"]
                gap = distance(p, q)
                if gap > (170 if group == "drops" else 85) or abs(q[2] - p[2]) > 4:
                    continue
                center, radius = zone_future(zone, obs["t"], gap / me["stats"]["walk_speed"] + 8)
                if distance(q, center) > radius - 8:
                    continue
                if time.perf_counter() >= deadline:
                    return best
                if group == "drops":
                    if item["holder"] not in (None, me["id"]) or item["lands_in"] > gap / 11 + 5:
                        continue
                    value = 115 + 65 * (1 - me["hp"] / me["max_hp"])
                elif group == "pickups":
                    if item["kind"] in held or item["kind"] == "gun" or len(held) == 2:
                        continue
                    value = {"laser": 95, "lightning": 80, "mortar": 32}.get(item["kind"], 0)
                elif group == "cubes":
                    value = 80 if me["cubes"] < self.cfg["cubes"]["stat_cap"] else 30
                else:
                    if me["cubes"] >= 10 or close_enemy < 120:
                        continue
                    value = 64 if "laser" in held else 40
                exposure = self.exposure(q[:2], q[2], threats[:2], me) if threats else 0
                score = value - .60 * gap - .42 * exposure - max(0, distance(q, zone_goal) - distance(p, zone_goal)) * .17
                if score > 0 and (best is None or score > best[0]):
                    best = score, group, item
        return best

    def center_move(self, me, anchor):
        p, velocity, stats = me["pos"], me["vel"], me["stats"]
        d = distance(p, anchor)
        accel = stats["ground_accel"] if me["grounded"] else stats["air_accel"]
        speed = stats["walk_speed"]
        desired = min(speed, math.sqrt(2 * accel * d) * .8, d * (8 if me["grounded"] else 2.5))
        unit = direction(p, anchor, .001)
        gain = .17 if d < 3 else 0
        command = [desired * unit[i] - gain * velocity[i] for i in range(2)]
        scale = max(speed, math.hypot(*command))
        return [component / scale for component in command]

    def endgame(self, act, obs, threats, anchor, size, deadline):
        me, now, zone = obs["self"], obs["t"], obs["zone"]
        p, stats = me["pos"], me["stats"]
        distance_to_center = distance(p, anchor)
        top = self.arena.roof(*anchor)
        if p[2] < top - 1 and top > self.arena.ground(*anchor) + 2 and distance_to_center < 100:
            if self.roof_plan is None and now - self.roof_at > 1.2:
                self.roof_at = now
                self.roof_plan = self.arena.roof_route(p, anchor, size, stats, me["energy"], deadline)
            if self.roof_plan is not None:
                _, launch, altitude, fuel = self.roof_plan
                if self.ascent is None and me["energy"] < fuel:
                    return launch, False
                if self.ascent is None and me["grounded"] and me["energy"] >= fuel:
                    if distance(p, launch) > 1.4:
                        return launch, False
                    if math.hypot(*me["vel"][:2]) > 2:
                        return tuple(p[:2]), False
                    self.ascent = now
                    act["jump"] = True
                if self.ascent is not None:
                    if now - self.ascent < 12 and me["energy"] > .8:
                        act["boost"] = not me["grounded"] and jet_pulse(me["vel"][2], me["energy"], stats)
                        return (anchor if p[2] >= altitude - .5 else launch), True
                    self.roof_plan = self.ascent = None
        remaining = zone["shrink_end"] - now
        if (me["grounded"] and distance_to_center < 1.3 and math.hypot(*me["vel"][:2]) < 2
                and 3 < remaining < min(27, me["energy"] / stats["jet_drain"] * 1.35)
                and (zone["radius"] < 13 or len(threats) >= 2)):
            gain, _ = project_ascent(remaining, me["vel"][2], me["energy"], stats, True)
            if gain > 43 and all(self.arena.clear(*p[:2], p[2] + h, 2.5 * size, 9 * size)
                                 for h in range(0, int(gain), 4)):
                act["jump"] = self.final_flight = True
        if self.final_flight and not me["grounded"]:
            act["boost"] = remaining > -2 and jet_pulse(me["vel"][2], me["energy"], stats)
            return anchor, True
        return anchor, False

    def fire(self, act, obs, target):
        me = obs["self"]
        p, stats = me["pos"], me["stats"]
        target_pos = target["pos"]
        kind = target.get("kind", "crate")
        scale = 1 + self.cfg["cubes"]["size_per_cube"] * target.get("cubes", 0)
        radius, height = (2.5 * scale, 9 * scale) if kind == "mech" else (
            (self.cfg["npc"]["radius"], self.cfg["npc"]["height"]) if kind == "npc" else (1.15, 1.6)
        )
        origin = (*p[:2], p[2] + stats["muzzle_height"])
        velocity = target.get("vel", (0, 0, 0))
        gap = distance(p, target_pos)
        selected = next(((i, w) for i, w in enumerate(me["weapons"])
                         if w and w["kind"] == "lightning" and gap < w["stats"]["range"] - 1
                         and me["energy"] > w["stats"]["energy"] + 12), None)
        laser = next(((i, w) for i, w in enumerate(me["weapons"]) if w and w["kind"] == "laser"), None)
        if laser and (laser[1].get("charge", 0) or selected is None and laser[1]["cooldown"] <= .15):
            selected = laser
        if selected is None:
            selected = next(((i, w) for i, w in enumerate(me["weapons"]) if w and w["kind"] == "gun"), None)
        if selected is None:
            return
        i, w = selected
        delay = firing_delay(w)
        travel = gap / w["stats"]["speed"] if w["kind"] == "gun" else 0
        point = project_position((*target_pos[:2], target_pos[2] + height * .55), velocity, delay + travel)
        source = project_position(origin, me["vel"], delay)
        yaw = bearing(source, point)
        pitch = math.atan2(point[2] - source[2], distance(source, point))
        cfg = self.cfg["mech"]
        act["aim"] = [yaw, max(cfg["min_pitch"], min(cfg["max_pitch"], pitch))]
        error = abs(math.remainder(yaw - me["aim"][0], math.tau))
        if not self.arena.shot(source, point) or gap >= w["stats"]["range"]:
            return
        if w["kind"] == "lightning":
            act["fire"][i] = w["cooldown"] <= .1 and error < math.radians(w["stats"]["cone_deg"]) * .45
        elif w["kind"] == "laser":
            charge = w.get("charge", 0)
            act["fire"][i] = (w["cooldown"] <= .1 and error < .13 if not charge else
                              charge < w["stats"]["charge"] or (charge < w["stats"]["charge"] + .5
                              and not shot_connects(self.arena, origin, me, act["aim"], target, w, radius, height)))
        else:
            act["fire"][i] = w["cooldown"] <= .1 and w["reload"] <= .1 and shot_connects(
                self.arena, origin, me, act["aim"], target, w, radius, height
            )

    def act(self, obs):
        start = time.perf_counter()
        me, zone, now = obs["self"], obs["zone"], obs["t"]
        p, stats = me["pos"], me["stats"]
        if any(event["type"] == "damaged" for event in obs["events"]):
            self.damage_at = now
        if any(event["type"] == "hit" for event in obs["events"]):
            self.hit_at = now
        size = 1 + self.cfg["cubes"]["size_per_cube"] * me["cubes"]
        threats = self.threats(p, obs)
        act = {"tick": obs["tick"], "fire": [False, False]}
        final = zone["next_radius"] <= 0
        anchor = tuple(zone["next_center"])
        goal = anchor
        flight = False
        target = None
        capture = None
        health = me["hp"] / me["max_hp"]
        urgent = (not me["in_zone"] or distance(p, zone["center"]) > zone["radius"] - 10
                  or distance(p, anchor) > zone["next_radius"] - 13
                  and zone["shrink_end"] - now < distance(p, anchor) / stats["walk_speed"] + 12)
        if final:
            goal, flight = self.endgame(act, obs, threats, anchor, size, start + .015)
            intruders = [enemy for _, enemy in threats if enemy["kind"] == "mech"
                         and distance(enemy["pos"], anchor) < max(10, zone["radius"] * .65)
                         and distance(enemy["pos"], p) < 55]
            target = min(intruders, key=lambda e: distance(anchor, e["pos"]), default=None)
        else:
            gap = distance(p, anchor)
            hold_radius = min(zone["next_radius"] * .60, max(0, gap - 8))
            if gap > .1 and not urgent:
                goal = tuple(anchor[i] + (p[i] - anchor[i]) * hold_radius / gap for i in range(2))
            if not urgent and me["grounded"]:
                resource = self.resource(obs, threats, goal, start + .009) if now < 335 else None
                if resource is not None and (health > .65 or resource[1] == "drops"):
                    _, group, item = resource
                    gap = distance(p, item["pos"])
                    goal = tuple(item["pos"][:2])
                    if group == "pickups" and gap < self.cfg["loot"]["pickup_radius"] - .1:
                        act["take"] = item["id"]
                    elif group == "drops" and item["lands_in"] <= 0 and gap < item["radius"] - .4:
                        capture = item
                    elif group == "crates":
                        target = item
                        if gap < 38 and self.arena.shot((*p[:2], p[2] + stats["muzzle_height"]),
                                                        (*goal, item["pos"][2] + .8)):
                            goal = tuple(p[:2])
                elif threats:
                    goal = self.safe_position(obs, threats, goal, size, start + .020)
                    nearest = min((enemy for _, enemy in threats), key=lambda enemy: distance(p, enemy["pos"]))
                    recovery_due = health < .78 and distance(p, goal) < 3 and (
                        now - max(self.damage_at, self.hit_at) >= stats["regen_delay"] - 2
                    )
                    if not recovery_due and distance(p, nearest["pos"]) < (46 if nearest["kind"] == "npc" else 58):
                        target = nearest
        waypoint = goal if flight or not me["grounded"] else self.route(p, goal, size, now, start + .027)
        dest_gap = distance(p, goal)
        act["move"] = (self.center_move(me, goal) if (final or flight) and dest_gap < 6
                       else direction(p, waypoint, 3))
        if not flight and me["grounded"] and dest_gap > 9:
            reserve = 18 if urgent else 60
            escaping = bool(threats) and now - self.damage_at < 3
            act["boost"] = me["energy"] > reserve and (urgent or escaping)
        if target and time.perf_counter() < start + .032:
            self.fire(act, obs, target)
        charging = any(weapon and weapon["kind"] == "laser" and act["fire"][i]
                       for i, weapon in enumerate(me["weapons"]))
        if (not flight and me["grounded"] and (not final or dest_gap > 6)
                and time.perf_counter() < start + .032 and p[2] < self.arena.ground(*p[:2]) + 2):
            chargers = [(enemy, weight / 100) for weight, enemy in threats if enemy.get("charging")]
            if chargers or imminent_projectile(me, obs["projectiles"], zone):
                speed_scale = self.cfg["mech"]["charge_move_mult"] if charging else 1.0
                move, boost = choose_movement(
                    self.arena, me, zone, act["move"], chargers, obs["projectiles"],
                    size, urgent, start + .037, capture, now, speed_scale,
                )
                act["move"], act["boost"] = list(move), boost
        if target is None and now - self.damage_at > 1 and not threats:
            act["reload"] = any(w and w["kind"] == "gun" and w["ammo"] < 5 and w["reload"] == 0
                                for w in me["weapons"])
        if "aim" not in act:
            angle = bearing(p, threats[0][1]["pos"]) if threats else bearing(p, goal) + .85 * math.sin(now * 2)
            act["aim"] = [math.remainder(angle, math.tau), 0]
        if obs["offer"]:
            priorities = ("jets", "capacitor", "plating", "nanites", "servos", "armor", "laser_damage")
            if now < 240 and health < .84:
                priorities = ("nanites", "plating", "armor", "jets", "capacitor", "servos", "laser_damage")
            act["pick"] = min(range(len(obs["offer"]["choices"])), key=lambda i: (
                priorities.index(obs["offer"]["choices"][i]["id"])
                if obs["offer"]["choices"][i]["id"] in priorities else len(priorities)
            ))
        return act


if __name__ == "__main__":
    mechfight.run(PlacementBot)
