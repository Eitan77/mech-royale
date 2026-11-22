"""V10 audited mechanics.

Small, bounded, unit-tested decisions that resolve contradictions between
V9's stealth, recovery, shooting and movement modules. Game servers remain
authoritative; none of these tests is a simulated placement score.
"""
import math

def xy(a,b):
    return math.hypot(a[0]-b[0],a[1]-b[1])

def imminent_projectile(me, projectiles, zone=None, horizon=.75):
    """Detect a projectile on a plausible intercept with our hit cylinder.

    Uses relative 2D velocity and checks vertical overlap at nearest
    approach. Conservative screening, not a perfect physics emulator.
    """
    p=me["pos"]; velocity=me.get("vel",(0.,0.,0.))
    size=1+.05*me.get("cubes",0)
    radius=2.5*size+.65
    height=9*size
    if zone is not None and zone.get("dps",0)>=160:
        margin=zone["radius"]-xy(p,zone["center"])
        if 0<=margin<3.5:
            # Surrendering a tiny safe circle costs more than a gun bullet.
            # A late mortar is handled only if it is clearly deadly.
            projectiles=[q for q in projectiles if q.get("kind")=="mortar"]
    for q in projectiles[:20]:
        loc=q["pos"];v=q["vel"]
        rx,ry=loc[0]-p[0],loc[1]-p[1]
        vx,vy=v[0]-velocity[0],v[1]-velocity[1]
        vv=vx*vx+vy*vy
        t=max(0.,min(horizon, -(rx*vx+ry*vy)/max(.01,vv)))
        if t<.005 or t>=horizon:continue
        lateral=math.hypot(rx+vx*t,ry+vy*t)
        mortar=q["kind"]=="mortar"
        if lateral>radius+(6.0 if mortar else .35):
            continue
        z=loc[2]+v[2]*t-(.5*22*t*t if mortar else 0.)
        ourfeet=p[2]+(velocity[2]*t if not me.get("grounded",True) else 0.)
        if mortar:
            # Only dodge a mortar whose predicted impact passes near the
            # actual vertical space. A shell 40m above is not imminent.
            if ourfeet-9<=z<=ourfeet+height+8:return True
        elif ourfeet-.65<=z<=ourfeet+height+.65:
            return True
    return False

def sniper_choice(me,enemies,zone,now,alive,ambush_filter):
    """Find a valid ONE-SHOT 150m+ isolated target to aim at."""
    if not enemies:return None
    valid=[e for e in enemies
           if ambush_filter(me,e,enemies,zone,now,alive)]
    return min(valid,key=lambda e: (e["hp"],xy(me["pos"],e["pos"])),
               default=None)

def resource_laser_silence(me,target,near_mech,retreat,urgent,now):
    """One full-charge laser can kill a crate, or a drone after 3 cubes.

    A second weapon's gunfire isn't needed during that charge, and emits
    an avoidable 320-meter sound before the kill. Other mechs in range,
    emergency storm or retreat disables the farming optimization.
    """
    if not target or target.get("kind") not in ("crate","npc"):
        return False
    if retreat or urgent or now>260 or near_mech<120:return False
    laser=next((w for w in me["weapons"] if w and w["kind"]=="laser"),None)
    if not laser:return False
    # A failed or blocked laser shot must not suppress the arm gun throughout
    # the 1.65s cooldown. Silence applies only when charging or nearly ready.
    if laser.get("cooldown",0)>.15 and not laser.get("charge",0):
        return False
    power=laser["stats"]["damage"]*(1+.04*min(10,me["cubes"]))
    return power>=target.get("hp",300) and me["hp"]>.70*me["max_hp"]

def late_storm_armor_trade(me,zone,projectile=False):
    """A tiny endgame safe-circle margin outweighs ordinary dodge value."""
    if zone.get("dps",0)<160:return False
    margin=zone["radius"]-xy(me["pos"],zone["center"])
    return me.get("in_zone",True) and margin>0 and margin<5 and not projectile

def safety_silence(mode,charging,ambush_target,laser_target,target):
    """When a strategic laser is charging, never fire the loud arm gun."""
    return (bool(charging) and ambush_target is not None
            and laser_target==ambush_target
            and target is not None and target.get("id")==ambush_target)
