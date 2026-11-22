"""V11X verified offer-pool and exact action sequencing; NOT a scored match."""
import unittest
from universal_upgrade_v11 import UniversalSculptor,safe_candidate,chance_one_of_two

class TestSculpt(unittest.TestCase):
    def setUp(self):
        self.p=UniversalSculptor()
        self.me={"id":0,"pos":[0.,0.,0.],"vel":[0.,0.,0.],
                 "hp":1400.,"max_hp":1400.,"energy":100.,
                 "grounded":True,"in_zone":True,"cubes":0,
                 "weapons":[{"kind":"gun","ammo":12},
                            {"kind":"laser","charge":0,"cooldown":0}]}
        self.obs={"type":"obs","tick":0,"t":20.,
                  "self":self.me,"cubes":[{"id":5001,"pos":[6.,0.,0.]}],
                  "mechs":[],"pickups":[],"events":[],"sounds":[],
                  "offer":None}
        self.zone={"center":[0.,0.],"radius":560.,
                   "next_center":[0.,0.],"next_radius":380.,
                   "shrink_end":110.}
        self.thresholds=(1,3,6,10,15,21)
    def action(self,nearest=999):
        return self.p.apply(self.obs,
             {"tick":self.obs["tick"],"fire":[True,True],
              "move":[0,0],"pick":2},
             nearest,-100,self.thresholds,self.zone)

    def test_real_draw_probabilities(self):
        self.assertAlmostEqual(chance_one_of_two(16),.35)
        self.assertAlmostEqual(chance_one_of_two(13),.4230769231)
        self.assertAlmostEqual(chance_one_of_two(9),.5833333333)

    def test_no_drops_while_enemy_in_danger_range(self):
        a=self.action(nearest=110)
        self.assertNotIn("drop",a)
        self.assertEqual(self.p.stage,"IDLE")

    def test_full_double_disarm_cube_offer_and_rearm(self):
        first=self.action()
        self.assertEqual(first.get("drop"),1)  # laser first
        self.assertEqual(first["fire"],[False,False])
        self.assertEqual(self.p.stage,"DROP")
        self.me["weapons"][1]=None
        self.obs["events"]=[{"type":"dropped","id":8001,
                             "kind":"laser","slot":1}]
        self.obs["tick"]+=2
        self.obs["t"]+=.1
        second=self.action()
        self.assertEqual(second.get("drop"),0) # then gun
        self.me["weapons"][0]=None
        self.obs["events"]=[{"type":"dropped","id":8002,
                             "kind":"gun","slot":0}]
        self.obs["pickups"]=[
            {"id":8001,"kind":"laser","pos":[0.,0.,0.]},
            {"id":8002,"kind":"gun","pos":[0.,0.,0.]}]
        self.obs["tick"]+=2
        self.obs["t"]+=.1
        third=self.action()
        self.assertEqual(self.p.stage,"COLLECT")
        self.assertGreater(third["move"][0],.9)
        self.me["pos"]=[2.8,0.,0.]  # cube inside 3.5m; gun only 2.8m away
        self.me["cubes"]=1
        self.obs["cubes"]=[]
        self.obs["offer"]={"id":1,"choices":[
            {"id":"plating"},{"id":"nanites"},{"id":"jets"}]}
        self.obs["tick"]+=2
        self.obs["t"]+=.1
        fourth=self.action()
        self.assertEqual(fourth.get("take"),8002)
        self.assertEqual(fourth.get("pick"),2) # preserve controller's pick
        self.me["weapons"][0]={"kind":"gun"}
        self.obs["pickups"]=[{"id":8001,"kind":"laser","pos":[0.,0.,0.]}]
        self.obs["tick"]+=2
        self.obs["t"]+=.1
        fifth=self.action()
        self.assertEqual(fifth.get("take"),8001)
        self.me["weapons"][1]={"kind":"laser","charge":0}
        self.obs["tick"]+=2
        self.obs["t"]+=.1
        self.action()
        self.assertEqual(self.p.stage,"IDLE")

    def test_cube_collects_too_early_abort_other_drop(self):
        self.action()
        self.me["weapons"][1]=None
        self.me["cubes"]=1
        self.obs["offer"]={"choices":[{"id":"armor"}]}
        a=self.action()
        self.assertNotIn("drop",a)
        self.assertEqual(self.p.stage,"REARM")

    def test_active_laser_cannot_be_dropped(self):
        self.me["weapons"][1]["charge"]=.3
        self.assertNotIn("drop",self.action())
        self.assertEqual(self.p.stage,"IDLE")

    def test_sound_and_zone_safety_gate(self):
        self.obs["sounds"]=[{"kind":"gun","dist":"near","age":.2}]
        self.assertIsNone(safe_candidate(self.obs,self.me,999,-100,self.thresholds,self.zone))
        self.obs["sounds"]=[]
        z=dict(self.zone,next_radius=20.)
        self.assertIsNone(safe_candidate(self.obs,self.me,999,-100,self.thresholds,z))

    def test_urgent_enemy_interrupts_second_drop(self):
        self.action()
        self.me["weapons"][1]=None
        a=self.action(nearest=80)
        self.assertNotIn("drop",a)
        self.assertEqual(self.p.stage,"REARM")

if __name__=="__main__":unittest.main()
