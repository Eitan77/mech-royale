"""Predict the shot along the actual slewing torso, against moving hit cylinders."""
import math


def slew(current, requested, allowance, wrap=False):
    change = requested - current
    if wrap:
        change = math.remainder(change, math.tau)
    return current + max(-allowance, min(allowance, change))


def cylinder_hit(point, direction, feet, velocity, radius, height, travel_limit):
    """Return entry distance/time into the volume in relative coordinates."""
    dx, dy, dz = (point[i] - feet[i] for i in range(3))
    vx, vy, vz = (direction[i] - velocity[i] for i in range(3))
    lo, hi = 0.0, travel_limit
    a = vx * vx + vy * vy
    c = dx * dx + dy * dy - radius * radius
    if a < 1e-10:
        if c > 0:
            return None
    else:
        b = dx * vx + dy * vy
        disc = b * b - a * c
        if disc < 0:
            return None
        root = math.sqrt(disc)
        lo, hi = max(lo, (-b - root) / a), min(hi, (-b + root) / a)
    if abs(vz) < 1e-10:
        if not 0 <= dz <= height:
            return None
    else:
        z0, z1 = -dz / vz, (height - dz) / vz
        lo, hi = max(lo, min(z0, z1)), min(hi, max(z0, z1))
    return lo if lo <= hi else None


def project_position(point, velocity, delay):
    return tuple(position + delay * speed for position, speed in zip(point, velocity))


def firing_delay(weapon):
    return min(.1, max(.05, weapon["cooldown"]))


def shot_connects(arena, origin, me, requested, target, weapon, radius, height):
    stats = me["stats"]
    lead_time = firing_delay(weapon)
    yaw = slew(me["aim"][0], requested[0], stats["turn_rate"] * lead_time, True)
    pitch = slew(me["aim"][1], requested[1], stats["pitch_rate"] * lead_time)
    direction = math.cos(pitch) * math.cos(yaw), math.cos(pitch) * math.sin(yaw), math.sin(pitch)
    feet_velocity = target.get("vel", (0, 0, 0))
    feet = project_position(target["pos"], feet_velocity, lead_time)
    muzzle = project_position(origin, me["vel"], lead_time)
    setback = 0.5 + stats.get("radius", 2.5 * (1 + .05 * me["cubes"]))
    forward = tuple(muzzle[i] + direction[i] * setback for i in range(3))
    if arena.shot(muzzle, forward):
        muzzle = forward
    speed = weapon["stats"].get("speed")
    reach = weapon["stats"]["range"]
    motion = tuple(d * speed for d in direction) if speed else direction
    travel = reach / speed if speed else reach
    hit = cylinder_hit(muzzle, motion, feet, feet_velocity if speed else (0, 0, 0), radius, height, travel)
    if hit is None:
        return False
    contact = tuple(muzzle[i] + motion[i] * hit for i in range(3))
    return arena.shot(muzzle, contact)
