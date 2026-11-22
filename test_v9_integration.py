"""V9 end-to-end real-map / recorded-protocol behavioral regressions."""
import copy
import gzip
import json
import math
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from controller import Bot
KIT=Path(os.environ.get("MECH_KIT","/tmp/mech-kit/mechfight-kit"))

class Cases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with gzip.open(KIT/"check"/"stream.jsonl.gz","rt") as f:
            cls.hello=json.loads(next(f))
            cls.base=json.loads(next(f))
        cls.hello["map"]["dir"]=str(KIT/"arena")

    def prepare(self,hp=500,enemy_distance=125,charging=False):
        bot=Bot(copy.deepcopy(self.hello))
        obs=copy.deepcopy(self.base)
        p=obs["self"]["pos"]
        obs["self"]["hp"]=hp
        obs["self"]["vel"]=[0,0,0]
        obs["self"]["grounded"]=True
        obs["self"]["in_zone"]=True
        obs["events"]=[]
        obs["mechs"]=[{"kind":"mech","id":8,
                       "pos":[p[0]+enemy_distance,p[1],p[2]],
                       "vel":[0,0,0],"aim":[math.pi,0],
                       "weapons":["gun","laser"],"charging":charging,
                       "hp":1400,"max_hp":1400,"cubes":0}]
        bot.arena.shot=lambda *args:True
        bot.arena.walk=lambda *args:True
        bot.cover_point=lambda *args:None
        refuge=(p[0],p[1]+18)
        bot.foliage.refuge=lambda *args:(100.,refuge,.95)
        return bot,obs,refuge

    def test_foliage_retreat_not_ordinary_enemy_orbit(self):
        bot,obs,refuge=self.prepare()
        with patch("controller.choose_movement",
                   side_effect=lambda arena,me,z,move,*a,**k:(move,False)):
            action=bot.act(obs)
        self.assertTrue(bot.foliage_active)
        self.assertAlmostEqual(bot.foliage_goal[1],refuge[1])
        self.assertGreater(action["move"][1],.2)
        self.assertEqual(action["fire"],[False,False])

    def test_foliage_persists_after_enemy_disappears(self):
        bot,obs,refuge=self.prepare()
        with patch("controller.choose_movement",
                   side_effect=lambda arena,me,z,move,*a,**k:(move,False)):
            bot.act(obs)
            later=copy.deepcopy(obs)
            later["t"]+=.1
            later["tick"]+=2
            later["mechs"]=[]
            later["self"]["pos"]=[*refuge,obs["self"]["pos"][2]]
            later["events"]=[]
            act=bot.act(later)
        self.assertTrue(bot.foliage_active)
        self.assertEqual(bot.mode,"HEAL")
        self.assertEqual(act["fire"],[False,False])
        self.assertFalse(act.get("boost",False))

    def test_tree_is_not_stealth_when_enemy_uses_proximity_sensor(self):
        bot,obs,refuge=self.prepare()
        bot.act(obs)
        later=copy.deepcopy(obs)
        later["tick"]+=2
        later["t"]+=.1
        later["mechs"][0]["pos"]=[
            later["self"]["pos"][0]+28,
            later["self"]["pos"][1],later["self"]["pos"][2]]
        bot.act(later)
        self.assertFalse(bot.foliage_active)

    def test_charging_laser_blocks_tree_hide(self):
        bot,obs,_=self.prepare(charging=True)
        bot.act(obs)
        self.assertFalse(bot.foliage_active)

    def test_final_center_contester_can_be_shot(self):
        bot,obs,_=self.prepare(hp=1350,enemy_distance=5)
        p=obs["self"]["pos"]
        obs["t"]=400.
        obs["alive"]=8
        obs["zone"]["next_center"]=p[:2]
        obs["zone"]["next_radius"]=0
        obs["zone"]["radius"]=25
        obs["zone"]["dps"]=260
        obs["self"]["aim"]=[0,0]
        obs["self"]["weapons"][0]["cooldown"]=0
        obs["self"]["weapons"][0]["reload"]=0
        obs["self"]["weapons"][0]["ammo"]=12
        obs["mechs"][0]["weapons"]=["gun"]
        obs["mechs"][0]["charging"]=False
        act={"tick":obs["tick"],"move":[0,0],"fire":[False,False]}
        with patch("controller.shot_connects",return_value=True):
            bot.combat(act,obs,
                (p[0],p[1],p[2]+obs["self"]["stats"]["muzzle_height"]),
                obs["mechs"][0],retreat=False,urgent=False,
                final=True,primary_threat=None)
        self.assertTrue(act["fire"][0])

    def test_final_center_contester_outprioritizes_far_weak_target(self):
        bot,obs,_=self.prepare(hp=1400,enemy_distance=5)
        p=obs["self"]["pos"]
        obs["t"]=400
        obs["zone"]["next_center"]=p[:2]
        obs["zone"]["center"]=p[:2]
        obs["zone"]["next_radius"]=0
        obs["zone"]["radius"]=25
        obs["zone"]["dps"]=260
        obs["self"]["energy"]=30
        close=obs["mechs"][0]
        close["id"]=8
        close["pos"]=[p[0]+5,p[1],p[2]]
        close["weapons"]=["gun"]
        close["charging"]=False
        distant=dict(close,id=9,pos=[p[0]+80,p[1],p[2]],hp=35)
        obs["mechs"]=[distant,close]
        chosen=[]
        bot.final_movement=lambda act,me,threats,p,anchor,goal,roof,remain,zone,size,now,deadline:(False,goal)
        bot.combat=lambda act,obs,origin,target,*args:chosen.append(
            target["id"] if target else None)
        bot.act(obs)
        self.assertEqual(chosen,[8])

    def test_silent_laser_ambush_doesnt_fire_arm_gun(self):
        bot,obs,_=self.prepare(hp=1350,enemy_distance=170)
        p=obs["self"]["pos"]
        obs["t"]=150
        obs["alive"]=12
        obs["mechs"][0]["hp"]=300
        obs["mechs"][0]["aim"]=[0,0]
        obs["mechs"][0]["weapons"]=["gun"]
        obs["self"]["aim"]=[0,0]
        obs["self"]["weapons"][1]={"kind":"laser","cooldown":0,"charge":0,
                         "stats":copy.deepcopy(self.hello["config"]["weapons"]["laser"])}
        obs["self"]["weapons"][0]["cooldown"]=0
        act={"tick":obs["tick"],"move":[0,0],"fire":[False,False]}
        with patch("controller.shot_connects",return_value=True):
            bot.combat(act,obs,
                (p[0],p[1],p[2]+obs["self"]["stats"]["muzzle_height"]),
                obs["mechs"][0],retreat=False,urgent=False,
                final=False,primary_threat=None)
        self.assertFalse(act["fire"][0])
        self.assertTrue(act["fire"][1])

if __name__=="__main__":
    unittest.main()
