"""V11 hard-cover pursuit denial and anti-lead movement.

Source of truth: original mechfight-kit protocol/world map. Unlike foliage,
solid prisms stop BOTH sight and gun/laser projectiles. Enemies we can't
observe may still see us through the cooperating squad; no perfect guarantee.
"""
from collections import defaultdict
import math
import time

CELL=32
def dist(a,b):
    return math.hypot(a[0]-b[0],a[1]-b[1])

def aimed(enemy,me):
    if "aim" not in enemy or dist(enemy["pos"],me["pos"])>155:return False
    theta=math.atan2(me["pos"][1]-enemy["pos"][1],
                     me["pos"][0]-enemy["pos"][0])
    return abs(math.remainder(enemy["aim"][0]-theta,math.tau))<.30

def focus_fire(me,enemies,projectiles,now,last_damage):
    """Only divert from farming on strong, local attack evidence."""
    if now>185:return False
    close=[e for e in enemies if dist(e["pos"],me["pos"])<155]
    if not close:return False
    if now-last_damage<4.5:return True
    if sum(aimed(e,me) for e in close)>=2:return True
    if me["hp"]<.82*me["max_hp"] and any(aimed(e,me) for e in close):
        return True
    toward=0
    for q in projectiles[:12]:
        if dist(q["pos"],me["pos"])>85:continue
        p,v=q["pos"],q["vel"]
        toward+=((me["pos"][0]-p[0])*v[0]+
                 (me["pos"][1]-p[1])*v[1])>0
    return toward>=2

class ShadowAtlas:
    def __init__(self,arena):
        self.corners=[]
        self.grid=defaultdict(list)
        seen=set()
        # arena.bins repeats the same ring object across cells.
        for entries in arena.bins.values():
            for base,top,ring,holes in entries:
                ident=id(ring)
                if ident in seen:continue
                seen.add(ident)
                if top-base<4 or len(ring)<3:continue
                xs,ys=zip(*ring)
                if min(max(xs)-min(xs),max(ys)-min(ys))<5:continue
                for q in ring:
                    i=len(self.corners)
                    self.corners.append(q)
                    self.grid[(math.floor(q[0]/CELL),
                               math.floor(q[1]/CELL))].append(i)

    def nearby_corners(self,p,reach=80):
        cx,cy=math.floor(p[0]/CELL),math.floor(p[1]/CELL)
        n=math.ceil(reach/CELL)+1
        ids=set()
        for x in range(cx-n,cx+n+1):
            for y in range(cy-n,cy+n+1):
                ids.update(self.grid.get((x,y),()))
        return sorted((self.corners[i] for i in ids
                       if 4<dist(self.corners[i],p)<reach),
                      key=lambda q:dist(q,p))

    def search(self,me,enemies,zone,arena,now,deadline,reach=80):
        """Find reachable hard LOS break from several visible shooters.

        Candidate positions are just beyond nearby prism corners as seen
        from the nearest shooter. No expensive global pathfinding here.
        """
        if not enemies:return None
        p=me["pos"];size=1+.05*me["cubes"]
        shooters=sorted(enemies,key=lambda e:dist(e["pos"],p))[:3]
        if dist(shooters[0]["pos"],p)>170:return None
        best=None
        best_score=-1e9
        tested=0
        for corner in self.nearby_corners(p,reach)[:26]:
            if time.perf_counter()>deadline or tested>=40:break
            e=shooters[0]["pos"]
            vx,vy=corner[0]-e[0],corner[1]-e[1]
            n=math.hypot(vx,vy)
            if n<.01:continue
            vx,vy=vx/n,vy/n
            px,py=-vy,vx
            for f,side in ((7,0),(10,5),(10,-5)):
                if time.perf_counter()>deadline or tested>=40:break
                tested+=1
                q=(corner[0]+f*vx+side*px,
                   corner[1]+f*vy+side*py)
                d=dist(p,q)
                if d<4 or d>reach:continue
                if dist(q,zone["center"])>zone["radius"]-10:continue
                # The circle does not finish closing for tens of seconds.
                # Cover 20m outside its NEXT radius is often the only way
                # to stop being shot NOW. Reject it only if there won't be
                # enough time to exit cover and reach the next circle later.
                future_excess=max(0.,dist(q,zone["next_center"])-
                                  max(0.,zone["next_radius"]-16))
                transit=future_excess/max(1.,me["stats"]["walk_speed"]*.60)
                eta=d/max(1.,me["stats"]["walk_speed"]*.70)
                if zone["shrink_end"]-now<eta+transit*1.55+13:continue
                g=arena.ground(*q)
                if not arena.clear(q[0],q[1],g,2.5*size+.2,9*size):
                    continue
                # Truly useful shadows are often BEHIND a wall, so a
                # direct path is not always available. Let the existing A*
                # route around a nearby corner; penalize the extra exposure.
                direct=arena.walk(p[:2],q,size)
                if not direct and (d>45 or
                        zone["shrink_end"]-now<1.8*eta+15):
                    continue
                blocked=0
                for enemy in shooters:
                    scale=1+.05*enemy.get("cubes",0)
                    src=(enemy["pos"][0],enemy["pos"][1],
                         enemy["pos"][2]+7*scale)
                    mid=(q[0],q[1],g+4.5*size)
                    top=(q[0],q[1],g+8.8*size)
                    if not arena.shot(src,mid) and not arena.shot(src,top):
                        blocked+=1
                if not blocked:continue
                if min(dist(q,e["pos"]) for e in shooters)<48:continue
                score=(70*blocked-1.4*d+
                       .15*min(dist(q,e["pos"]) for e in shooters)-
                       .08*dist(q,zone["next_center"])-
                       .16*future_excess-(24 if not direct else 0))
                if blocked==len(shooters):score+=50
                if score>best_score:
                    best,best_score=q,score
        return (best,best_score) if best else None

def hold_shadow(me,goal,enemies,zone,arena,deadline):
    if goal is None or dist(me["pos"],goal)>90:return False
    future_excess=max(0.,dist(goal,zone["next_center"])-
                      max(0.,zone["next_radius"]-12))
    transit=future_excess/max(1.,me["stats"]["walk_speed"]*.60)
    if zone["shrink_end"]-me.get("t",0)<0:
        return False
    # The controller checks urgency independently. Don't reject cover
    # outside the next circle when there is ample time to leave it.
    if not enemies:return True # preserve hiding through shared 5s tracking
    if time.perf_counter()>deadline:return True
    p=me["pos"];size=1+.05*me["cubes"]
    mid=(goal[0],goal[1],arena.ground(*goal)+4.5*size)
    return any(not arena.shot(
        (e["pos"][0],e["pos"][1],e["pos"][2]+7*(1+.05*e.get("cubes",0))),mid)
        for e in enemies[:3])

def anti_lead(me,enemies,now,last_damage,zone):
    """Reverse lateral motion near enemy gun time-of-flight."""
    if not enemies or now-last_damage>8:return None
    p=me["pos"];e=min(enemies,key=lambda x:dist(x["pos"],p))
    d=dist(e["pos"],p)
    if not 18<d<155:return None
    a=math.atan2(p[1]-e["pos"][1],p[0]-e["pos"][0])
    period=max(.22,min(.48,d/320.))
    side=1 if int(now/period)%2==0 else -1
    theta=a+side*math.pi/2+.18*math.sin(now*3)
    q=(p[0]+11*math.cos(theta),p[1]+11*math.sin(theta))
    if dist(q,zone["center"])>zone["radius"]-10:
        theta=a-side*math.pi/2
    return (math.cos(theta),math.sin(theta))
