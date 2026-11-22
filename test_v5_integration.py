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
