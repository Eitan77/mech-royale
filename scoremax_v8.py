"""V8 score-maximizing policies.

Match placement is the ONLY reward. One dying opponent = one placement
point, but early kills can intensify the cooperating practice squad.
This module handles health economics, NPC interruptions and risk-aware
mode selection. It does not use hidden seeds or opponent state.
"""
import math

def distance(a,b):
    return math.hypot(a[0]-b[0],a[1]-b[1])

def npc_pressure(me,visible,arena,now,last_npc_damage=-999):
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
        limit=90 if recent else 48
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
    if resource_safe and hp>=.58:
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
