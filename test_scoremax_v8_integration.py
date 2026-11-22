"""V8 end-to-end score-maximized NPC and mode interaction checks."""
import copy, gzip, json, os, unittest
from pathlib import Path
from unittest.mock import patch

from controller import Bot

KIT=Path(os.environ.get("MECH_KIT","/tmp/mech-kit/mechfight-kit"))

class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with gzip.open(KIT/"check"/"stream.jsonl.gz","rt") as f:
            cls.hello=json.loads(next(f))
            cls.obs=json.loads(next(f))
        cls.hello["map"]["dir"]=str(KIT/"arena")
    def sample(self):
        return Bot(copy.deepcopy(self.hello)),copy.deepcopy(self.obs)
    def npc(self,obs,dist):
        p=obs["self"]["pos"]
        return {"id":105,"kind":"npc","pos":[p[0]+dist,p[1],p[2]],
                "vel":[0,0,0],"aim":[3.14159,0],
                "hp":350,"max_hp":350}
    def test_npc_attack_interrupts_critical_heal(self):
        bot,obs=self.sample()
        obs["self"]["hp"]=750
        obs["mechs"]=[self.npc(obs,35)]
        bot.arena.shot=lambda *_:True
        bot.arena.walk=lambda *_:True
        act=bot.act(obs)
        self.assertEqual(bot.mode,"EVADE")
        self.assertFalse(bot.recovering)
        self.assertFalse(any(act.get("fire",[False,False])))
    def test_npc_at_40m_targeted_instead_of_idle(self):
        bot,obs=self.sample()
        obs["self"]["hp"]=1300
        obs["mechs"]=[self.npc(obs,44)]
        bot.arena.shot=lambda *_:True
        bot.arena.walk=lambda *_:True
        act=bot.act(obs)
        self.assertEqual(bot.mode,"FIGHT")
        # Must be aiming at the drone rather than walking blindly.
        self.assertLess(abs(abs(act["aim"][0])-0),.5)
    def test_npc_behind_cover_allows_healing(self):
        bot,obs=self.sample()
        obs["self"]["hp"]=670
        obs["mechs"]=[self.npc(obs,40)]
        bot.arena.shot=lambda *_:False
        act=bot.act(obs)
        self.assertEqual(bot.mode,"HEAL")
        self.assertTrue(bot.recovering)
        self.assertFalse(any(act["fire"]))
    def test_npc_event_memory_extends_chase_risk(self):
        bot,obs=self.sample()
        obs["self"]["hp"]=700
        obs["mechs"]=[self.npc(obs,78)]
        obs["events"]=[{"type":"damaged","amount":25,"by":105,
                        "weapon":"npc","bearing":0,"rear":False}]
        bot.arena.shot=lambda *_:True
        bot.arena.walk=lambda *_:True
        bot.act(obs)
        self.assertEqual(bot.mode,"EVADE")
        self.assertEqual(bot.last_npc_damage,obs["t"])
    def test_short_isolated_gun_pickoff_earns_placement(self):
        bot,obs=self.sample()
        p=obs["self"]["pos"]
        obs["t"]=130
        obs["alive"]=14
        obs["self"]["hp"]=1300
        obs["self"]["aim"]=[0,0]
        obs["self"]["weapons"][0]["cooldown"]=0
        obs["self"]["weapons"][0]["reload"]=0
        obs["self"]["weapons"][0]["ammo"]=12
        target={"id":8,"kind":"mech","pos":[p[0]+70,p[1],p[2]],
                "vel":[0,0,0],"aim":[0,0],"weapons":["gun"],
                "charging":False,"hp":100,"max_hp":1400,"cubes":0}
        obs["mechs"]=[target]
        bot.mode="TRAVEL"
        bot.arena.shot=lambda *_:True
        with patch("controller.shot_connects",return_value=True):
            action={"tick":obs["tick"],"move":[0,0],"fire":[False,False]}
            bot.combat(action,obs,
                       (p[0],p[1],p[2]+obs["self"]["stats"]["muzzle_height"]),
                       target,retreat=False,urgent=False,final=False,
                       primary_threat=None)
        self.assertTrue(action["fire"][0])
    def test_pickoff_suppressed_when_ten_points_banked(self):
        bot,obs=self.sample()
        p=obs["self"]["pos"]
        obs["t"]=340
        obs["alive"]=6
        obs["self"]["hp"]=1300
        obs["self"]["aim"]=[0,0]
        obs["self"]["weapons"][0]["cooldown"]=0
        obs["self"]["weapons"][0]["reload"]=0
        obs["self"]["weapons"][0]["ammo"]=12
        target={"id":8,"kind":"mech","pos":[p[0]+70,p[1],p[2]],
                "vel":[0,0,0],"aim":[0,0],"weapons":["gun"],
                "charging":False,"hp":100,"max_hp":1400,"cubes":0}
        obs["mechs"]=[target]
        bot.mode="TRAVEL"
        bot.arena.shot=lambda *_:True
        with patch("controller.shot_connects",return_value=True):
            action={"tick":obs["tick"],"move":[0,0],"fire":[False,False]}
            bot.combat(action,obs,
                       (p[0],p[1],p[2]+obs["self"]["stats"]["muzzle_height"]),
                       target,retreat=False,urgent=False,final=False,
                       primary_threat=None)
        self.assertFalse(action["fire"][0])

    def test_safe_moderate_hp_bot_gathers_resources(self):
        bot,obs=self.sample()
        obs["self"]["hp"]=1050
        p=obs["self"]["pos"]
        crate={"id":1999,"pos":[p[0]+30,p[1],p[2]],"hp":300}
        obs["crates"]=[crate]
        obs["mechs"]=[]
        obs["drops"]=[]
        bot.arena.shot=lambda *_:True
        bot.arena.walk=lambda *_:True
        bot.objective=lambda *_:("crates",crate["id"],crate["pos"])
        bot.resource_waypoint=lambda *args:crate["pos"][:2]
        act=bot.act(obs)
        self.assertEqual(bot.mode,"FARM")
        self.assertGreater(act["move"][0],.3)

if __name__=="__main__":unittest.main()
