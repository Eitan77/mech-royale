"""V8 score-maximizing policies.

Match placement is the ONLY reward. One dying opponent = one placement
point, but early kills can intensify the cooperating practice squad.
This module handles health economics, NPC interruptions and risk-aware
mode selection. It does not use hidden seeds or opponent state.
"""
import math

def distance(a,b):
    return math.hypot(a[0]-b[0],a[1]-b[1])

def npc_pressure(me,visible,arena,now,last_npc_damage=-999,chasing_npc_id=None):
    """Risk that a drone prevents regeneration with 1s NPC bullets.

    NPCs can attack any mech within 45m of their home, and chase out to
    90m when provoked. Exact home/target isn't observed, so widen only
    if we've recently received an NPC hit.
    """
    recent=now-last_npc_damage<3.5
    p=me["pos"]
    active=[]
    visible=sorted((e for e in visible if e.get("kind")=="npc"),
                   key=lambda e:distance(p,e["pos"]))[:5]
    for e in visible:
        d=distance(p,e["pos"])
        limit=90 if recent and (chasing_npc_id is None or
                              e.get("id")==chasing_npc_id) else 48
        if d>limit:continue
        eye=(e["pos"][0],e["pos"][1],e["pos"][2]+2.8)
        body=(p[0],p[1],p[2]+.5*me["stats"]["height"])
        if arena.shot(eye,body):
            active.append(e)
    return sorted(active,key=lambda e:distance(p,e["pos"]))

def score_phase(alive,now):
    """The direct placement points guaranteed if the bot were next to die."""
    # If alive=N, N-1 other mechs can still die first, and 16-N have
    # already died, so 16-N points are banked in the current match.
    return max(0,16-alive)

def mode_v8(previous,hp,danger,urgent,now,last_damage,last_hit,
            has_resource,npc_active=False,alive=16):
    """Aim to recover and *progress*. Do not become permanently stationary.

    Early kills increase pursuit pressure, but passive HEAL with nearby
    NPC bullets, uncovered gunners, or loot available cannot build strength.
    """
    if urgent:return "ZONE"
    if danger.get("charged_exposed",0):return "EVADE"
    if npc_active:
        if hp<.72:return "EVADE"
        return "FIGHT"  # fight or leave, but no silent heal while being shot
    close=danger.get("close",0)
    exposed=danger.get("exposed",0)
    aimed=danger.get("aimed_exposed",0)
    if (close>=2 or aimed>=2) and hp<.84:return "EVADE"
    if hp<.45 and exposed:return "EVADE"
    resource_safe=(has_resource and close==0 and aimed==0
                   and not danger.get("charged_exposed",0)
                   and (not danger.get("laser_exposed",0)
                        or danger.get("closest",999)>155))
    # Once 10 opponents are eliminated, we have already banked 10 points.
    # Late resource greed is not worth risking that placement for marginal cubes.
    # Keep healing or moving toward the next circle instead.
    if resource_safe and hp>=.58 and not (alive<=6 and now>220):
        return "FARM"
    if previous=="HEAL" and hp<.82 and exposed==0 and not resource_safe:
        return "HEAL"
    if hp<.62 and exposed==0:return "HEAL"
    if hp<.68 and aimed==0 and close==0 and not resource_safe:
        return "HEAL"
    if close or aimed:return "FIGHT"
    if exposed and hp<.78:return "EVADE"
    return "TRAVEL"

def immediate_npc_escape(me,npc,zone,arena,size):
    """Choose a short reachable direction away from an NPC while staying safe."""
    p=me["pos"];q=npc["pos"]
    angle=math.atan2(p[1]-q[1],p[0]-q[0])
    current=distance(p,zone["center"])
    candidates=[]
    for offset in (0,.45,-.45,1.,-1.,1.5,-1.5):
        a=angle+offset
        trial=(p[0]+22*math.cos(a),p[1]+22*math.sin(a))
        if distance(trial,zone["center"])>=zone["radius"]-7:continue
        if not arena.walk(p[:2],trial,size):continue
        score=distance(trial,q)-.4*distance(trial,zone["next_center"])
        candidates.append((score,trial))
    return max(candidates)[1] if candidates else None

def endgame_priority(alive,hp,zone,now,enemy_near,ours_dist):
    """Return survival-first if zone damage is large relative to enemy fire.

    The clock cap isn't a kill objective: placements continue to accrue as
    the other bots die. Never leave a safe final center to chase a target.
    """
    severe=zone["dps"]>=100 or zone["next_radius"]<=25
    return severe and (ours_dist<max(20.,zone["radius"]*.35) or alive<=8)

def opportunistic_kill(target,me,alive,nearby_allies):
    """Only chase a *nearly finished* opponent when payoff beats likely aggro.

    A hit is not rewarded. A kill is one placement point. Low TTK is valuable
    when the enemy is separated from the rest of the cooperating squad.
    """
    if target is None or target.get("kind")!="mech":return False
    d=distance(target["pos"],me["pos"])
    if d>95:return False
    if nearby_allies>=2:return False
    my_health=me["hp"]/max(1,me["max_hp"])
    target_health=target["hp"]/max(1,target.get("max_hp",1400))
    return my_health>.60 and (target_health<.14 or
                              target.get("hp",1400)<165)

def expected_placement_proxy(alive,likelihoods):
    """Simple identity: score is sum of other deaths before ours.

    Probabilities should come from scored rollouts, NOT guessed constants.
    """
    return 16-alive+sum(max(0.,min(1.,p)) for p in likelihoods)


def laser_ambush(me,target,all_enemies,zone,now,alive):
    """A rare isolated, unsuspecting laser opportunity.

    No points for damage; only attempt if rear damage could *finish* a
    compromised enemy promptly, without drawing the whole practice squad.
    Trees can obscure vision, but their effect is not assumed here.
    """
    if target is None or target.get("kind")!="mech" or alive<=6:
        return False
    if now>320 or zone["dps"]>=100 or me["hp"]/max(1.,me["max_hp"])<.86:
        return False
    if not any(w and w["kind"]=="laser" for w in me["weapons"]):
        return False
    d=distance(me["pos"],target["pos"])
    if not 146<d<196:return False
    if target.get("charging"):return False
    # Rear half is angle >90deg from target torso. Require >120deg.
    from_enemy=math.atan2(me["pos"][1]-target["pos"][1],
                          me["pos"][0]-target["pos"][0])
    if abs(math.remainder(from_enemy-target["aim"][0],math.tau))<2.1:
        return False
    # A second enemy seeing our charge defeats the stealth advantage.
    if any(e["id"]!=target["id"] and
           (distance(me["pos"],e["pos"])<185 or
            distance(target["pos"],e["pos"])<90)
           for e in all_enemies):
        return False
    laser=next(w for w in me["weapons"] if w and w["kind"]=="laser")
    damage=laser["stats"]["damage"]*(1+.04*min(10,me["cubes"]))
    rear_damage=damage*1.5*(1.6 if "mortar" in target.get("weapons",()) else 1.)
    # One shot early, two shots only after the initial squad hunt has eased.
    max_shots=1 if now<140 else 2
    if target["hp"]>rear_damage*max_shots*.98:
        return False
    if zone["next_radius"]<75 and distance(me["pos"],zone["next_center"])>zone["next_radius"]-18:
        return False
    return True
