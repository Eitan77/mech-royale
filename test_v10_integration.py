"""V10 real-observation adversarial controller tests."""
import copy
import gzip
import json
import math
import os
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from controller import Bot
from pilot import choose_movement

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

    def test_lightning_pickup_keeps_laser_and_replaces_gun(self):
        bot, obs = self.start()
        self.give_laser(obs)
        obs["mechs"] = []
        obs["pickups"] = [{"id": 8001, "kind": "lightning", "pos": obs["self"]["pos"]}]
        act = bot.act(obs)
        self.assertEqual((act["take"], act["drop"]), (8001, 0))

    def test_dual_loadout_uses_arc_against_close_lightning(self):
        bot, obs = self.start()
        self.give_laser(obs)
        me = obs["self"]
        me["weapons"][0] = {"kind": "lightning", "cooldown": 0.,
                            "stats": self.hello["config"]["weapons"]["lightning"]}
        me["energy"] = 100
        target = self.target(obs, dist=25)
        target["weapons"] = ["gun", "lightning"]
        obs["mechs"] = [target]
        bot.arena.shot = lambda *args: True
        muzzle = (*me["pos"][:2], me["pos"][2] + me["stats"]["muzzle_height"])
        act = {"fire": [False, False]}
        with patch.object(bot, "lightning_connects", return_value=True):
            bot.combat(act, obs, muzzle, target, False, False, False, target)
        self.assertEqual(act["fire"], [True, False])

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

    def test_three_cube_drone_laser_requires_exact_full_charge(self):
        bot,o=self.start()
        self.give_laser(o,charge=.70)
        o["t"]=60
        o["self"]["cubes"]=3
        bot.laser_target=101
        p=o["self"]["pos"]
        drone={"kind":"npc","id":101,
               "pos":[p[0]+50,p[1],p[2]],
               "vel":[0.,0.,0.],"hp":350.,"max_hp":350.}
        o["mechs"]=[drone]
        bot.arena.shot=lambda *args:True
        with patch("controller.shot_connects",return_value=True):
            act={"tick":o["tick"],"move":[0,0],"fire":[False,False]}
            bot.combat(act,o,(p[0],p[1],p[2]+o["self"]["stats"]["muzzle_height"]),
                       drone,retreat=False,urgent=False,final=False,
                       primary_threat=None)
            self.assertTrue(act["fire"][1],
                            "0.70s laser insufficient for 350HP drone at 3 cubes")
            self.assertFalse(act["fire"][0],
                             "Gun must not announce full-charge laser farming")
            o["self"]["weapons"][1]["charge"]=.75
            act2={"tick":o["tick"],"move":[0,0],"fire":[False,False]}
            bot.combat(act2,o,(p[0],p[1],p[2]+o["self"]["stats"]["muzzle_height"]),
                       drone,retreat=False,urgent=False,final=False,
                       primary_threat=None)
            self.assertFalse(act2["fire"][1],
                             "At 0.75s the laser must release its full-damage beam")

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

    def test_active_own_laser_charge_prevents_false_silent_hide(self):
        bot,o=self.start()
        self.give_laser(o,charge=.35)
        o["self"]["hp"]=650
        p=o["self"]["pos"]
        o["zone"].update(center=p[:2],radius=560.,
                         next_center=p[:2],next_radius=380.,
                         shrink_start=60.,shrink_end=110.,dps=20.)
        o["t"]=25
        o["mechs"]=[self.target(o,125,math.pi,1200)]
        bot.arena.shot=lambda *args:True
        bot.arena.walk=lambda *args:True
        bot.cover_point=lambda *args:None
        bot.foliage.refuge=lambda *args:(100.,(p[0],p[1]+18),.9)
        bot.danger_cache={"exposed":0,"near":0,"lasers":0,
                          "charging":0,"closest":125}
        bot.danger_update=o["t"]
        bot.act(o)
        self.assertFalse(bot.foliage_active,
                         "Entering ghost mode would release the active laser")

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

    def test_skirmish_closes_only_to_short_an_isolated_laser(self):
        for enemy_weapon, toward in (("laser", 1), ("mortar", -1)):
            for side in (-1, 1):
                with self.subTest(enemy_weapon=enemy_weapon, side=side):
                    bot, obs = self.start()
                    me = obs["self"]
                    p = me["pos"]
                    me.update(hp=me["max_hp"], energy=100., grounded=True, in_zone=True)
                    me["weapons"][1] = {
                        "kind": "lightning", "cooldown": 0.,
                        "stats": self.hello["config"]["weapons"]["lightning"],
                    }
                    enemy = self.target(obs, 35)
                    enemy["weapons"].append(enemy_weapon)
                    obs.update(t=50, alive=12, mechs=[enemy],
                               projectiles=[], drops=[])
                    obs["zone"].update(center=p[:2], radius=320.,
                                       next_center=p[:2], next_radius=240.,
                                       shrink_end=110.)
                    bot.evade_side, bot.evade_until = side, 55
                    bot.arena.shot = lambda *args: True
                    bot.arena.walk = lambda *args: True
                    with patch.object(bot, "travel_waypoint", side_effect=lambda _, goal, *_args: goal), patch(
                        "controller.choose_movement", side_effect=lambda _arena, _me, _zone, move, *_args, **_kwargs: (move, False)
                    ):
                        act = bot.act(obs)
                    self.assertGreater(toward * act["move"][0], .25)

    def test_supply_capture_commits_early_only_when_survivable(self):
        bot, obs = self.start()
        me = obs["self"]
        me.update(hp=me["max_hp"], grounded=True)
        drop = {"id": 20000, "pos": me["pos"], "holder": me["id"],
                "radius": 8., "lands_in": 0., "capture_s": 4., "progress": .5}
        obs["drops"] = [drop]
        enemy = self.target(obs, 130)
        bot.arena.shot = lambda *args: True
        self.assertIs(bot.finish_capture(obs, [enemy]), drop)
        me["hp"] = 300
        self.assertIsNone(bot.finish_capture(obs, [enemy]))
        bot.arena.shot = lambda *args: False
        self.assertIs(bot.finish_capture(obs, [enemy]), drop)
        enemy["pos"][0] = me["pos"][0] + 60
        self.assertIsNone(bot.finish_capture(obs, [enemy]))

    def test_combat_aim_accounts_for_shooter_motion_before_firing(self):
        for kind, delay in (("gun", .10), ("laser", .05)):
            with self.subTest(kind=kind):
                bot, obs = self.start()
                me = obs["self"]
                me["vel"] = [0., 15., 0.]
                me["weapons"][0].update(ammo=12, reload=0., cooldown=.10)
                me["weapons"][1] = None
                if kind == "laser":
                    self.give_laser(obs, charge=.75)
                enemy = self.target(obs, 100, hp=900)
                obs["mechs"] = [enemy]
                bot.laser_target = enemy["id"]
                bot.arena.shot = lambda *args: True
                x, y, z = me["pos"]
                origin = (x, y, z + me["stats"]["muzzle_height"])
                action = {"fire": [False, False]}
                bot.combat(action, obs, origin, enemy, False, False, False, enemy)
                self.assertAlmostEqual(action["aim"][0], math.atan2(-15 * delay, 100))

    def test_laser_charge_movement_rollout_uses_half_walk_speed(self):
        bot, obs = self.start()
        me = obs["self"]
        p = me["pos"]
        speed = me["stats"]["walk_speed"]
        scale = self.hello["config"]["mech"]["charge_move_mult"]
        me.update(grounded=True, energy=0., vel=[speed * scale, 0., 0.])
        obs["zone"].update(center=p[:2], radius=320.)
        endpoints = []

        def record_walk(_start, end, _size):
            endpoints.append(end)
            return True

        bot.arena.walk = record_walk
        choose_movement(bot.arena, me, obs["zone"], [1., 0.], [], [], 1.,
                        True, time.perf_counter() + .05, speed_scale=scale)
        self.assertAlmostEqual(endpoints[0][0] - p[0], speed * scale * .6)

if __name__=="__main__":unittest.main()
