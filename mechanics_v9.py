"""V9 exploit arbitration; no secret server state or unsupported protocol actions.

Conservative on-by-default tactical opportunities:
- final-center defensive firing only when a mech can displace us
- mortar storm-edge finishers against isolated weakened targets
- one-shot rear laser ambush outside the 140m charge audible range
- laser-vs-NPC one-hit threshold at three cubes

An optional OFF-by-default upgrade-offer pool experiment is implemented
separately because dropping the gun is not a proven profitable maneuver.
"""
import math
from scoremax_v8 import storm_mortar_finisher

def distance(a,b):
    return math.hypot(a[0]-b[0],a[1]-b[1])

def one_shot_laser_ambush(me,target,enemies,zone,now,alive):
    """Restrict the rare backshot to one-hit kill candidates.

    We make no assumptions about consecutive rear hits or a held mortar
    surviving the charging sound. Mech body size and beam aim still matter.
    """
    if not target or target.get("kind")!="mech" or alive<=6:return False
    if now<55 or now>320 or zone.get("dps",0)>=100:return False
    if me["hp"]<.88*me["max_hp"] or not me.get("in_zone",True):return False
    laser=next((w for w in me["weapons"] if w and w.get("kind")=="laser"),None)
    if not laser or laser.get("cooldown",0)>.15:return False
    d=distance(me["pos"],target["pos"])
    if d<150 or d>195:return False
    if target.get("charging"):return False
    # Only if the opponent is facing away by 135+ degrees.
    enemy_to_us=math.atan2(me["pos"][1]-target["pos"][1],
                           me["pos"][0]-target["pos"][0])
    if abs(math.remainder(target["aim"][0]-enemy_to_us,math.tau))<2.36:
        return False
    # Require almost-certain one-hit-kill assuming no cookoff multiplier.
    # Penalty accounts for the target turning while charge builds.
    damage=laser["stats"]["damage"]*(1+.04*min(10,me["cubes"]))
    if target["hp"]>damage*1.5*.87:return False
    if any(e["id"]!=target["id"] and
           (distance(me["pos"],e["pos"])<205 or
            distance(target["pos"],e["pos"])<125)
           for e in enemies):
        return False
    if (zone["next_radius"]<90 and
        distance(me["pos"],zone["next_center"])>zone["next_radius"]-18):
        return False
    return True

def easy_laser_drone(me,target):
    """Laser farm break point, exact documented cube scaling."""
    if target is None or target.get("kind")!="npc":return False
    laser=next((w for w in me["weapons"] if w and w["kind"]=="laser"),None)
    if laser is None:return False
    damage=laser["stats"]["damage"]*(1+.04*min(10,me["cubes"]))
    return damage>=target.get("hp",350)

def contest_center(me,enemy,zone,now,retreat):
    """Only allow active final-center defense where occupancy conflicts."""
    if retreat or not enemy or enemy.get("kind")!="mech":
        return False
    if zone["next_radius"]!=0 or now<375:return False
    xy1=distance(me["pos"],zone["next_center"])
    xy2=distance(enemy["pos"],zone["next_center"])
    radius=2.5*(1+.05*me["cubes"])+2.5*(1+.05*enemy.get("cubes",0))
    if xy1>max(4.5,radius*.7):return False
    if xy2>radius+5.:return False
    if abs(me["pos"][2]-enemy["pos"][2])>8.:return False
    return True

def storm_finish(me,target,enemies,zone,alive):
    """Delegates to the deliberately restrictive V8 storm-edge gate."""
    if not any(w and w["kind"]=="mortar" for w in me["weapons"]):return False
    return storm_mortar_finisher(me,target,enemies,zone,alive)

def safe_offer_sculpt_candidate(me,obs,nearest,zone):
    """Conservative eligibility for an optional experimental exploit.

    OFF by default. Dropping *every* weapon before the offer is drawn may
    increase the chance of a desired universal upgrade. It can also leave
    the bot unarmed and trigger a bad score. This function does not perform
    the drop; it is only a diagnostic/feature gate.
    """
    if obs.get("offer") is not None or nearest<230:
        return False
    if me["hp"]<.95*me["max_hp"] or me["energy"]<75:
        return False
    if not me["grounded"] or not me.get("in_zone",True):return False
    if zone["next_radius"]<140:return False
    if sum(bool(w) for w in me["weapons"])!=1:return False
    if not me["weapons"][0] or me["weapons"][0]["kind"]!="gun":return False
    if me["cubes"]+1 not in (1,3,6,10,15,21):return False
    cubes=[c for c in obs.get("cubes",[])
           if 5<distance(me["pos"],c["pos"])<7
           and abs(me["pos"][2]-c["pos"][2])<4]
    return bool(cubes)
