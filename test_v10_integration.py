"""V10 real-observation adversarial controller tests."""
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

class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with gzip.open(KIT/"check"/"stream.jsonl.gz","rt") as f:
            cls.hello=json.loads(next(f))
            cls.sample=json.loads(next(f))
        cls.hello["map"]["dir"]=str(KIT/"arena")

    def start(self):
        bot=Bot(copy.deepcopy(self.hello))
        obs=copy.deepcopy(self.sample)
        obs["events"]=[]
        return bot,obs

    def target(self,obs,dist=170,aim=0.,hp=350):
        p=obs["self"]["pos"]
        return {"id":7,"kind":"mech","pos":[p[0]+dist,p[1],p[2]],
                "vel":[0.,0.,0.],"aim":[aim,0.],
                "cubes":0,"hp":hp,"max_hp":1400,
                "weapons":["gun"],"charging":False}

    def give_laser(self,obs,charge=0):
        obs["self"]["weapons"][1]={
            "kind":"laser","cooldown":0.,"charge":charge,
            "stats":copy.deepcopy(self.hello["config"]["weapons"]["laser"])}
        obs["self"]["aim"]=[0.,0.]

    def test_multi_tick_ambush_stays_silent_after_enemy_turns(self):
        bot,o=self.start()
        self.give_laser(o)
        o["self"]["hp"]=1390
        o["t"]=170
        o["alive"]=12
        # Keep the observation internally consistent at t=170. A t=170
        # action should not be evaluated against the t=25 storm schedule.
        p=o["self"]["pos"]
        o["zone"].update(center=p[:2],radius=320.,
                         next_center=p[:2],next_radius=240.,
                         shrink_start=155.,shrink_end=195.,dps=35)
        target=self.target(o,170,0,320)
        o["mechs"]=[target]
        bot.arena.shot=lambda *args:True
        bot.arena.walk=lambda *args:True
        with patch("controller.shot_connects",return_value=True):
            act=bot.act(o)
            self.assertTrue(act["fire"][1],msg=f"first action={act}, mode={bot.mode}, ambush_id={bot.ambush_target_id}")
            self.assertFalse(act["fire"][0])
            self.assertEqual(bot.ambush_target_id,7)
            o2=copy.deepcopy(o)
            o2["tick"]+=2
            o2["t"]+=.1
            o2["self"]["weapons"][1]["charge"]=.20
            o2["mechs"][0]["aim"]=[math.pi,0.]
            act2=bot.act(o2)
            self.assertFalse(act2["fire"][0])
            self.assertEqual(bot.ambush_target_id,7)
            self.assertTrue(act2["fire"][1])

    def test_quiet_single_shot_resource_farming(self):
        bot,o=self.start()
        self.give_laser(o)
        o["t"]=50
        p=o["self"]["pos"]
        o["mechs"]=[]
        crate={"kind":"crate","id":1003,"pos":[p[0]+50,p[1],p[2]],"hp":300}
        o["crates"]=[crate]
        bot.arena.shot=lambda *args:True
        with patch("controller.shot_connects",return_value=True):
            act={"tick":o["tick"],"move":[0.,0.],"fire":[False,False]}
            bot.mode="FARM"
            bot.combat(act,o,(p[0],p[1],p[2]+o["self"]["stats"]["muzzle_height"]),
                       crate,retreat=False,urgent=False,final=False,
                       primary_threat=None)
        self.assertTrue(act["fire"][1])
        self.assertFalse(act["fire"][0])

    def test_incoming_bullet_interrupts_idle_healing(self):
        bot,o=self.start()
        o["self"]["hp"]=650
        o["mechs"]=[]
        p=o["self"]["pos"]
        o["projectiles"]=[{
            "id":555,"kind":"gun",
            "pos":[p[0]+40,p[1],p[2]+4],
            "vel":[-200.,0.,0.]}
        ]
        bot.arena.shot=lambda *args:True
        act=bot.act(o)
        self.assertEqual(bot.mode,"EVADE")
        self.assertFalse(bot.recovering)

    def test_distant_bullet_does_not_interrupt_heal(self):
        bot,o=self.start()
        o["self"]["hp"]=650
        o["mechs"]=[]
        p=o["self"]["pos"]
        o["projectiles"]=[{
            "id":555,"kind":"gun",
            "pos":[p[0]+40,p[1]+40,p[2]+4],
            "vel":[-200.,0.,0.]}
        ]
        bot.arena.shot=lambda *args:True
        bot.act(o)
        self.assertEqual(bot.mode,"HEAL")
        self.assertTrue(bot.recovering)

    def test_laser_ambush_only_on_true_one_shot(self):
        bot,o=self.start()
        self.give_laser(o)
        o["self"]["hp"]=1390
        o["t"]=170
        o["alive"]=12
        t=self.target(o,170,0,900)
        o["mechs"]=[t]
        bot.arena.shot=lambda *args:True
        with patch("controller.shot_connects",return_value=True):
            act=bot.act(o)
        self.assertNotEqual(bot.ambush_target_id,7)

if __name__=="__main__":unittest.main()
