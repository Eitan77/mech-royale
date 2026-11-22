"""V9 foliage/stealth mechanics based on arena/v2/world.json.

Rules: trees block vision only; mechs are still tracked for memory_s=5s
after last sight; within 45m a proximity sensor ignores canopy; shots go
through foliage. This model is a *conservative approximation* of the
unpublished precise canopy ray algorithm, not an exact server emulator.

The candidate optimizer cannot assume that unobserved members of the
cooperating house squad are also fooled.
"""
from collections import defaultdict
import json
import math
from pathlib import Path
import time

CELL=24.
TAU=math.tau

def xy(a,b):
    return math.hypot(a[0]-b[0],a[1]-b[1])

def segment_distance2(px,py,a,b):
    vx=b[0]-a[0];vy=b[1]-a[1]
    den=vx*vx+vy*vy
    t=0. if den<1e-12 else max(0.,min(1.,((px-a[0])*vx+(py-a[1])*vy)/den))
    return (px-(a[0]+t*vx))**2+(py-(a[1]+t*vy))**2,t

class Foliage:
    def __init__(self,mapdir):
        world=json.loads((Path(mapdir)/"v2"/"world.json").read_text(encoding="utf8"))
        fields=world["trees"]["fields"]
        cols={name:i for i,name in enumerate(fields)}
        data=world["trees"]["data"]
        stride=len(fields)
        self.density=float(world.get("rules",{}).get("canopyDensity",.35))
        self.block_t=float(world.get("rules",{}).get("canopyBlockT",.25))
        self.trees=[]
        self.cells=defaultdict(list)
        for k in range(0,len(data),stride):
            row=data[k:k+stride]
            # tuple (crown x,y, crown bottom/top z, crown radius, trunk x/y/r,
            #        trunk base/top z)
            crownx=float(row[cols["crownX"]]);crowny=float(row[cols["crownY"]])
            base=float(row[cols["z"]])
            crown_base=base+float(row[cols["crownBase"]])
            crown_top=base+float(row[cols["height"]])
            radius=float(row[cols["crownR"]])
            trunkx=float(row[cols["x"]]);trunky=float(row[cols["y"]])
            tree=(crownx,crowny,crown_base,crown_top,radius,
                  trunkx,trunky,float(row[cols["trunkR"]]),base)
            if radius<1.:continue
            ident=len(self.trees)
            self.trees.append(tree)
            # Store in all overlapping cells, so point/ray queries are quick
            r=max(radius,float(row[cols["trunkR"]]))+.2
            for cx in range(math.floor((crownx-r)/CELL),math.floor((crownx+r)/CELL)+1):
                for cy in range(math.floor((crowny-r)/CELL),math.floor((crowny+r)/CELL)+1):
                    self.cells[(cx,cy)].append(ident)

    def candidates_near(self,position,radius=40.):
        px,py=position[:2]
        ids=set()
        for cx in range(math.floor((px-radius-15)/CELL),
                        math.floor((px+radius+15)/CELL)+1):
            for cy in range(math.floor((py-radius-15)/CELL),
                            math.floor((py+radius+15)/CELL)+1):
                ids.update(self.cells.get((cx,cy),()))
        return [self.trees[i] for i in ids
                if math.hypot(self.trees[i][0]-px,self.trees[i][1]-py)<radius+14]

    def screen_depth(self,source,target):
        """Optical depth accumulated through crowns along a 3D ray.

        Tree trunks have near-infinite depth only if the ray's height is
        inside the trunk. A crown's horizontal chord contributes
        canopyDensity * length; favors unequivocally dense foliage.
        This intentionally does NOT return a binary proof of occlusion.
        """
        a,b=source,target
        if xy(a,b)<.001:return 0.
        minx,maxx=sorted((a[0],b[0]));miny,maxy=sorted((a[1],b[1]))
        checked=set();depth=0.
        for cx in range(math.floor((minx-15)/CELL),
                        math.floor((maxx+15)/CELL)+1):
            for cy in range(math.floor((miny-15)/CELL),
                            math.floor((maxy+15)/CELL)+1):
                for i in self.cells.get((cx,cy),()):
                    if i in checked:continue
                    checked.add(i)
                    x,y,lo,hi,r,tx,ty,tr,base=self.trees[i]
                    d2,t=segment_distance2(x,y,a,b)
                    if d2 < r*r:
                        z=a[2]+(b[2]-a[2])*t
                        if lo-.2<=z<=hi+.2:
                            chord=2*math.sqrt(max(0.,r*r-d2))
                            depth+=min(8.,chord*self.density)
                    d2,tt=segment_distance2(tx,ty,a,b)
                    if d2<tr*tr:
                        z=a[2]+(b[2]-a[2])*tt
                        if base<=z<=hi:
                            depth+=10.
        return depth

    def concealment(self,enemy,q,ground,size=1.):
        """0=no useful concealment, 1=likely optical block of center and top.

        Near-range sensor (45m) bypasses foliage. We require both the
        upper and middle mech target rays to cross dense crowns, because
        the server sees either visible ray.
        """
        if xy(enemy["pos"],q)<49.:return 0.
        e=enemy["pos"]
        eye=(e[0],e[1],e[2]+8*(1+.05*enemy.get("cubes",0)))
        middle=(q[0],q[1],ground+4.5*size)
        top=(q[0],q[1],ground+8.9*size)
        minimum=min(self.screen_depth(eye,middle),self.screen_depth(eye,top))
        # Require more depth than the approximate canopy cutoff. The server
        # may use a different ray integration scheme.
        return max(0.,min(1.,(minimum-1.25)/1.5))

    def refuge(self,me,enemies,zone,arena,deadline,limit=35.):
        """Find an accessible concealment point in the future safe circle.

        Restrict to at most 18 candidates / 3 enemy line tests and return
        only a strong refuge. Called periodically, not every 100ms.
        """
        p=me["pos"];size=1+.05*me["cubes"]
        nearby=[e for e in enemies if e.get("kind")=="mech"
                and 48<xy(e["pos"],p)<205]
        if not nearby:return None
        nearby=sorted(nearby,key=lambda e:xy(e["pos"],p))[:3]
        scored=[]
        for tree in self.candidates_near(p,limit):
            if time.perf_counter()>deadline:break
            x,y,lo,hi,r,_,_,_,_=tree
            if r<3.:continue
            q=(x,y)
            dist=xy(p,q)
            if dist<3. or dist>limit:continue
            ground=arena.ground(x,y)
            # If the crown is too low or too high relative to mech eye,
            # it cannot hide the visible center and top.
            if not (lo <=ground+5*size and hi>=ground+8*size):
                continue
            if xy(q,zone["next_center"])>zone["next_radius"]-17:
                continue
            if xy(q,zone["center"])>zone["radius"]-12:
                continue
            if any(xy(e["pos"],q)<51 for e in nearby):
                continue
            if not arena.clear(x,y,ground,2.5*size+.15,9*size):
                continue
            if not arena.walk(p[:2],q,size):
                continue
            conceal=min(self.concealment(e,q,ground,size) for e in nearby)
            if conceal<.7:continue
            # Avoid excessive detours to a soft cover spot.
            score=80*conceal-1.65*dist-.12*xy(q,zone["next_center"])
            scored.append((score,q,conceal))
            if len(scored)>=18:break
        return max(scored,key=lambda a:a[0]) if scored else None

def should_ghost(now,last_enemy_seen,last_damage,zone,me):
    """After last enemy sight, preserve five-second tracking expiration."""
    if not me.get("in_zone",False):return False
    if zone["dps"]>=160:return False
    return now-last_enemy_seen>=.2 and now-last_enemy_seen<7.5 and me["hp"]<me["max_hp"]*.90

def stealth_vector(me,goal):
    """Brake first, then command under 5m/s to avoid step sounds."""
    velocity=me.get("vel",(0.,0.))
    speed=math.hypot(velocity[0],velocity[1])
    if speed>4.7:
        return [-velocity[0]/speed*.45,-velocity[1]/speed*.45]
    d=xy(me["pos"],goal)
    if d<1.75:return [0.,0.]
    dx=(goal[0]-me["pos"][0])/d;dy=(goal[1]-me["pos"][1])/d
    return [dx*.35,dy*.35]
