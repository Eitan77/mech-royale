"""Short-horizon movement selection for the game controller."""
import math
import time


def choose_movement(arena, me, zone, move, threats, projectiles, size, urgent, deadline, capture=None):
    p, velocity, stats = me["pos"], me["vel"], me["stats"]
    if not me["grounded"] or not threats and not projectiles:
        return move, False
    mag = math.hypot(*move)
    preferred = math.atan2(move[1], move[0]) if mag > 0.05 else me["aim"][0]
    options = [tuple(move)]
    options.extend((math.cos(preferred + angle), math.sin(preferred + angle))
                   for angle in (0, .40, -.40, .80, -.80, 1.45, -1.45, 2.1, -2.1))
    aim_lines = []
    for enemy, weight in threats[:4]:
        q = enemy["pos"]
        d = math.hypot(p[0] - q[0], p[1] - q[1])
        if 5 < d < 240:
            yaw = enemy["aim"][0]
            aim_lines.append((q, d, math.cos(yaw), math.sin(yaw), weight,
                              enemy.get("charging", False), "lightning" in enemy.get("weapons", ())))
    incoming = []
    for bullet in projectiles[:16]:
        q, v = bullet["pos"], bullet["vel"]
        d = math.hypot(q[0] - p[0], q[1] - p[1])
        if d < 100 and (p[0] - q[0]) * v[0] + (p[1] - q[1]) * v[1] > 0:
            incoming.append((q, v, bullet["kind"] == "mortar"))
    best, best_score = (move, False), -math.inf
    ground_accel = stats["ground_accel"]
    current_margin = zone["radius"] - math.hypot(p[0] - zone["center"][0], p[1] - zone["center"][1])
    for dx, dy in options:
        for boost in (False, True) if (urgent or incoming) and me["energy"] > 21 and mag > 0.1 else (False,):
            if time.perf_counter() >= deadline:
                return best
            speed = stats["boost_speed"] if boost else stats["walk_speed"]
            vx, vy = velocity[0], velocity[1]
            x, y = p[:2]
            samples = []
            for i in range(6):
                ax, ay = speed * dx - vx, speed * dy - vy
                scale = min(1, ground_accel * .1 / max(.001, math.hypot(ax, ay)))
                vx += ax * scale
                vy += ay * scale
                x += vx * .1
                y += vy * .1
                samples.append((x, y))
            if capture and any(math.dist(point, capture["pos"][:2]) > capture["radius"] - .2 for point in samples):
                continue
            if not arena.walk(p[:2], samples[-1], size):
                continue
            margin = zone["radius"] - math.hypot(x - zone["center"][0], y - zone["center"][1])
            if margin < min(0, current_margin - .3):
                continue
            progress = (x - p[0]) * math.cos(preferred) + (y - p[1]) * math.sin(preferred)
            score = (2 if urgent else 1.0) * mag * progress - (1.1 if boost else 0)
            for q, d, ax, ay, weight, charging, lightning in aim_lines:
                r0x, r0y = p[0] - q[0], p[1] - q[1]
                cross0 = abs(r0x * ay - r0y * ax)
                crossed = abs((x - q[0]) * ay - (y - q[1]) * ax)
                if r0x * ax + r0y * ay > 0 and cross0 < max(8, d * .12):
                    score += weight * min(7, crossed - cross0) * (1.55 if charging else .52)
                if lightning and d < 60:
                    score += weight * .8 * (math.hypot(x - q[0], y - q[1]) - d)
            for q, v, mortar in incoming:
                closest = math.inf
                for i, (sx, sy) in enumerate(samples, 1):
                    t = i * .1
                    prior = samples[i - 2] if i > 1 else p[:2]
                    bx, by = q[0] + (t - .1) * v[0] - prior[0], q[1] + (t - .1) * v[1] - prior[1]
                    wx, wy = .1 * v[0] - (sx - prior[0]), .1 * v[1] - (sy - prior[1])
                    f = max(0, min(1, -(bx * wx + by * wy) / max(.001, wx * wx + wy * wy)))
                    at = t - .1 + .1 * f
                    z = q[2] + at * v[2] - (0.5 * stats.get("gravity", 22) * at * at if mortar else 0)
                    if p[2] - 2 < z < p[2] + 9 * size + 2:
                        closest = min(closest, math.hypot(bx + f * wx, by + f * wy))
                radius = (7 if mortar else 2.5 * size) + 1
                score -= (22 if mortar else 12) * max(0, 1 - closest / radius)
            if score > best_score:
                best, best_score = ((dx, dy), boost), score
    return best
