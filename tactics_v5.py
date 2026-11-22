"""V5 tactical state helpers. Pure functions, bounded work, no privileged info."""
import math

def xy_distance(a,b):
    return math.hypot(a[0]-b[0],a[1]-b[1])

def classify_danger(me,enemies,arena,max_checks=4):
    """Track visible firing lanes, not all enemies inside memory radius."""
    p=me["pos"]
    # A charging laser at 260m is more dangerous than a closer gunner.
    # Prioritize charging lasers, then other lasers, while bounding costly
    # geometry tests to max_checks per decision.
    def priority(e):
        d=xy_distance(p,e["pos"])
        laser="laser" in e.get("weapons",())
        threatening=laser and d <= 280
        return (0 if threatening and e.get("charging") else
                1 if threatening else 2, d)
    # Cheap proximity counts MUST include *all* visible enemies; selecting
    # the four most dangerous firing lanes must never hide a gunner standing
    # directly beside us. Always reserve one geometry check for the nearest.
    distances=[(xy_distance(p,e["pos"]),e) for e in enemies]
    closest=min((d for d,_ in distances),default=math.inf)
    near=sum(d<85 for d,_ in distances)
    closest_enemy=min(distances,key=lambda pair:pair[0])[1] if distances else None
    ordered=sorted(enemies,key=priority)
    chosen=([closest_enemy] if closest_enemy is not None else [])
    chosen.extend(e for e in ordered if e is not closest_enemy)
    chosen=chosen[:max_checks]
    exposed=lasers=charging=0
    for e in chosen:
        d=xy_distance(p,e["pos"])
        # A laser reaches 280m; gun-only threats stop nearer.
        equipment=e.get("weapons",())
        if d > (280 if "laser" in equipment else 235): continue
        src=(e["pos"][0],e["pos"][1],e["pos"][2]+7*(1+.05*e.get("cubes",0)))
        dest=(p[0],p[1],p[2]+.55*me["stats"]["height"])
        if arena.shot(src,dest):
            exposed+=1
            if "laser" in e.get("weapons",()):
                lasers+=1
                if e.get("charging"): charging+=1
    return dict(exposed=exposed,near=near,lasers=lasers,charging=charging,closest=closest)

def next_mode(previous,hp,danger,zone_urgent,now,last_damage,last_hit,has_objective=False,has_cover=False):
    """Priority policy: storm, incoming laser, escape, recover, farm, fight."""
    if zone_urgent: return "ZONE"
    if danger["charging"]: return "EVADE"
    exposed=danger["exposed"]
    if previous=="HEAL" and hp<.89 and exposed==0: return "HEAL"
    if hp<.55 and (danger["lasers"] or exposed>=2): return "EVADE"
    if hp<.76 and exposed==0 and has_cover: return "HEAL"
    if previous=="EVADE" and hp<.62 and exposed>0: return "EVADE"
    # Do not continue farming in an open laser lane. Laser hits
    # cost far more than a marginal cube pickup is worth.
    if has_objective and (exposed==0 or
                          hp>.73 and danger["closest"]>105 and not danger["lasers"]):
        return "FARM"
    if exposed>0: return "FIGHT"
    if hp<.68 and now-max(last_damage,last_hit)<5.4 and has_cover: return "HEAL"
    return "TRAVEL"

def candidate_resource_target(objective,obs):
    if not objective: return None
    group,ident,_=objective
    if group not in ("crates","mechs"): return None
    return next((a for a in obs[group] if a["id"]==ident),None)

def energy_floor(me,storm_emergency=False):
    return 7.0 if storm_emergency else min(38.0,max(24.0,.27*me.get("max_energy",100.0)))

def zone_eta(lower_bound,direct_clear,route_points,speed,safety_factor=.75):
    length=max(0.0,lower_bound)
    if route_points and len(route_points)>1:
        length=max(length,sum(xy_distance(a,b) for a,b in zip(route_points,route_points[1:])))
    elif not direct_clear:
        length=1.85*length+15
    return length/max(1.0,speed*safety_factor)

def should_commit_resource(now,locked_at,available,risk):
    return available and not risk and now-locked_at<3.5


def should_skirmish(mode, visible, retreat, urgent, final, nearest):
    """Orbit opponents only when an exposed firing lane calls for a fight."""
    return bool(visible and mode == "FIGHT" and not retreat and not urgent
                and not final and 13 < nearest < 145)
