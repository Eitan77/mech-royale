"""V11X full-controller smoke tests on authentic hello/map."""
import copy,gzip,json,os,unittest
from pathlib import Path
from controller import Bot
KIT=Path(os.environ.get("MECH_KIT","/tmp/mech-kit/mechfight-kit"))

class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with gzip.open(KIT/"check"/"stream.jsonl.gz","rt") as f:
            cls.hello=json.loads(next(f))
            cls.first=json.loads(next(f))
        cls.hello["map"]["dir"]=str(KIT/"arena")
    def first_obs(self):
        o=copy.deepcopy(self.first)
        p=o["self"]["pos"]
        o["t"]=5.
        o["events"]=[]
        o["mechs"]=[]
        o["sounds"]=[]
        o["self"]["vel"]=[0.,0.,0.]
        o["self"]["grounded"]=True
        o["self"]["hp"]=o["self"]["max_hp"]
        o["zone"]["next_center"]=p[:2]
        o["zone"]["next_radius"]=380.
        o["cubes"]=[{"id":5011,"pos":[p[0]+6.,p[1],p[2]]}]
        return o
    def test_safe_first_threshold_disarms_at_real_controller_output(self):
        bot=Bot(copy.deepcopy(self.hello))
        o=self.first_obs()
        bot.arena.walk=lambda *args:True
        act=bot.act(o)
        self.assertEqual(act.get("drop"),0)
        self.assertEqual(act["move"],[0.,0.])
        self.assertEqual(act["fire"],[False,False])
        self.assertEqual(bot.sculptor.stage,"DROP")
    def test_offering_choices_is_not_ignored_while_rearming(self):
        bot=Bot(copy.deepcopy(self.hello))
        o=self.first_obs()
        bot.arena.walk=lambda *args:True
        bot.act(o)
        p=o["self"]["pos"]
        o2=copy.deepcopy(o)
        o2["tick"]+=2
        o2["t"]+=.1
        o2["self"]["weapons"]=[None,None]
        o2["events"]=[{"type":"dropped","id":8801,
                        "kind":"gun","slot":0}]
        o2["pickups"]=[{"id":8801,"kind":"gun","pos":p}]
        bot.act(o2) # COLLECT: walk toward cube, do not yet take gun
        o3=copy.deepcopy(o2)
        o3["tick"]+=2
        o3["t"]+=.1
        o3["self"]["pos"]=[p[0]+2.8,p[1],p[2]]
        o3["self"]["cubes"]=1
        o3["cubes"]=[]
        o3["offer"]={"id":12,"expires":o3["t"]+5.,
                     "choices":[{"id":"armor"},{"id":"nanites"},{"id":"sensors"}]}
        act=bot.act(o3)
        self.assertEqual(act.get("take"),8801)
        self.assertEqual(act.get("pick"),1)
        self.assertEqual(bot.sculptor.stage,"REARM")
if __name__=="__main__":unittest.main()
