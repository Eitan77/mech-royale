"""V6 final-zone regressions, separate from V5 baseline."""
import unittest
from throne_v6 import zone_future,expected_zone_damage,defensive_contest,permit_stationary_laser,bodyblock_min_damage

class Tests(unittest.TestCase):
    def setUp(self):
        self.zone={"center":[0.,0.],"next_center":[20.,0.],
                   "radius":25.,"next_radius":0.,"shrink_start":390.,
                   "shrink_end":415.,"dps":260.}
        self.me={"pos":[20.,0.,0.],"vel":[0.,0.,0.],
                 "cubes":10,"energy":85.}
        self.enemy={"kind":"mech","pos":[26.,0.,0.],"cubes":0}
    def test_future_moving_circle(self):
        center,r=zone_future(self.zone,390,12.5)
        self.assertAlmostEqual(center[0],10)
        self.assertAlmostEqual(r,12.5)
    def test_final_center_always_inside_moving_circle(self):
        for i in range(51):
            c,r=zone_future(self.zone,390,25*i/50)
            self.assertLessEqual(abs(20-c[0]),r+1e-7)
    def test_storm_cost_exposure_vs_center(self):
        # At t410 the real observation already reflects the moving circle,
        # not the circle at t390. Use a self-consistent current snapshot.
        late=dict(self.zone,center=[16.,0.],radius=5.)
        safe=expected_zone_damage(late,410,[20.,0.],5)
        outside=expected_zone_damage(late,410,[10.,0.],5)
        self.assertEqual(safe,0)
        self.assertGreater(outside,500)
    def test_contest_target_near_our_anchor(self):
        self.assertTrue(defensive_contest(self.me,self.enemy,self.zone,392,False,False))
    def test_no_far_chase(self):
        foe=dict(self.enemy,pos=[78.,0.,0.])
        self.assertFalse(defensive_contest(self.me,foe,self.zone,410,False,False))
    def test_never_fire_during_heal(self):
        self.assertFalse(defensive_contest(self.me,self.enemy,self.zone,410,False,True))
        self.assertFalse(defensive_contest(self.me,self.enemy,self.zone,410,True,False))
    def test_laser_only_when_centered(self):
        self.assertTrue(permit_stationary_laser(self.me,self.zone))
        self.assertFalse(permit_stationary_laser(dict(self.me,pos=[23,0,0]),self.zone))
    def test_shifting_zone_conservative_bound(self):
        self.assertAlmostEqual(bodyblock_min_damage(10,0,0),1625.)
        self.assertAlmostEqual(bodyblock_min_damage(10,0,25),812.5)
        self.assertAlmostEqual(bodyblock_min_damage(0,0,0),1300.)

if __name__=="__main__":unittest.main()
