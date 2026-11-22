"""V7 score-oriented behavior checks (not actual match scoring)."""
import unittest
from strategy_v7 import *

class Arena:
    def shot(self,a,b):return True
class Dummy:
    def __init__(self,los):self.los=los
    def shot(self,a,b):return self.los

class Cases(unittest.TestCase):
    def setUp(self):
        self.me={"pos":[0,0,0],"hp":1400,"max_hp":1400,"cubes":0,
                 "energy":100,"max_energy":100,
                 "stats":{"height":9,"radius":2.5,"walk_speed":11.7},
                 "weapons":[{"kind":"gun"},None],"grounded":True,"in_zone":True}
        self.zone={"center":[0,0],"radius":560,"next_center":[0,0],
                   "next_radius":380,"shrink_end":110}
        self.e={"pos":[140,0,0],"aim":[0,0],"kind":"mech",
                "weapons":["gun"],"cubes":0,"charging":False,
                "hp":1200,"max_hp":1400}
    def test_enemy_facing_away_not_aimed(self):
        self.assertFalse(aimed_at_us(self.e,self.me))
        self.assertTrue(aimed_at_us(dict(self.e,aim=[math.pi,0]),self.me))
    def test_loot_before_distant_fight(self):
        d=situational_danger(self.me,[self.e],Arena())
        self.assertEqual(mode_v7("TRAVEL",1,d,False,6,-99,-99,True),"FARM")
        self.assertFalse(deliberate_mech_fire(self.me,self.e,"FARM",6,-99,self.zone))
    def test_aimed_enemy_forces_fight(self):
        e=dict(self.e,aim=[math.pi,0])
        d=situational_danger(self.me,[e],Arena())
        self.assertEqual(mode_v7("TRAVEL",1,d,False,6,-99,-99,True),"FIGHT")
        self.assertTrue(deliberate_mech_fire(self.me,e,"FIGHT",6,-99,self.zone))
    def test_charging_laser_forces_evasion(self):
        e=dict(self.e,aim=[math.pi,0],weapons=["gun","laser"],charging=True)
        d=situational_danger(self.me,[e],Arena())
        self.assertEqual(mode_v7("TRAVEL",1,d,False,6,-99,-99,True),"EVADE")
    def test_blocked_laser_does_not_force_evasion(self):
        e=dict(self.e,aim=[math.pi,0],weapons=["gun","laser"],charging=True)
        d=situational_danger(self.me,[e],Dummy(False))
        self.assertEqual(d["charged_exposed"],0)
    def test_silence_only_during_safe_heal(self):
        self.assertTrue(should_silence(self.me,"HEAL",self.zone,20,False,False))
        self.assertFalse(should_silence(self.me,"FARM",self.zone,20,False,False))
        self.assertFalse(should_silence(self.me,"HEAL",self.zone,20,False,True))
    def test_silence_move_below_step_sound(self):
        self.assertLess(math.hypot(*silence_movement(self.me,[1.,1.]))*
                        self.me["stats"]["walk_speed"],5)
    def test_fight_only_when_close_or_aiming(self):
        self.assertFalse(deliberate_mech_fire(self.me,self.e,"FIGHT",20,-99,self.zone))
        self.assertTrue(deliberate_mech_fire(self.me,dict(self.e,pos=[20,0,0]),
                                            "FIGHT",20,-99,self.zone))
    def test_low_hp_upgrade_favors_plating(self):
        self.me["hp"]=400
        opts=[{"id":"gun_mag"},{"id":"plating"},{"id":"sensors"}]
        self.assertEqual(upgrade_v7(opts,self.me,50),1)
    def test_full_heal_drop_can_interrupt_passive_regen(self):
        me=dict(self.me,id=3,hp=560)
        drop={"id":1500,"pos":[20.,0.,0.],
              "lands_in":3,"capture_s":4,"holder":None}
        self.assertIsNotNone(healing_supply_drop(me,[drop],[],self.zone,70))

    def test_contested_drop_should_not_interrupt_regen(self):
        me=dict(self.me,id=3,hp=560)
        drop={"id":1500,"pos":[20.,0.,0.],
              "lands_in":3,"capture_s":4,"holder":None}
        enemy=dict(self.e,pos=[40.,0.,0.])
        self.assertIsNone(healing_supply_drop(me,[drop],[enemy],self.zone,70))

    def test_marginal_distant_drop_not_worth_detour(self):
        me=dict(self.me,id=3,hp=1100)
        drop={"id":1500,"pos":[75.,0.,0.],
              "lands_in":12,"capture_s":4,"holder":None}
        self.assertIsNone(healing_supply_drop(me,[drop],[],self.zone,70))

    def test_impossible_center_uses_nearest_legal_perimeter(self):
        import time
        class SolidCenter:
            def ground(self,x,y):return 0.0
            def clear(self,x,y,z,r,h):return math.hypot(x,y)>18+r
            def walk(self,a,b,size):return True
        candidate=nearest_legal_final_ground(
            SolidCenter(),(40.,0.,0.),(0.,0.),1.,time.perf_counter()+.1)
        self.assertIsNotNone(candidate)
        self.assertGreater(math.hypot(*candidate),20)
        self.assertLess(math.hypot(*candidate),42)
        self.assertGreater(candidate[0],0)

    def test_laser_one_shot_priority(self):
        self.me["weapons"][1]={"kind":"laser"}
        opts=[{"id":"gun_mag"},{"id":"laser_damage"},{"id":"sensors"}]
        self.assertEqual(upgrade_v7(opts,self.me,50),1)

if __name__=="__main__":unittest.main()
