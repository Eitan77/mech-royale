"""V8 policy tests. Does NOT assert actual match scores."""
import unittest,math
from scoremax_v8 import *
class Arena:
    def shot(self,a,b):return True
    def walk(self,a,b,size):return True
class Blocked(Arena):
    def shot(self,a,b):return False
class Tests(unittest.TestCase):
    def setUp(self):
        self.me={"pos":[0.,0.,0.],"hp":1100,"max_hp":1400,"cubes":0,
                 "stats":{"height":9.,"walk_speed":11.7},"in_zone":True}
        self.zone={"center":[0,0],"radius":560,"next_center":[0,0],
                   "next_radius":380,"dps":20}
        self.danger={"close":0,"exposed":0,"aimed_exposed":0,
                     "charged_exposed":0,"laser_exposed":0,"closest":999}
        self.npc={"id":104,"kind":"npc","pos":[35.,0.,0.],"hp":350}
    def test_score_banked_formula(self):
        self.assertEqual(score_phase(16,0),0)
        self.assertEqual(score_phase(6,350),10)
        self.assertEqual(score_phase(1,400),15)
    def test_npc_detected_even_without_mech_enemy(self):
        self.assertEqual(npc_pressure(self.me,[self.npc],Arena(),12),[self.npc])
    def test_cover_occludes_npc(self):
        self.assertFalse(npc_pressure(self.me,[self.npc],Blocked(),12))
    def test_recent_npc_hit_expands_chase_danger(self):
        n=dict(self.npc,pos=[70.,0.,0.])
        self.assertFalse(npc_pressure(self.me,[n],Arena(),20,-100))
        self.assertTrue(npc_pressure(self.me,[n],Arena(),20,19))
    def test_recent_hit_does_not_expand_other_npcs_chase_radius(self):
        other=dict(self.npc,id=106,pos=[73.,0.,0.])
        self.assertFalse(npc_pressure(self.me,[other],Arena(),20,19,
                                      chasing_npc_id=105))
        self.assertTrue(npc_pressure(self.me,[other],Arena(),20,19,
                                     chasing_npc_id=106))
    def test_ten_point_placement_banked_changes_late_risk(self):
        self.assertEqual(mode_v8("FARM",.89,self.danger,False,300,-100,-100,
                                 True,alive=6),"TRAVEL")
        self.assertEqual(mode_v8("FARM",.89,self.danger,False,100,-100,-100,
                                 True,alive=6),"FARM")

    def test_heal_forbidden_when_npc_could_shoot(self):
        self.assertEqual(mode_v8("HEAL",.6,self.danger,False,12,0,0,
                                  False,npc_active=True),"EVADE")
    def test_resource_gathering_beats_sitting_at_moderate_hp(self):
        self.assertEqual(mode_v8("HEAL",.73,self.danger,False,12,0,0,
                                  True),"FARM")
    def test_heal_still_allowed_when_critical_and_safe(self):
        self.assertEqual(mode_v8("TRAVEL",.40,self.danger,False,12,0,0,
                                  True),"HEAL")
    def test_no_early_aggression_when_safe(self):
        self.assertEqual(mode_v8("TRAVEL",1,self.danger,False,12,-99,-99,
                                  False),"TRAVEL")
    def test_npc_escape_goes_away(self):
        q=immediate_npc_escape(self.me,self.npc,self.zone,Arena(),1.)
        self.assertLess(q[0],0)
    def test_storm_safety_at_end(self):
        z=dict(self.zone,radius=25,next_radius=0,dps=260)
        self.assertTrue(endgame_priority(16,.8,z,390,True,0.2))
    def test_opportunistic_kill_only_weak_isolated(self):
        t={"kind":"mech","pos":[40,0,0],"hp":100,"max_hp":1400}
        self.assertTrue(opportunistic_kill(t,self.me,16,0))
        self.assertFalse(opportunistic_kill(t,self.me,16,3))
    def test_silent_rear_laser_pickoff(self):
        me=dict(self.me,
                hp=1350,
                weapons=[{"kind":"gun"},
                         {"kind":"laser","stats":{"damage":315}}],
                cubes=0)
        enemy={"id":6,"kind":"mech","pos":[170.,0.,0.],
               "aim":[0.,0.],"weapons":["gun","mortar"],
               "hp":700,"max_hp":1400,"charging":False}
        self.assertTrue(laser_ambush(me,enemy,[enemy],self.zone,170,12))
    def test_ambush_rejects_already_aiming_enemy(self):
        me=dict(self.me,hp=1350,
                weapons=[{"kind":"gun"},{"kind":"laser","stats":{"damage":315}}],
                cubes=0)
        enemy={"id":6,"kind":"mech","pos":[170.,0.,0.],
               "aim":[math.pi,0.],"weapons":["gun","mortar"],
               "hp":700,"max_hp":1400,"charging":False}
        self.assertFalse(laser_ambush(me,enemy,[enemy],self.zone,170,12))
    def test_ambush_rejects_grouped_squad(self):
        me=dict(self.me,hp=1350,
                weapons=[{"kind":"gun"},{"kind":"laser","stats":{"damage":315}}],
                cubes=0)
        enemy={"id":6,"kind":"mech","pos":[170.,0.,0.],
               "aim":[0.,0.],"weapons":["gun","mortar"],
               "hp":700,"max_hp":1400,"charging":False}
        guard=dict(enemy,id=7,pos=[170.,50.,0.])
        self.assertFalse(laser_ambush(me,enemy,[enemy,guard],self.zone,170,12))
    def test_ambush_does_not_assume_two_rear_hits(self):
        me=dict(self.me,hp=1350,
                weapons=[{"kind":"gun"},{"kind":"laser","stats":{"damage":315}}],
                cubes=0)
        enemy={"id":6,"kind":"mech","pos":[170.,0.,0.],
               "aim":[0.,0.],"weapons":["gun"],
               "hp":900,"max_hp":1400,"charging":False}
        # First rear: 472.5; next facing forward: 315; 900 will survive.
        self.assertFalse(laser_ambush(me,enemy,[enemy],self.zone,170,12))
    def test_ambush_preserves_banked_10_points(self):
        me=dict(self.me,hp=1350,
                weapons=[{"kind":"gun"},{"kind":"laser","stats":{"damage":315}}],
                cubes=0)
        enemy={"id":6,"kind":"mech","pos":[170.,0.,0.],
               "aim":[0.,0.],"weapons":["gun","mortar"],
               "hp":600,"max_hp":1400,"charging":False}
        self.assertFalse(laser_ambush(me,enemy,[enemy],self.zone,170,6))

    def test_probability_score_identity(self):
        self.assertAlmostEqual(expected_placement_proxy(16,[.8]*15),12.)

if __name__=="__main__":unittest.main()
