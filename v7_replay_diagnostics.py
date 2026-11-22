"""Diagnostics on a *non-reactive* recorded observation stream.

Not a simulation, not a placement score. Prints behavioral statistics only.
"""
import collections,gzip,json,os
from pathlib import Path
from controller import Bot
P=Path(os.environ.get("MECH_KIT","/tmp/mech-kit/mechfight-kit"))
with gzip.open(P/"check"/"stream.jsonl.gz","rt") as f:
    hello=json.loads(next(f))
    observations=[json.loads(s) for s in f if s.strip()]
hello["map"]["dir"]=str(P/"arena")
bot=Bot(hello)
counts=collections.Counter()
for o in observations:
    if o.get("type")!="obs":continue
    a=bot.act(o)
    counts[bot.mode]+=1
    counts["commands_fire"]+=sum(bool(v) for v in a.get("fire",[]))
    counts["commands_boost"]+=bool(a.get("boost"))
    counts["commands_take"]+="take" in a
    counts["commands_pick"]+="pick" in a
    counts["commands_drop"]+="drop" in a
    counts["commands_reload"]+=bool(a.get("reload"))
    counts["with_visible_enemy"]+=any(m["kind"]=="mech" for m in o["mechs"])
    counts["with_visible_resource"]+=bool(o["crates"] or o["cubes"] or o["pickups"])
print("REPLAY_DIAGNOSTICS_NON_REACTIVE",dict(counts))
