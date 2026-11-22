"""V10 surgical policy regressions."""
import unittest,math
from tactical_v10 import *

class Tests(unittest.TestCase):
    def setUp(self):
        self.me={"pos":[0.,0.,0.],"vel":[0.,0.,0.],"grounded":True,
                 "hp":1400,"max_hp":1400,"cubes":0,
                 "weapons":[{"kind":"gun"},{"kind":"laser",
                             "stats":{"damage":315}}]}
        self.zone={"center":[0,0],"radius":560,"dps":35}
    def test_bullet_aimed_at_healing_mech(self):
        bullet={"kind":"gun","pos":[40.,0.,4.],
                "vel":[-200.,0.,0.]}
        self.assertTrue(imminent_projectile(self.me,[bullet],self.zone))
    def test_bullet_flying_away_is_not_threat(self):
        bullet={"kind":"gun","pos":[40.,0.,4.],
                "vel":[200.,0.,0.]}
        self.assertFalse(imminent_projectile(self.me,[bullet],self.zone))
    def test_projectile_passing_far_side_is_not_threat(self):
        bullet={"kind":"gun","pos":[40.,28.,4.],
                "vel":[-200.,0.,0.]}
        self.assertFalse(imminent_projectile(self.me,[bullet],self.zone))
    def test_projectile_overhead_is_not_threat(self):
        bullet={"kind":"gun","pos":[40.,0.,40.],
                "vel":[-200.,0.,0.]}
        self.assertFalse(imminent_projectile(self.me,[bullet],self.zone))
    def test_late_storm_override_regular_bullet(self):
        zone=dict(self.zone,radius=4.,dps=260)
        me=dict(self.me,pos=[2.,0.,0.])
        bullet={"kind":"gun","pos":[40.,0.,4.],
                "vel":[-200.,0.,0.]}
        self.assertFalse(imminent_projectile(me,[bullet],zone))
    def test_realistic_shell_intercept(self):
        shell={"kind":"mortar","pos":[24.,0.,14.],
               "vel":[-50.,0.,-4.]}
        self.assertTrue(imminent_projectile(self.me,[shell],self.zone))
    def test_sniper_picks_weak_only(self):
        e=[{"id":1,"pos":[100,0],"hp":100},
           {"id":2,"pos":[150,0],"hp":30}]
        f=lambda me,e,es,zone,now,alive: e["id"]==2
        self.assertEqual(sniper_choice(self.me,e,self.zone,140,12,f)["id"],2)
    def test_laser_resource_one_shot_crate(self):
        self.assertTrue(resource_laser_silence(
            self.me,{"kind":"crate","hp":300},999,False,False,40))
    def test_laser_resource_one_shot_drone_requires_cubes(self):
        drone={"kind":"npc","hp":350}
        self.assertFalse(resource_laser_silence(
            self.me,drone,999,False,False,40))
        self.me["cubes"]=3
        self.assertTrue(resource_laser_silence(
            self.me,drone,999,False,False,40))
    def test_gun_can_resume_while_laser_on_cooldown(self):
        laser=self.me["weapons"][1]
        laser["cooldown"]=1.5
        self.assertFalse(resource_laser_silence(
            self.me,{"kind":"crate","hp":300},999,False,False,40))
        laser["charge"]=.5
        self.assertTrue(resource_laser_silence(
            self.me,{"kind":"crate","hp":300},999,False,False,40))

    def test_laser_resource_silence_no_enemy_near(self):
        self.assertFalse(resource_laser_silence(
            self.me,{"kind":"crate","hp":300},70,False,False,40))
    def test_laser_ambush_locked_midcharge(self):
        self.assertTrue(safety_silence("FIGHT",.5,11,11,{"id":11}))
        self.assertFalse(safety_silence("FIGHT",.5,11,11,{"id":12}))
    def test_storm_edge_trade(self):
        zone=dict(self.zone,radius=4.,dps=260)
        me=dict(self.me,pos=[2,0,0])
        self.assertTrue(late_storm_armor_trade(me,zone))
if __name__=="__main__":unittest.main()
