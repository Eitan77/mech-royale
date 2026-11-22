"""V7 policy primitives: survival is worth placement points, not tags.
All heuristics are exposed as pure functions for adversarial tests.
No hidden game state or privileged engine data.
"""
import math

def dist(a,b):
    return math.hypot(a[0]-b[0],a[1]-b[1])

def angle_delta(a,b):
    return abs(math.remainder(a-b,math.tau))

def aimed_at_us(enemy,me,tolerance=.45):
    """A torso pointed at our current hit-cylinder could be shooting us."""
    if "aim" not in enemy:return False
    delta=math.atan2(me["pos"][1]-enemy["pos"][1],
                     me["pos"][0]-enemy["pos"][0])
    d=dist(enemy["pos"],me["pos"])
    angular_radius=math.atan2(me["stats"].get("radius",2.5)+.75,max(d,1.0))
    return angle_delta(enemy["aim"][0],delta) <= tolerance+angular_radius

def situational_danger(me,enemies,arena,max_checks=5):
    """Bound line-of-sight checks but never ignore the nearest attacker.

    "exposed" is *potential* incoming LOS, not proof an enemy is shooting;
    "aimed" is a separate measure of immediate engagement intent.
    """
    p=me["pos"]
    pairs=[(dist(p,e["pos"]),e) for e in enemies]
    nearest=min((d for d,_ in pairs),default=float("inf"))
    close=sum(d<60 for d,_ in pairs)
    near=sum(d<110 for d,_ in pairs)
    facing=sum(d<230 and aimed_at_us(e,me) for d,e in pairs)
    def order(item):
        d,e=item
        laser="laser" in e.get("weapons",())
        return (0 if laser and e.get("charging") and d<280 else
                1 if aimed_at_us(e,me) and d<230 else
                2 if laser and d<280 else 3,d)
    priority=sorted(pairs,key=order)
    closest_enemy=min(pairs,key=lambda item:item[0])[1] if pairs else None
    selected=[closest_enemy] if closest_enemy is not None else []
    selected.extend(e for _,e in priority if e is not closest_enemy)
    exposed=charged_exposed=laser_exposed=aimed_exposed=0
    for e in selected[:max_checks]:
        d=dist(p,e["pos"])
        laser="laser" in e.get("weapons",())
        if d>(280 if laser else 235):continue
        size=1+.05*e.get("cubes",0)
        muzzle=(e["pos"][0],e["pos"][1],
                e["pos"][2]+7*size)
        center=(p[0],p[1],p[2]+.55*me["stats"].get("height",9))
        if not arena.shot(muzzle,center):continue
        exposed+=1
        if laser:
            laser_exposed+=1
            if e.get("charging"):charged_exposed+=1
        if aimed_at_us(e,me):aimed_exposed+=1
    return dict(exposed=exposed,laser_exposed=laser_exposed,
                charged_exposed=charged_exposed,aimed_exposed=aimed_exposed,
                close=close,near=near,closest=nearest,facing=facing)

def mode_v7(previous,hp,danger,urgent,now,last_damage,last_hit,has_resource):
    if urgent:return "ZONE"
    if danger["charged_exposed"]:return "EVADE"
    if danger["close"]>=2 and hp<.80:return "EVADE"
    if danger["aimed_exposed"]>=2 and hp<.80:return "EVADE"
    if hp<.48 and danger["exposed"]:return "EVADE"
    if previous=="HEAL" and hp<.94 and danger["charged_exposed"]==0 and danger["aimed_exposed"]==0:
        return "HEAL"
    if hp<.86 and danger["exposed"]==0:return "HEAL"
    if hp<.74 and not danger["aimed_exposed"] and danger["close"]==0:
        return "HEAL"
    # Being in the broad firing range of an enemy 150m away is not
    # enough to abandon the only useful starting loot.
    safe_resource=(danger["close"]==0 and danger["charged_exposed"]==0
                   and danger["aimed_exposed"]==0 and
                   (danger["laser_exposed"]==0 or danger["closest"]>145))
    if has_resource and safe_resource:return "FARM"
    if danger["close"] or danger["aimed_exposed"]>0:
        return "FIGHT"
    if danger["exposed"] and hp<.8:return "EVADE"
    return "TRAVEL"

def deliberate_mech_fire(me,target,mode,now,last_damage,zone):
    """Stop starting 200m duels just because a mech is visible.

    Defensive combat and finishing near-dead enemies are allowed. Storm
    controller has its own last-circle guard. Avoid firing while healing
    or looting. Damage we deal resets our own regen delay.
    """
    if target is None or target.get("kind")!="mech":return False
    if mode in ("HEAL","FARM","TRAVEL","ZONE"):return False
    d=dist(me["pos"],target["pos"])
    if d>230:return False
    hp=target.get("hp",1400)
    if hp<=min(240,.23*target.get("max_hp",1400)) and d<125:return True
    if mode=="EVADE":
        return False  # lightning shorts handled independently
    if mode!="FIGHT":return False
    # Defend when enemy is actually shooting at us or very close.
    if d<57:return True
    if d<135 and aimed_at_us(target,me,tolerance=.5):
        return True
    return False

def should_silence(me,mode,zone,now,damage,urgent):
    """Only become acoustically quiet while safe and not needing travel."""
    if mode!="HEAL" or urgent or not me["grounded"] or not me["in_zone"]:
        return False
    if zone["next_radius"]<=0:return False
    p=me["pos"]
    # Do not camp outside the NEXT circle unless ample time remains.
    next_margin=zone["next_radius"]-dist(p,zone["next_center"])
    time_left=zone["shrink_end"]-now
    speed=me["stats"]["walk_speed"]
    eta=max(0,-next_margin+8)/max(1,speed*.65)
    return next_margin>=8 or time_left>eta+22

def silence_movement(me,move,hold=False):
    """Under 5 m/s movement makes no footsteps; zero at a defensible refuge."""
    if hold:return [0.,0.]
    speed=max(1.,me["stats"]["walk_speed"])
    limit=min(.38,4.5/speed)
    magnitude=math.hypot(*move)
    if magnitude<1e-6:return [0.,0.]
    return [move[0]/magnitude*min(limit,magnitude),
            move[1]/magnitude*min(limit,magnitude)]

def upgrade_v7(choices,me,now):
    """Survival-first priority, adapted to existing secondary weapon."""
    hp=me["hp"]/max(1,me["max_hp"])
    has=set(w["kind"] for w in me["weapons"] if w)
    scores={
      "nanites":100 if now<330 and hp>.28 else 72,
      "plating":100 if hp<.55 else 92,
      "armor":89 if hp<.6 else 84,
      "servos":82,
      "jets":81 if now<350 else 94,
      "capacitor":71 if me["max_energy"]<130 else 61,
      "reactor":72,
      "gyros":52,
      "sensors":44,
      "gun_damage":58,
      "gun_rate":49,
      "gun_velocity":53,
      "gun_mag":42,
      "laser_charge":75,
      "laser_damage":93 if "laser" in has and me["cubes"]<5 else 63,
      "laser_pierce":35,
      "lightning_range":87 if "lightning" in has else 56,
      "lightning_efficiency":69,
      "lightning_chain":50,
      "mortar_splash":40,
      "mortar_reload":41,
      "mortar_velocity":32
    }
    return max(range(len(choices)),key=lambda i:scores.get(choices[i]["id"],40))
