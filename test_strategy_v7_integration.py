"""V7 end-to-end adversarial tests on real hello / arena and synthetic situations."""
import copy,gzip,json,math,os,unittest
from pathlib import Path
from unittest.mock import patch

from controller import Bot
from strategy_v7 import should_silence
KIT=Path(os.environ.get("MECH_KIT","/tmp/mech-kit/mechfight-kit"))

class Integration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with gzip.open(KIT/"check"/"stream.jsonl.gz","rt") as f:
            cls.hello=json.loads(next(f))
            cls.sample=json.loads(next(f))
        cls.hello["map"]["dir"]=str(KIT/"arena")

    def clone(self):
        return Bot(copy.deepcopy(self.hello)),copy.deepcopy(self.sample)

    def enemy(self,obs,d,aim_toward=False,laser=False,charging=False,ident=9):
        p=obs["self"]["pos"]
        return {"id":ident,"kind":"mech","pos":[p[0]+d,p[1],p[2]],
                "vel":[0,0,0],"aim":[math.pi if aim_toward else 0,0],
                "hp":1400,"max_hp":1400,"cubes":0,
                "weapons":["gun","laser"] if laser else ["gun"],
                "charging":charging}

    def test_safe_passive_enemy_does_not_cancel_resource_farming(self):
        bot,obs=self.clone()
        p=obs["self"]["pos"]
        crate={"id":1001,"pos":[p[0],p[1]+25,p[2]],"hp":300}
        obs["crates"]=[crate];obs["drops"]=[]
        obs["mechs"]=[self.enemy(obs,140,aim_toward=False)]
        bot.arena.shot=lambda *args:True
        bot.arena.walk=lambda *args:True
        bot.objective=lambda *args:("crates",1001,crate["pos"])
        bot.resource_waypoint=lambda *args:crate["pos"][:2]
        with patch("controller.choose_movement",side_effect=lambda arena,me,zone,move,*a,**kw:(move,False)):
            act=bot.act(obs)
        self.assertEqual(bot.mode,"FARM")
        self.assertGreater(act["move"][1],.4)
        self.assertLess(abs(act["move"][0]),.3)

    def test_active_laser_preempts_loot(self):
        bot,obs=self.clone()
        obs["mechs"]=[self.enemy(obs,150,aim_toward=True,laser=True,charging=True)]
        bot.arena.shot=lambda *args:True
        act=bot.act(obs)
        self.assertEqual(bot.mode,"EVADE")
        self.assertFalse(bot.recovering)

    def test_stationary_healing_does_not_step_or_fire(self):
        bot,obs=self.clone()
        p=obs["self"]["pos"]
        obs["self"]["hp"]=700
        obs["mechs"]=[]
        obs["zone"]["next_center"]=p[:2]
        obs["zone"]["next_radius"]=380
        obs["zone"]["shrink_end"]=110
        act=bot.act(obs)
        self.assertEqual(bot.mode,"HEAL")
        self.assertFalse(any(act["fire"]))
        self.assertFalse(act.get("boost",False))
        self.assertFalse(act.get("jump",False))
        self.assertLess(math.hypot(*act["move"]),.01)

    def test_healing_does_not_crawl_into_shrinking_storm(self):
        bot,obs=self.clone()
        p=obs["self"]["pos"]
        obs["t"]=55
        obs["self"]["hp"]=800
        obs["zone"]["next_center"]=[p[0]+200,p[1]]
        obs["zone"]["next_radius"]=45
        obs["zone"]["shrink_start"]=56
        obs["zone"]["shrink_end"]=65
        obs["mechs"]=[]
        act=bot.act(obs)
        self.assertEqual(bot.mode,"ZONE")
        self.assertGreater(math.hypot(*act["move"]),.5)

    def test_low_hp_bot_goes_to_safe_full_heal_drop(self):
        bot,obs=self.clone()
        p=obs["self"]["pos"]
        obs["t"]=75
        obs["self"]["hp"]=500
        obs["mechs"]=[]
        obs["zone"]["next_center"]=p[:2]
        obs["zone"]["next_radius"]=380
        obs["drops"]=[{"id":990,"pos":[p[0]+20,p[1],p[2]],
                        "holder":None,"lands_in":1,
                        "radius":8,"capture_s":4,"progress":0}]
        bot.arena.walk=lambda *args:True
        act=bot.act(obs)
        self.assertEqual(bot.mode,"FARM")
        self.assertFalse(bot.recovering)
        self.assertGreater(act["move"][0],.4)

    def test_contested_full_heal_drop_is_ignored(self):
        bot,obs=self.clone()
        p=obs["self"]["pos"]
        obs["t"]=75
        obs["self"]["hp"]=500
        obs["mechs"]=[self.enemy(obs,40)]
        obs["zone"]["next_center"]=p[:2]
        obs["zone"]["next_radius"]=380
        obs["drops"]=[{"id":990,"pos":[p[0]+20,p[1],p[2]],
                        "holder":None,"lands_in":1,
                        "radius":8,"capture_s":4,"progress":0}]
        bot.arena.shot=lambda *args:False
        bot.act(obs)
        self.assertNotEqual(bot.mode,"FARM")

    def test_unthreatening_mortar_holder_not_disarmed(self):
        bot,obs=self.clone()
        obs["self"]["weapons"][1]={
            "kind":"mortar","cooldown":0,
            "stats":copy.deepcopy(self.hello["config"]["weapons"]["mortar"])}
        obs["mechs"]=[self.enemy(obs,170,aim_toward=False,laser=True)]
        bot.arena.shot=lambda *args:True
        act=bot.act(obs)
        self.assertNotIn("drop",act)

    def test_imminent_laser_charge_can_drop_mortar(self):
        bot,obs=self.clone()
        obs["self"]["weapons"][1]={
            "kind":"mortar","cooldown":0,
            "stats":copy.deepcopy(self.hello["config"]["weapons"]["mortar"])}
        obs["mechs"]=[self.enemy(obs,160,aim_toward=True,laser=True,charging=True)]
        bot.arena.shot=lambda *args:True
        act=bot.act(obs)
        self.assertEqual(act.get("drop"),1)

if __name__=="__main__":unittest.main()
