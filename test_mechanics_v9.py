"""V9 mechanics checks: all policies are conditional, not claimed match wins."""
import math,unittest
from mechanics_v9 import *
class TestMechanics(unittest.TestCase):
    def setUp(self):
        self.me={"id":0,"pos":[0.,0.,0.],"hp":1380.,"max_hp":1400.,
                 "energy":100.,"in_zone":True,"grounded":True,
                 "cubes":0,"weapons":[{"kind":"gun"},
                 {"kind":"laser","cooldown":0.,
                  "stats":{"damage":315.}}]}
        self.zone={"center":[0.,0.],"radius":380.,
                   "next_center":[0.,0.],"next_radius":240.,
                   "dps":35}
        self.enemy={"id":1,"kind":"mech","pos":[170.,0.,0.],
                    "aim":[0.,0.],"hp":350.,"max_hp":1400.,
                    "weapons":["gun"],"cubes":0,"charging":False}
    def test_one_shot_rear_ambush(self):
        self.assertTrue(one_shot_laser_ambush(
            self.me,self.enemy,[self.enemy],self.zone,170,12))
    def test_ambush_rejects_high_hp(self):
        e=dict(self.enemy,hp=900.)
        self.assertFalse(one_shot_laser_ambush(self.me,e,[e],self.zone,170,12))
    def test_ambush_rejects_facing_opponent(self):
        e=dict(self.enemy,aim=[math.pi,0.])
        self.assertFalse(one_shot_laser_ambush(self.me,e,[e],self.zone,170,12))
    def test_ambush_rejects_squad_near_shooter(self):
        e=dict(self.enemy)
        other=dict(self.enemy,id=2,pos=[175.,30.,0.])
        self.assertFalse(one_shot_laser_ambush(
            self.me,e,[e,other],self.zone,170,12))
    def test_ambush_doesnt_risk_bank_of_ten(self):
        self.assertFalse(one_shot_laser_ambush(
            self.me,self.enemy,[self.enemy],self.zone,170,6))
    def test_three_cube_laser_oneshot_drone(self):
        me=dict(self.me,cubes=3)
        self.assertTrue(easy_laser_drone(me,{"kind":"npc","hp":350}))
        self.assertFalse(easy_laser_drone(self.me,{"kind":"npc","hp":350}))
    def test_contest_only_center_same_height(self):
        me=dict(self.me,cubes=10)
        z=dict(self.zone,next_radius=0,dps=260)
        e=dict(self.enemy,pos=[5,0,0])
        self.assertTrue(contest_center(me,e,z,400,False))
        self.assertFalse(contest_center(me,dict(e,pos=[15,0,0]),z,400,False))
        self.assertFalse(contest_center(me,dict(e,pos=[5,0,18]),z,400,False))
        self.assertFalse(contest_center(me,e,z,400,True))
    def test_mortar_storm_edge_only(self):
        me=dict(self.me,
                weapons=[{"kind":"gun"},{"kind":"mortar"}],
                hp=1350,energy=90)
        z=dict(self.zone,radius=70,next_radius=25,dps=160)
        e=dict(self.enemy,pos=[65,0,0],hp=250)
        self.assertTrue(storm_finish(me,e,[e],z,12))
        self.assertFalse(storm_finish(me,e,[e],dict(z,dps=35),12))
        self.assertFalse(storm_finish(me,e,[e],z,6))
    def test_safe_upgrade_pool_candidate_is_not_an_action(self):
        me=dict(self.me,energy=100,cubes=0,
                weapons=[{"kind":"gun"},None])
        obs={"offer":None,"cubes":[{"id":5001,"pos":[6.,0.,0.]}]}
        self.assertTrue(safe_offer_sculpt_candidate(
            me,obs,300,self.zone))
        self.assertFalse(safe_offer_sculpt_candidate(
            me,obs,60,self.zone))
if __name__=="__main__":unittest.main()
