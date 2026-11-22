"""Optional V9X upgrade-eligibility experiment.

When the mech is exactly one cube short of an upgrade threshold, dropping
a secondary weapon BEFORE collecting it should exclude that weapon's
upgrades from the drawn offer. The official protocol documents weapon
eligibility at offer-draw time, but no scored trial has established the
payoff. This is dangerous and intentionally isolated in a separate branch.

Never drop the starting gun. Always attempt to recover the secondary.
"""
import math

THRESHOLDS=(1,3,6,10,15,21)

def xy(a,b):
    return math.hypot(a[0]-b[0],a[1]-b[1])

class UpgradeSculptor:
    def __init__(self):
        self.stage="IDLE"
        self.cube_id=None
        self.cube_count=None
        self.cube_pos=None
        self.weapon_kind=None
        self.drop_pos=None
        self.pickup_id=None
        self.started=-100.

    def _reset(self):
        self.stage="IDLE"
        self.cube_id=self.cube_count=self.cube_pos=None
        self.weapon_kind=self.drop_pos=self.pickup_id=None

    def _locate_weapon(self,obs):
        for event in obs.get("events",()):
            if event.get("type")=="dropped" and event.get("kind")==self.weapon_kind:
                self.pickup_id=event["id"]
        opts=[q for q in obs.get("pickups",())
              if q.get("kind")==self.weapon_kind and
              self.drop_pos is not None and xy(q["pos"],self.drop_pos)<5.5]
        if self.pickup_id is not None:
            chosen=next((q for q in opts if q["id"]==self.pickup_id),None)
            if chosen is not None:return chosen
        return min(opts,key=lambda q:xy(q["pos"],self.drop_pos),default=None)

    def _eligible(self,obs,nearest,urgent,arena):
        me=obs["self"];z=obs["zone"]
        if urgent or obs["t"]>230 or me["cubes"]+1 not in THRESHOLDS:
            return None
        if obs.get("offer") or not me.get("grounded",False) or not me.get("in_zone",False):
            return None
        if z["next_radius"]<140 or nearest<220:
            return None
        if me["hp"]<.95*me["max_hp"] or me["energy"]<75:
            return None
        if len(me["weapons"])<2 or not me["weapons"][0] or not me["weapons"][1]:
            return None
        if me["weapons"][0]["kind"]!="gun" or me["weapons"][1]["kind"]=="gun":
            return None
        if me["weapons"][1].get("charge",0)>0:return None
        for cube in sorted(obs.get("cubes",()),
                           key=lambda c:xy(me["pos"],c["pos"])):
            dist=xy(me["pos"],cube["pos"])
            if not 5.0<dist<6.8 or abs(me["pos"][2]-cube["pos"][2])>3.4:
                continue
            if not arena.walk(me["pos"][:2],cube["pos"][:2],
                              1+.05*me["cubes"]):
                continue
            return cube
        return None

    def _navigate(self,act,me,point,quiet=False):
        d=xy(me["pos"],point)
        if d<2:return False
        act["move"]=[(point[0]-me["pos"][0])/d,
                     (point[1]-me["pos"][1])/d]
        act["boost"]=False
        act["jump"]=False
        act["fire"]=[False,False] if quiet else act.get("fire",[False,False])
        return True

    def apply(self,obs,act,nearest,urgent,arena):
        """Mutates and returns act. Never cancels storm flight for an offer."""
        me=obs["self"];now=obs["t"]
        if self.stage!="IDLE" and (urgent or now-self.started>12.):
            # Abandon the cube manipulation but recover the weapon if possible.
            self.stage="REARM" if not urgent else "ABORT"
        if self.stage=="IDLE":
            cube=self._eligible(obs,nearest,urgent,arena)
            if cube is None:return act
            self.stage="DISARM"
            self.started=now
            self.cube_id=cube["id"]
            self.cube_count=me["cubes"]
            self.cube_pos=tuple(cube["pos"])
            self.drop_pos=tuple(me["pos"])
            self.weapon_kind=me["weapons"][1]["kind"]
            self.pickup_id=None
            act["drop"]=1
            act.pop("take",None)
            act["move"]=[0,0]
            act["boost"]=False
            act["jump"]=False
            act["fire"]=[False,False]
            return act

        if self.stage=="DISARM":
            if len(me["weapons"])>1 and me["weapons"][1] is not None:
                # Engine action processing may have differed from expectation.
                # Try once more only while safe; abort rather than get stuck.
                if now-self.started<.4 and nearest>160:
                    act["drop"]=1
                    act.pop("take",None)
                    act["move"]=[0,0]
                    act["fire"]=[False,False]
                    act["boost"]=False
                    return act
                self.stage="REARM"
            else:
                self.stage="COLLECT"
        if self.stage=="COLLECT":
            if me["cubes"]>self.cube_count or obs.get("offer"):
                self.stage="REARM"
            elif nearest<135 or now-self.started>6 or not any(
                    c["id"]==self.cube_id for c in obs.get("cubes",())):
                self.stage="REARM"
            else:
                act.pop("drop",None)
                act.pop("take",None)
                self._navigate(act,me,self.cube_pos,quiet=True)
                return act
        if self.stage=="REARM":
            if len(me["weapons"])>1 and me["weapons"][1] is not None:
                self._reset()
                return act
            pickup=self._locate_weapon(obs)
            if pickup is None:
                if now-self.started>10:self._reset()
                return act
            if (xy(me["pos"],pickup["pos"])<3.75 and
                    abs(me["pos"][2]-pickup["pos"][2])<3.9):
                act["take"]=pickup["id"]
                act.pop("drop",None)
                return act
            if not urgent and nearest>100:
                self._navigate(act,me,pickup["pos"])
            return act
        if self.stage=="ABORT":
            # Never override urgent zone movement just to rearm.
            self.stage="REARM" if not urgent else "ABORT"
        return act
