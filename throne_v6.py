"""V6 experimental final-zone policy. Do not assume collision exploit is proven.
Pure calculations for defending the final circle; preserve V5 default elsewhere.
"""
import math

def xy_distance(a,b):
    return math.hypot(a[0]-b[0],a[1]-b[1])

def zone_future(zone,now,seconds):
    """Forecast the actual moving/shrinking circle from the current observation."""
    future=now+max(0.0,seconds)
    if future<=zone["shrink_start"]:
        return tuple(zone["center"]),zone["radius"]
    if zone["shrink_end"]<=now or future>=zone["shrink_end"]:
        return tuple(zone["next_center"]),zone["next_radius"]
    depart=max(now,zone["shrink_start"])
    fraction=max(0.,min(1.,(future-depart)/(zone["shrink_end"]-depart)))
    current=zone["center"]
    target=zone["next_center"]
    return tuple(a+fraction*(b-a) for a,b in zip(current,target)),(
        zone["radius"]+fraction*(zone["next_radius"]-zone["radius"]))

def expected_zone_damage(zone,now,location,horizon=2.0,step=.1):
    """Integrate damage for a stationary candidate location across a short horizon.

    Uses 2D distance and a live zone trajectory, not the concentric 260HP/m
    approximation. This is an estimator: the official physics server wins.
    """
    if horizon<=0:return 0.
    total=0.
    n=max(1,math.ceil(horizon/max(.05,step)))
    dt=horizon/n
    for j in range(n):
        center,radius=zone_future(zone,now,(j+.5)*dt)
        if xy_distance(location,center)>radius:
            total+=zone["dps"]*dt
    return total

def defensive_contest(me,target,zone,now,retreat,recovering):
    """Open non-regenerative fire only on a mech physically contesting anchor.

    Holding the trigger does not redirect movement. The default gun can fire
    while holding ground; charged laser may slow movement and is separately
    suppressed unless we are securely centered.
    """
    if zone["next_radius"]>0 or now<375 or not target or target.get("kind")!="mech":
        return False
    if retreat or recovering:return False
    anchor=zone["next_center"]
    ours=xy_distance(me["pos"],anchor)
    theirs=xy_distance(target["pos"],anchor)
    our_radius=2.5*(1+.05*me["cubes"])
    foe_radius=2.5*(1+.05*target.get("cubes",0))
    # Intercept someone whose body could displace us before zone zero.
    return (ours<=max(6.,our_radius+2.) and
            theirs<=our_radius+foe_radius+7. and
            xy_distance(me["pos"],target["pos"])<55.)

def permit_stationary_laser(me,zone):
    """Charging halves locomotion; only charge while center lock is secure."""
    return (xy_distance(me["pos"],zone["next_center"])<1.0 and
            math.hypot(me["vel"][0],me["vel"][1])<1.75 and
            me["energy"]>12.0)

def bodyblock_min_damage(own_cubes,enemy_cubes,center_shift,dps=260.,start_radius=25.):
    """Conditional guarantee if same-height cylinders cannot overlap and
    we hold exact final center. Geometry only, not enemy AI or collision test.
    """
    assert 0<=center_shift<=start_radius
    spacing=2.5*(2+.05*(own_cubes+enemy_cubes))
    return dps*min(start_radius, start_radius*spacing/(start_radius+center_shift))
