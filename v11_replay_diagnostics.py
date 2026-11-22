"""Non-reactive official-kit observation replay.

This does NOT simulate opponent reactions or score placement. It diagnoses
whether the new V11 hard-shadow logic actually triggers under the concrete
attack sequence in the starter archive.
"""
import collections,gzip,json,os
from pathlib import Path
from controller import Bot
from pursuit_v11 import focus_fire
KIT=Path(os.environ.get("MECH_KIT","/tmp/mech-kit/mechfight-kit"))
with gzip.open(KIT/"check"/"stream.jsonl.gz","rt") as f:
    hello=json.loads(next(f))
    observations=[json.loads(line) for line in f if line.strip()]
hello["map"]["dir"]=str(KIT/"arena")
bot=Bot(hello)
count=collections.Counter()
for o in observations:
    if o.get("type")!="obs":continue
    enemy=[e for e in o["mechs"] if e["kind"]=="mech"]
    if focus_fire(o["self"],enemy,o["projectiles"],o["t"],bot.last_damage):
        count["confirmed_attack_cues"]+=1
    a=bot.act(o)
    count["mode_"+bot.mode]+=1
    count["shadow_active"]+=bool(getattr(bot,"shadow_active",False))
    count["shadow_sheltered"]+=bool(getattr(bot,"shadow_sheltered",False))
    count["shadow_scan_updates"]+=bot.shadow_scan_at==o["t"]
    count["firing_commands"]+=sum(bool(f) for f in a.get("fire",[]))
    count["boost_commands"]+=bool(a.get("boost",False))
    count["upgrade_offer_sculpt"]+=getattr(getattr(bot,"sculptor",None),"stage","IDLE")!="IDLE"
count["ticks"]=len(observations)
count["precomputed_prism_corners"]=len(bot.shadow_atlas.corners)
print("V11_NON_REACTIVE_DIAGNOSTICS",dict(count))
