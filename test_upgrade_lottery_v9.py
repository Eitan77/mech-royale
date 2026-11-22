"""Upgrade offer-pool manipulation scenario tests. Unscored experiment."""
import unittest
from upgrade_lottery_v9 import UpgradeSculptor
class Arena:
    def walk(self,*args):return True
class Cases(unittest.TestCase):
    def setUp(self):
        self.m={"id":0,"pos":[0.,0.,0.],"cubes":0,
                "hp":1400.,"max_hp":1400.,"energy":100.,
                "grounded":True,"in_zone":True,
                "weapons":[{"kind":"gun"},{"kind":"mortar","charge":0}]}
        self.z={"next_radius":380}
        self.c={"id":501,"pos":[6.,0.,0.]}
        self.o={"t":24.,"self":self.m,"cubes":[self.c],
                "zone":self.z,"events":[],"pickups":[],"offer":None}
        self.bot=UpgradeSculptor()
    def act(self,nearest=999,urgent=False):
        act={"tick":1,"move":[1,0],"fire":[True,True]}
        return self.bot.apply(self.o,act,nearest,urgent,Arena())
    def test_drop_secondary_not_starting_gun(self):
        a=self.act()
        self.assertEqual(a.get("drop"),1)
        self.assertEqual(a["move"],[0,0])
        self.assertEqual(a["fire"],[False,False])
        self.assertEqual(self.bot.stage,"DISARM")
    def test_weapon_not_dropped_when_enemy_near(self):
        a=self.act(nearest=50)
        self.assertNotIn("drop",a)
        self.assertEqual(self.bot.stage,"IDLE")
    def test_normal_threshold_cube_collect_then_rearm(self):
        self.act()
        self.o["t"]=24.2
        self.m["weapons"][1]=None
        self.o["events"]=[{"type":"dropped","id":8055,
                           "kind":"mortar","slot":1}]
        self.o["pickups"]=[{"id":8055,"kind":"mortar","pos":[0.,0.,0.]}]
        a=self.act()
        self.assertEqual(self.bot.stage,"COLLECT")
        self.assertGreater(a["move"][0],.8)
        self.m["pos"]=[6.,0.,0.]
        self.o["cubes"]=[]
        self.m["cubes"]=1
        self.o["t"]=24.7
        self.o["offer"]={"choices":[{"id":"nanites"}]}
        a=self.act()
        self.assertEqual(self.bot.stage,"REARM")
        self.assertLess(a["move"][0],-.8)
        self.m["pos"]=[1.,0.,0.]
        self.o["t"]=25.2
        a=self.act()
        self.assertEqual(a["take"],8055)
        self.m["weapons"][1]={"kind":"mortar"}
        self.o["t"]=25.3
        self.act()
        self.assertEqual(self.bot.stage,"IDLE")
    def test_drop_not_attempted_before_nonthreshold_cube(self):
        self.m["cubes"]=1
        a=self.act()
        self.assertNotIn("drop",a)
    def test_does_not_drop_during_laser_charge(self):
        self.m["weapons"][1]={"kind":"laser","charge":.5}
        self.assertNotIn("drop",self.act())
    def test_abort_urgent_storm_movement(self):
        self.act()
        self.o["t"]=24.1
        self.m["weapons"][1]=None
        a=self.act(urgent=True)
        self.assertEqual(self.bot.stage,"ABORT")
        self.assertEqual(a["move"],[1,0])
    def test_no_infinite_wait_for_stolen_weapon(self):
        self.act()
        self.o["t"]=24.3
        self.m["weapons"][1]=None
        self.o["cubes"]=[]
        self.act()
        self.o["t"]=40
        self.bot.stage="REARM"
        self.act()
        self.assertEqual(self.bot.stage,"IDLE")

if __name__=="__main__":unittest.main()
