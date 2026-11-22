"""V11X conditional upgrade-offer sculpting.

MECHANIC FROM ORIGINAL KIT:
- Offers are 3 distinct eligible upgrades, and weapon upgrades are eligible
  only if the weapon is HELD WHEN THE OFFER IS DRAWN.
- Cubes auto-collect within 3.5m; dropped weapons can be taken within 4m.
- Dropped weapons do not despawn.

So at an upgrade threshold, drop all weapons ~5-7m from a safe cube,
collect it by walking 2-3m, choose from universal-only upgrades, then
re-equip both weapons WITHOUT walking back (4m pickup radius).

This is not a guarantee of good offers or placements. Strong danger gates
and loss recovery are intentional. Keep this on an isolated A/B branch.
"""
from math import comb,hypot

def dist(a,b):
    return hypot(a[0]-b[0],a[1]-b[1])

def chance_one_of_two(pool,draw=3):
    if pool<draw:return 1.
    return 1.-comb(pool-2,draw)/comb(pool,draw)

def safe_candidate(obs,me,nearest,last_damage,thresholds,zone):
    if obs.get("offer") or obs["t"]>195 or me["cubes"]+1 not in thresholds:
        return None
    if not me["grounded"] or not me["in_zone"]:return None
    if me["hp"]<.94*me["max_hp"] or me["energy"]<55:return None
    if nearest<235 or obs["t"]-last_damage<12:return None
    if zone["next_radius"]<110:return None
    if any(x["kind"] in ("gun","laser","mortar","npc_gun","lightning")
           and x["dist"] in ("near","mid") and x["age"]<2
           for x in obs["sounds"]):
        return None
    if not any(w and w["kind"]=="gun" for w in me["weapons"]):
        return None
    if any(w and w.get("charge",0)>0 for w in me["weapons"]):
        return None
    qbest=None
    dbest=1e9
    for c in obs["cubes"]:
        d=dist(me["pos"],c["pos"])
        if not 4.3<d<14 or abs(me["pos"][2]-c["pos"][2])>3.4:
            continue
        if dist(c["pos"],zone["next_center"])>zone["next_radius"]-25:
            continue
        if d<dbest:dbest,qbest=d,c
    return qbest

class UniversalSculptor:
    def __init__(self):
        self.stage="IDLE"
        self.cube_id=None
        self.cube_count=None
        self.cube_pos=None
        self.orig_pos=None
        self.kinds=[]
        self.drop_ids={}
        self.drop_order=[]
        self.started=-100.
        self.slot_started=-100.

    def reset(self):
        self.__init__()

    def silence(self,act,move=(0.,0.)):
        act.pop("drop",None)
        act.pop("take",None)
        act["move"]=list(move)
        act["boost"]=False
        act["jump"]=False
        act["fire"]=[False,False]
        act["reload"]=False
        return act

    def snapshot(self,obs):
        for event in obs.get("events",()):
            if event["type"]=="dropped" and event.get("kind") in self.kinds:
                self.drop_ids[event["kind"]]=event["id"]

    def find_pickup(self,obs,kind):
        choices=[w for w in obs.get("pickups",()) if w["kind"]==kind
                 and self.orig_pos is not None and
                 dist(w["pos"],self.orig_pos)<3.5]
        known=self.drop_ids.get(kind)
        if known is not None:
            match=next((w for w in choices if w["id"]==known),None)
            if match:return match
        return min(choices,key=lambda w:dist(w["pos"],self.orig_pos),
                   default=None)

    def apply(self,obs,act,nearest,last_damage,thresholds,zone):
        me=obs["self"]
        now=obs["t"]
        self.snapshot(obs)
        if self.stage=="IDLE":
            c=safe_candidate(obs,me,nearest,last_damage,thresholds,zone)
            if c is None:return act
            self.stage="STOP"
            self.started=now
            self.cube_id=c["id"]
            self.cube_count=me["cubes"]
            self.cube_pos=tuple(c["pos"])
            self.kinds=[w["kind"] for w in me["weapons"] if w]
            self.drop_order=([w["kind"] for w in reversed(me["weapons"]) if w])
            self.orig_pos=None

        if self.stage=="STOP":
            if (now-self.started>5 or nearest<160 or
                    not any(c["id"]==self.cube_id for c in obs["cubes"])
                    or obs.get("offer")):
                self.reset();return act
            d=dist(me["pos"],self.cube_pos)
            speed=hypot(*me["vel"][:2])
            if d<=4.25:
                # Already too close to guarantee offer draw happens disarmed.
                self.reset();return act
            if d>7.4 and speed<1.5:
                a=((self.cube_pos[0]-me["pos"][0])/d*.65,
                   (self.cube_pos[1]-me["pos"][1])/d*.65)
                return self.silence(act,a)
            if d>7.4 and speed>=1.5:
                return self.silence(act,(0.,0.))
            if speed>1.5:
                return self.silence(act,(0.,0.))
            # Stable about 4.5-7.4m from a cube, safely outside auto-collect.
            self.orig_pos=tuple(me["pos"])
            self.stage="DROP"
            self.slot_started=now

        if self.stage=="DROP":
            if me["cubes"]>self.cube_count or obs.get("offer"):
                # If a cube auto-collected early, don't make the mistake
                # of stripping another weapon after the offer was drawn.
                self.stage="REARM"
            elif now-self.started>8 or nearest<125:
                self.stage="REARM"
            else:
                to_drop=next((kind for kind in self.drop_order
                              if any(w and w["kind"]==kind for w in me["weapons"])),
                             None)
                if to_drop is not None:
                    slot=next(i for i,w in enumerate(me["weapons"])
                              if w and w["kind"]==to_drop)
                    self.silence(act)
                    act["drop"]=slot
                    return act
                self.stage="COLLECT"

        if self.stage=="COLLECT":
            if me["cubes"]>self.cube_count or obs.get("offer"):
                self.stage="REARM"
            elif (now-self.started>12 or nearest<125 or
                    not any(c["id"]==self.cube_id for c in obs["cubes"])):
                self.stage="REARM"
            else:
                d=dist(me["pos"],self.cube_pos)
                if d>2.7:
                    a=((self.cube_pos[0]-me["pos"][0])/d,
                       (self.cube_pos[1]-me["pos"][1])/d)
                    return self.silence(act,a)
                # Stop to avoid sailing beyond 4m of the dropped weapons.
                return self.silence(act,(0.,0.))

        if self.stage=="REARM":
            missing=[kind for kind in ("gun",)+tuple(
                    k for k in self.kinds if k!="gun")
                    if kind in self.kinds and
                    not any(w and w["kind"]==kind for w in me["weapons"])]
            if not missing:
                self.reset()
                return act
            if now-self.started>19:
                self.reset()
                return act
            pickup=self.find_pickup(obs,missing[0])
            if pickup is None:
                # If an attacker arrived, prioritize movement and surviving.
                return act
            d=dist(me["pos"],pickup["pos"])
            if nearest<60 and d>4:return act
            if d<3.85 and abs(me["pos"][2]-pickup["pos"][2])<3.9:
                act["take"]=pickup["id"]
                act.pop("drop",None)
                return act
            if nearest>100:
                v=((pickup["pos"][0]-me["pos"][0])/max(d,.01),
                   (pickup["pos"][1]-me["pos"][1])/max(d,.01))
                return self.silence(act,v)
            return act
        return act
