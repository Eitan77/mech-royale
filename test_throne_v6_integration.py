"""V6 experimental integration checks; tests use real hello/map and sample obs."""
import copy
import gzip
import json
import os
from pathlib import Path
import unittest
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

    def scenario(self,distance=10,healing=False):
        bot=Bot(copy.deepcopy(self.hello))
        obs=copy.deepcopy(self.obs)
        p=obs["self"]["pos"]
        obs["t"]=400
        obs["zone"]["center"]=p[:2]
        obs["zone"]["next_center"]=p[:2]
        obs["zone"]["radius"]=15
        obs["zone"]["next_radius"]=0
        obs["zone"]["shrink_start"]=390
        obs["zone"]["shrink_end"]=415
        obs["self"]["weapons"][0]["cooldown"]=0
        obs["self"]["weapons"][0]["ammo"]=12
        obs["self"]["weapons"][0]["reload"]=0
        enemy={"id":9,"kind":"mech","pos":[p[0]+distance,p[1],p[2]],
               "vel":[0,0,0],"aim":[0,0],"weapons":["gun"],"cubes":0,
               "hp":1400,"max_hp":1400,"charging":False}
        obs["mechs"]=[enemy]
        origin=(p[0],p[1],p[2]+obs["self"]["stats"]["muzzle_height"])
        bot.arena.shot=lambda *args: True
        bot.recovering=healing
        act={"tick":obs["tick"],"move":[0,0],"fire":[False,False]}
        with patch("controller.shot_connects",return_value=True):
            bot.combat(act,obs,origin,enemy,retreat=False,urgent=False,
                       final=True,primary_threat=enemy)
        return act

    def test_final_contester_gets_gunfire(self):
        self.assertTrue(self.scenario(10)["fire"][0])
    def test_far_off_center_enemy_not_provoked(self):
        self.assertFalse(self.scenario(35)["fire"][0])
    def test_regeneration_suppresses_final_fire(self):
        self.assertFalse(self.scenario(10,healing=True)["fire"][0])

if __name__=="__main__":unittest.main()
