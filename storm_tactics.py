"""Optional storm and ballistic tactics for Mech Royale."""
import math
import time


def artillery_shot(arena, origin, target, velocity, stats, setback, pitch_limits, deadline):
    """Solve both ballistic arcs to an observed moving point, then check cover."""
    speed, gravity = stats["speed"], stats["gravity"]
    dx, dy, dz = (b - a for a, b in zip(origin, target))
    vx, vy, vz = velocity
    vz = max(-4, min(4, vz))

    def offset(seconds):
        return dx + vx * seconds, dy + vy * seconds, dz + vz * seconds + .5 * gravity * seconds**2

    def error(seconds):
        return math.hypot(*offset(seconds)) - setback - speed * seconds

    previous_time, previous_error = .1, error(.1)
    ttl = stats.get("ttl", 7)
    for step in range(1, math.ceil(ttl * 5) + 1):
        if time.perf_counter() >= deadline:
            return None
        seconds = min(ttl, .1 + step * .2)
        current_error = error(seconds)
        if (previous_error > 0) != (current_error > 0):
            low, high = previous_time, seconds
            for _ in range(11):
                mid = (low + high) * .5
                if (error(mid) > 0) == (previous_error > 0):
                    low = mid
                else:
                    high = mid
            impact_time = (low + high) * .5
            x, y, z = offset(impact_time)
            yaw, pitch = math.atan2(y, x), math.atan2(z, math.hypot(x, y))
            # Long lob shots are for slow or stopped targets. Extrapolating
            # a moving mech across six seconds tends to overshoot corners.
            if pitch_limits[0] <= pitch <= pitch_limits[1] and (
                impact_time <= 3.6 or math.hypot(vx, vy) < 5
            ):
                length = math.hypot(x, y, z)
                direction = x / length, y / length, z / length
                muzzle = tuple(a + setback * v for a, v in zip(origin, direction))
                if arena.shot(origin, muzzle):
                    last = muzzle
                    segments = math.ceil(impact_time / .18)
                    for part in range(1, segments + 1):
                        if time.perf_counter() >= deadline:
                            return None
                        t = impact_time * part / segments
                        point = tuple(a + v * speed * t for a, v in zip(muzzle, direction))
                        point = point[0], point[1], point[2] - .5 * gravity * t * t
                        if not arena.shot(last, point):
                            break
                        last = point
                    else:
                        return yaw, pitch
        previous_time, previous_error = seconds, current_error
    return None


def mortar_shot(arena, origin, target, velocity, stats, zone, outward):
    """Find a clear ballistic impact, favoring the inward side of a storm target."""
    speed, gravity = stats["speed"], stats["gravity"]
    cx, cy = zone["center"]
    best = None
    for step in range(5, 37):
        t = step * .1
        x, y = target[0] + velocity[0] * t, target[1] + velocity[1] * t
        if outward:
            rx, ry = x - cx, y - cy
            r = math.hypot(rx, ry)
            if r < 1:
                continue
            offset = min(3.8, stats["splash_radius"] * .56)
            x -= offset * rx / r
            y -= offset * ry / r
        z = arena.ground(x, y) + (0.4 if outward else 1.4)
        dx, dy = x - origin[0], y - origin[1]
        d = math.hypot(dx, dy)
        if d < 19:
            continue
        vz = (z - origin[2]) / t + .5 * gravity * t
        required = math.hypot(d / t, vz)
        error = abs(required - speed)
        if best is None or error < best[0]:
            best = error, t, dx, dy, vz
    if best is None or best[0] > 4:
        return None
    _, t, dx, dy, vz = best
    yaw = math.atan2(dy, dx)
    pitch = math.atan2(vz, math.hypot(dx, dy) / t)
    vx, vy, vz = speed * math.cos(pitch) * math.cos(yaw), speed * math.cos(pitch) * math.sin(yaw), speed * math.sin(pitch)
    last = origin
    for step in range(1, 16):
        at = t * step / 15
        nxt = origin[0] + vx * at, origin[1] + vy * at, origin[2] + vz * at - .5 * gravity * at * at
        if not arena.shot(last, nxt):
            if step < 15:
                return None
            break
        last = nxt
    if outward:
        impact_r = math.hypot(last[0] - cx, last[1] - cy)
        enemy = (target[0] + velocity[0] * t, target[1] + velocity[1] * t)
        if impact_r >= math.hypot(enemy[0] - cx, enemy[1] - cy) or math.dist(last[:2], enemy) > stats["splash_radius"]:
            return None
    return yaw, pitch


def storm_screen(arena, position, enemy, zone, size, deadline):
    """Use nearby cover only when it obstructs a storm-exposed pursuer."""
    center, radius = zone["next_center"], zone["next_radius"]
    if radius < 12 or zone["dps"] < 60:
        return None
    q = enemy["pos"]
    ours = math.dist(position[:2], center)
    theirs = math.dist(q[:2], center)
    if ours > radius - 5 or theirs < radius + 7 or math.dist(q[:2], position[:2]) > 85:
        return None
    theta = math.atan2(position[1] - q[1], position[0] - q[0])
    eye = q[0], q[1], q[2] + 7 * (1 + .05 * enemy.get("cubes", 0))
    for offset in (0, .7, -.7, 1.4, -1.4):
        if time.perf_counter() > deadline:
            return None
        x = position[0] + 12 * math.cos(theta + offset)
        y = position[1] + 12 * math.sin(theta + offset)
        if math.hypot(x - center[0], y - center[1]) > radius - 7:
            continue
        if arena.walk(position[:2], (x, y), size) and not arena.shot(eye, (x, y, arena.ground(x, y) + 7 * size)):
            return x, y
    return None
