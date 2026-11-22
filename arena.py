"""Static arena geometry and bounded ground routing for Mech Royale."""
from array import array
from collections import defaultdict
from functools import lru_cache
from heapq import heappop, heappush
import json
import math
from pathlib import Path
import sys
import time

STEP = 5
NEIGHBORS = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))


def inside(x, y, ring):
    result = False
    ax, ay = ring[-1]
    for bx, by in ring:
        if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
            result = not result
        ax, ay = bx, by
    return result


def overlaps(x, y, radius, ring):
    if inside(x, y, ring):
        return True
    ax, ay = ring[-1]
    for bx, by in ring:
        dx, dy = bx - ax, by - ay
        length = dx * dx + dy * dy
        if length:
            f = max(0, min(1, ((x - ax) * dx + (y - ay) * dy) / length))
            if (x - ax - f * dx)**2 + (y - ay - f * dy)**2 < radius * radius:
                return True
        ax, ay = bx, by
    return False


class Arena:
    def __init__(self, directory):
        root = Path(directory) / "v2"
        world = json.loads((root / "world.json").read_text(encoding="utf-8"))
        self.terrain = world["terrain"]
        self.bounds = world["bounds"]
        self.heights = array("h", (root / self.terrain["file"]).read_bytes())
        if sys.byteorder != "little":
            self.heights.byteswap()
        self.bins = defaultdict(list)
        for prism in world["prisms"]:
            ring = tuple(zip(prism["ring"][::2], prism["ring"][1::2]))
            holes = tuple(tuple(zip(hole[::2], hole[1::2])) for hole in prism["holes"])
            solid = (prism["base"], prism["top"], ring, holes)
            xs, ys = zip(*ring)
            for i in range(math.floor(min(xs) / 16), math.floor(max(xs) / 16) + 1):
                for j in range(math.floor(min(ys) / 16), math.floor(max(ys) / 16) + 1):
                    self.bins[i, j].append(solid)

    def ground(self, x, y):
        t = self.terrain
        u = max(0, min(t["nx"] - 1.001, (x - t["minX"]) / t["step"]))
        v = max(0, min(t["ny"] - 1.001, (y - t["minY"]) / t["step"]))
        i, j = int(u), int(v)
        f, g = u - i, v - j
        n = j * t["nx"] + i
        south = self.heights[n] * (1 - f) + self.heights[n + 1] * f
        n += t["nx"]
        north = self.heights[n] * (1 - f) + self.heights[n + 1] * f
        return (south * (1 - g) + north * g) * 0.01

    def roof(self, x, y):
        return max((top for _, top, ring, holes in self.bins.get((math.floor(x / 16), math.floor(y / 16)), ())
                    if inside(x, y, ring) and not any(inside(x, y, h) for h in holes)),
                   default=self.ground(x, y))

    def clear(self, x, y, z, radius, height):
        b = self.bounds
        if not (b["minX"] + radius <= x <= b["maxX"] - radius and b["minY"] + radius <= y <= b["maxY"] - radius):
            return False
        for i in range(math.floor((x - radius) / 16), math.floor((x + radius) / 16) + 1):
            for j in range(math.floor((y - radius) / 16), math.floor((y + radius) / 16) + 1):
                for base, top, ring, holes in self.bins.get((i, j), ()):
                    if z + 0.2 >= top or z + height <= base:
                        continue
                    if overlaps(x, y, radius, ring) and not any(
                        inside(x, y, h) and all(inside(x + dx * radius, y + dy * radius, h)
                                                for dx, dy in NEIGHBORS) for h in holes
                    ):
                        return False
        return True

    def shot(self, a, b):
        steps = max(1, math.ceil(math.dist(a, b) / 2.5))
        for i in range(1, steps + 1):
            f = i / steps
            x = a[0] + (b[0] - a[0]) * f
            y = a[1] + (b[1] - a[1]) * f
            z = a[2] + (b[2] - a[2]) * f
            if z < self.ground(x, y) or not self.clear(x, y, z, 0, 0.05):
                return False
        return True

    @lru_cache(maxsize=70000)
    def edge(self, node, other, size):
        a = (node[0] * STEP, node[1] * STEP)
        b = (other[0] * STEP, other[1] * STEP)
        return self.walk(a, b, size)

    def walk(self, a, b, size):
        n = max(1, math.ceil(math.dist(a, b) / 2))
        previous = self.ground(*a)
        for i in range(1, n + 1):
            f = i / n
            x, y = a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f
            z = self.ground(x, y)
            if z - previous > 1.5 or not self.clear(x, y, z, size * 2.5 + 0.25, size * 9):
                return False
            previous = z
        return True

    def snap(self, point, size):
        cx, cy = (round(value / STEP) for value in point)
        local = [(cx + dx, cy + dy) for dx in range(-3, 4) for dy in range(-3, 4)]
        for node in sorted(local, key=lambda p: math.dist(point, (p[0] * STEP, p[1] * STEP))):
            x, y = node[0] * STEP, node[1] * STEP
            if self.clear(x, y, self.ground(x, y), size * 2.5 + 0.25, size * 9):
                return node
        return cx, cy

    def route(self, a, b, size, deadline):
        start, goal = self.snap(a, size), self.snap(b, size)
        queue = [(math.dist(start, goal), 0, start)]
        cost, parent = {start: 0}, {}
        best, best_distance = start, math.dist(start, goal)
        while queue and time.perf_counter() < deadline:
            _, spent, node = heappop(queue)
            if spent != cost[node]:
                continue
            distance = math.dist(node, goal)
            if distance < best_distance:
                best, best_distance = node, distance
            if node == goal:
                break
            for dx, dy in NEIGHBORS:
                other = node[0] + dx, node[1] + dy
                total = spent + (1.414 if dx and dy else 1)
                if total < cost.get(other, math.inf) and self.edge(node, other, size):
                    cost[other], parent[other] = total, node
                    heappush(queue, (total + 1.35 * math.dist(other, goal), total, other))
        route = []
        while best != start:
            route.append((best[0] * STEP, best[1] * STEP))
            best = parent[best]
        return route[::-1]
