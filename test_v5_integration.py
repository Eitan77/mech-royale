"""Adversarial smoke tests using REAL starter-kit obs and map, not a simulated score."""
import copy
import gzip
import json
import math
from pathlib import Path
import os
import unittest

from controller import Bot

KIT = Path(os.environ.get("MECH_KIT", "/tmp/mech-kit/mechfight-kit"))

class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with gzip.open(KIT/"check"/"stream.jsonl.gz","rt") as stream:
            cls.hello=json.loads(next(stream))
            cls.observations=[json.loads(line) for line in stream if line.strip()]
        cls.hello["map"]["dir"]=str(KIT/"arena")

    def action(self, obs):
        bot=Bot(copy.deepcopy(self.hello))
        obs=copy.deepcopy(obs)
        action=bot.act(obs)
        self.assertEqual(action["tick"],obs["tick"])
        self.assertEqual(len(action.get("move",[0,0])),2)
        self.assertLessEqual(math.hypot(*action.get("move",[0,0])),1.0001)
        self.assertEqual(len(action.get("fire",[False,False])),2)
        return action,bot

    def test_low_hp_alone_never_crashes(self):
        obs=copy.deepcopy(self.observations[0])
        obs["self"]["hp"]=400
        obs["mechs"]=[]
        obs["events"]=[]
        action,bot=self.action(obs)
        self.assertEqual(bot.mode,"HEAL")
        self.assertEqual(action["fire"],[False,False])

    def test_charging_laser_observation_does_not_crash(self):
        obs=next(copy.deepcopy(o) for o in self.observations
                 if o.get("type")=="obs" and any(m["kind"]=="mech" for m in o["mechs"]))
        enemy=next(m for m in obs["mechs"] if m["kind"]=="mech")
        enemy["weapons"]=["gun","laser"]
        enemy["charging"]=True
        self.action(obs)

    def test_evade_can_short_an_active_laser(self):
        obs=copy.deepcopy(self.observations[0])
        me=obs["self"]
        p=me["pos"]
        me["hp"]=me["max_hp"]*.95
        me["energy"]=me["max_energy"]
        me["aim"]=[0,0]
        me["weapons"][1]={
            "kind":"lightning","cooldown":0,
            "stats":copy.deepcopy(self.hello["config"]["weapons"]["lightning"])
        }
        obs["events"]=[]
        obs["crates"]=[]
        obs["mechs"]=[{
            "id":7,"kind":"mech","pos":[p[0]+20,p[1],p[2]],
            "vel":[0,0,0],"aim":[math.pi,0],
            "hp":1400,"max_hp":1400,"cubes":0,
            "weapons":["gun","laser"],"charging":True
        }]
        bot=Bot(copy.deepcopy(self.hello))
        # Force unobstructed geometry to exercise action prioritization,
        # not the particular terrain at this sample position.
        bot.arena.shot=lambda a,b: True
        action=bot.act(obs)
        self.assertEqual(bot.mode,"EVADE")
        self.assertFalse(bot.recovering)
        self.assertTrue(action["fire"][1])

    def test_dense_squad_observation_does_not_crash(self):
        obs=copy.deepcopy(self.observations[0])
        p=obs["self"]["pos"]
        obs["events"]=[]
        obs["mechs"]=[{
            "id":j+1,"kind":"mech",
            "pos":[p[0]+(40+7*j)*math.cos(j*math.tau/15),
                   p[1]+(40+7*j)*math.sin(j*math.tau/15),p[2]],
            "vel":[0,0,0],"aim":[0,0],"hp":1200,"max_hp":1400,
            "cubes":0,"weapons":["gun","laser"],"charging":j%3==0
        } for j in range(15)]
        self.action(obs)

    def test_farm_mode_keeps_resource_route_and_target(self):
        from unittest.mock import patch
        obs=copy.deepcopy(self.observations[0])
        p=obs["self"]["pos"]
        obs["events"]=[]
        obs["drops"]=[]
        crate={"id":1201,"pos":[p[0],p[1]+40,p[2]],"hp":300}
        obs["crates"]=[crate]
        obs["mechs"]=[{
            "id":7,"kind":"mech","pos":[p[0]+80,p[1],p[2]],
            "vel":[0,0,0],"aim":[0,0],"hp":1400,"max_hp":1400,
            "cubes":0,"weapons":["gun"],"charging":False
        }]
        bot=Bot(copy.deepcopy(self.hello))
        bot.danger_cache={"exposed":0,"near":0,"lasers":0,
                          "charging":0,"closest":80}
        bot.danger_update=obs["t"]
        bot.objective=lambda *args: ("crates",crate["id"],crate["pos"])
        bot.resource_waypoint=lambda *args: crate["pos"][:2]
        bot.arena.walk=lambda *args: True
        bot.arena.shot=lambda *args: True
        with patch("controller.choose_movement",side_effect=lambda arena,me,zone,move,*a,**kw:(move,False)):
            act=bot.act(obs)
        self.assertEqual(bot.mode,"FARM")
        # The skirmish code previously reversed this direction to orbit an
        # enemy 80m east, abandoning the crate 40m north.
        self.assertGreater(act["move"][1],0.3)
        self.assertLess(abs(act["move"][0]),.25)

    def test_collecting_pickup_never_aggresses_occluded_enemy(self):
        from unittest.mock import patch
        obs=copy.deepcopy(self.observations[0])
        p=obs["self"]["pos"]
        obs["events"]=[]
        obs["drops"]=[]
        obs["mechs"]=[{
            "id":7,"kind":"mech","pos":[p[0]+80,p[1],p[2]],
            "vel":[0,0,0],"aim":[0,0],"hp":1400,"max_hp":1400,
            "cubes":0,"weapons":["gun"],"charging":False
        }]
        pickup={"id":8010,"kind":"lightning","pos":[p[0],p[1]+25,p[2]]}
        obs["pickups"]=[pickup]
        bot=Bot(copy.deepcopy(self.hello))
        bot.danger_cache={"exposed":0,"near":0,"lasers":0,
                          "charging":0,"closest":80}
        bot.danger_update=obs["t"]
        bot.objective=lambda *args: ("pickups",pickup["id"],pickup["pos"])
        bot.arena.walk=lambda *args: True
        bot.arena.shot=lambda *args: True
        with patch("controller.choose_movement",side_effect=lambda arena,me,zone,move,*a,**kw:(move,False)):
            act=bot.act(obs)
        self.assertEqual(bot.mode,"FARM")
        self.assertGreater(act["move"][1],.3)
        self.assertEqual(act["fire"],[False,False])

    def test_heal_does_not_fire_even_with_visible_enemy(self):
        obs=copy.deepcopy(self.observations[0])
        p=obs["self"]["pos"]
        obs["self"]["hp"]=obs["self"]["max_hp"]*.5
        obs["events"]=[]
        obs["mechs"]=[{
            "id":7,"kind":"mech","pos":[p[0]+70,p[1],p[2]],
            "vel":[0,0,0],"aim":[0,0],"hp":1400,"max_hp":1400,
            "cubes":0,"weapons":["gun"],"charging":False
        }]
        bot=Bot(copy.deepcopy(self.hello))
        bot.danger_cache={"exposed":0,"near":1,"lasers":0,
                          "charging":0,"closest":70}
        bot.danger_update=obs["t"]
        act=bot.act(obs)
        self.assertTrue(bot.recovering)
        self.assertFalse(any(act["fire"]))

    def test_final_center_observation_does_not_crash(self):
        obs=copy.deepcopy(self.observations[0])
        obs["t"]=397
        obs["self"]["hp"]=1000
        obs["zone"]["next_radius"]=0
        obs["zone"]["radius"]=25
        obs["zone"]["next_center"]=obs["self"]["pos"][:2]
        obs["zone"]["shrink_start"]=390
        obs["zone"]["shrink_end"]=415
        self.action(obs)

    def test_normal_opening_does_not_crash(self):
        self.action(self.observations[0])

if __name__=="__main__": unittest.main()
