"""V8B conservative incremental changes on top of scored V5."""
import copy,gzip,json,os,unittest
from pathlib import Path
from unittest.mock import patch
from controller import Bot

KIT=Path(os.environ.get("MECH_KIT","/tmp/mech-kit/mechfight-kit"))
class Cases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with gzip.open(KIT/"check"/"stream.jsonl.gz","rt") as f:
            cls.hello=json.loads(next(f))
            cls.sample=json.loads(next(f))
        cls.hello["map"]["dir"]=str(KIT/"arena")
    def clone(self):
        return Bot(copy.deepcopy(self.hello)),copy.deepcopy(self.sample)
    def npc(self,o,d):
        p=o["self"]["pos"]
        return {"id":106,"kind":"npc","pos":[p[0]+d,p[1],p[2]],
                "vel":[0,0,0],"aim":[3.14,0],
                "hp":350,"max_hp":350}
    def test_npc_prevents_passive_heal(self):
        bot,o=self.clone()
        o["self"]["hp"]=700
        o["mechs"]=[self.npc(o,30)]
        bot.arena.shot=lambda *_:True
        bot.arena.walk=lambda *_:True
        a=bot.act(o)
        self.assertEqual(bot.mode,"EVADE")
        self.assertFalse(bot.recovering)
    def test_hidden_npc_does_not_prevent_heal(self):
        bot,o=self.clone()
        o["self"]["hp"]=700
        o["mechs"]=[self.npc(o,30)]
        bot.arena.shot=lambda *_:False
        a=bot.act(o)
        self.assertEqual(bot.mode,"HEAL")
        self.assertTrue(bot.recovering)
    def test_v5_can_still_fire_when_engaged(self):
        bot,o=self.clone()
        o["self"]["hp"]=1300
        p=o["self"]["pos"]
        o["self"]["aim"]=[0,0]
        o["mechs"]=[{"id":5,"kind":"mech",
                     "pos":[p[0]+50,p[1],p[2]],"vel":[0,0,0],
                     "aim":[3.14,0],"hp":1000,"max_hp":1400,
                     "cubes":0,"weapons":["gun"],"charging":False}]
        o["self"]["weapons"][0]["cooldown"]=0
        o["self"]["weapons"][0]["reload"]=0
        o["self"]["weapons"][0]["ammo"]=12
        bot.arena.shot=lambda *_:True
        bot.arena.walk=lambda *_:True
        with patch("controller.shot_connects",return_value=True):
            a=bot.act(o)
        self.assertEqual(bot.mode,"FIGHT")
        self.assertTrue(a["fire"][0])

if __name__=="__main__":unittest.main()
