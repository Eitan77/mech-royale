"""Energy and threat models for the V4 controller."""
import math


def jet_pulse(vertical_speed, energy, stats, floor_speed=None):
    threshold = stats["max_rise_speed"] - 0.5 if floor_speed is None else floor_speed
    return energy >= stats["jet_drain"] * 0.1 and vertical_speed < threshold


def project_ascent(seconds, velocity, energy, stats, grounded):
    """Return height above launch and remaining energy under a 10 Hz pulse policy."""
    height = 0.0
    if grounded:
        velocity = stats["jump_speed"]
    for step in range(min(800, max(0, round(seconds * 10)))):
        boost = not (grounded and step == 0) and jet_pulse(velocity, energy, stats)
        if boost:
            energy -= stats["jet_drain"] * 0.1
        for _ in range(2):
            velocity += ((stats["jet_accel"] if boost else 0) - stats["gravity"]) * 0.05
            if boost:
                velocity = min(velocity, stats["max_rise_speed"])
            height += velocity * 0.05
    return height, energy


class GroundBoost:
    def __init__(self):
        self.end = -math.inf
        self.recharge_until = -math.inf
        self.burst = 0.0

    def active(self, now, energy, stats, reserve, eligible):
        if not eligible or energy < reserve:
            if now < self.end:
                self.end = now
                self.recharge_until = now + stats["energy_regen_delay"] + self.burst * stats["boost_drain"] / stats["energy_regen"]
            return False
        if now < self.end:
            return True
        if now < self.recharge_until:
            return False
        duration = min(2.0, (energy - reserve) / stats["boost_drain"])
        if duration < 0.8:
            return False
        self.burst = duration
        self.end = now + duration
        self.recharge_until = self.end + stats["energy_regen_delay"] + duration * stats["boost_drain"] / stats["energy_regen"]
        return True


def defensive_yaw(current, risks, yaw_rate):
    if not risks:
        return current
    candidates = [current]
    for direction, _ in risks:
        candidates.extend((direction, direction - math.pi / 2 + 0.05, direction + math.pi / 2 - 0.05))

    def score(yaw):
        slew = abs(math.remainder(yaw - current, math.tau))
        turn = max(-yaw_rate * 0.25, min(yaw_rate * 0.25, math.remainder(yaw - current, math.tau)))
        return sum(weight * (0.6 * (math.cos(direction - current - turn) >= 0)
                            + 0.4 * (math.cos(direction - yaw) >= 0)) for direction, weight in risks) - 0.02 * slew

    return math.remainder(max(candidates, key=score), math.tau)


def rear_laser_bonus(target, origin, charge_range, vision_fov):
    if target.get("kind") != "mech":
        return 0
    dx, dy = origin[0] - target["pos"][0], origin[1] - target["pos"][1]
    angle = abs(math.remainder(math.atan2(dy, dx) - target["aim"][0], math.tau))
    if angle < max(math.pi / 2, vision_fov / 2 + 0.35):
        return 0
    bonus = 8 if "mortar" in target.get("weapons", ()) else 0
    d = math.hypot(dx, dy)
    return bonus + (13 if charge_range + 4 < d < 200 and angle > 1.9 and not target.get("charging") else 0)
