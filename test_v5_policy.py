"""Fast policy regressions. Run: python3 -m unittest -v test_v5_policy."""
import unittest
from tactics_v5 import classify_danger,next_mode,candidate_resource_target,energy_floor,zone_eta,should_commit_resource

class DummyArena:
    def __init__(self,los=True): self.los=los
    def shot(self,a,b): return self.los

class Tests(unittest.TestCase):
    def setUp(self):
        self.me={"pos":[0,0,0],"stats":{"height":9},"max_energy":100}
        self.laser={"id":1,"kind":"mech","pos":[90,0,0],"weapons":["gun","laser"],"cubes":0,"charging":True}
        self.none={"exposed":0,"near":0,"lasers":0,"charging":0,"closest":999}
    def test_proactive_laser_evasion(self):
        d=classify_danger(self.me,[self.laser],DummyArena(True))
        self.assertEqual(next_mode("TRAVEL",1,d,False,10,-100,-100),"EVADE")
    def test_occluded_laser_no_evasion(self):
        d=classify_danger(self.me,[self.laser],DummyArena(False))
        self.assertEqual(next_mode("TRAVEL",1,d,False,10,-100,-100),"TRAVEL")
    def test_recovery_stays_quiet(self):
        self.assertEqual(next_mode("HEAL",.78,self.none,False,10,0,0,has_cover=True),"HEAL")
    def test_farming_target(self):
        target={"id":1999,"pos":[24,0,0],"kind":"crate"}
        self.assertEqual(candidate_resource_target(("crates",1999,[24,0,0]),{"crates":[target]}),target)
    def test_route_eta(self):
        self.assertGreater(zone_eta(40,False,None,12),zone_eta(40,True,None,12)*2)
    def test_energy_reserve(self):
        self.assertGreater(energy_floor(self.me),20)
        self.assertLess(energy_floor(self.me,True),10)
    def test_close_enemy_interrupts_farm(self):
        d={"exposed":1,"near":1,"lasers":0,"charging":0,"closest":28}
        self.assertEqual(next_mode("FARM",1,d,False,10,-100,-100,has_objective=True),"FIGHT")
    def test_far_enemy_allows_farm(self):
        d={"exposed":1,"near":0,"lasers":0,"charging":0,"closest":160}
        self.assertEqual(next_mode("TRAVEL",1,d,False,10,-100,-100,has_objective=True),"FARM")

    def test_resource_hysteresis(self):
        self.assertTrue(should_commit_resource(3,1,True,False))
        self.assertFalse(should_commit_resource(6,1,True,False))

if __name__=="__main__": unittest.main()
