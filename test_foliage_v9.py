"""V9 geometry and stealth checks; uses the REAL kit world.json."""
import json
import math
import os
import time
import unittest
from pathlib import Path
from foliage_v9 import Foliage,should_ghost,stealth_vector

MAP=Path(os.environ.get("MECH_KIT","/tmp/mech-kit/mechfight-kit"))/"arena"

class SimpleArena:
    def ground(self,x,y):return 0.
    def clear(self,*args):return True
    def walk(self,*args):return True

class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.woods=Foliage(MAP)
    def test_all_real_trees_loaded(self):
        self.assertGreaterEqual(len(self.woods.trees),1500)
    def test_proximity_sensors_see_through_any_tree(self):
        enemy={"pos":[-489.+35,143.25,0.],"cubes":0}
        self.assertEqual(self.woods.concealment(enemy,(-489.,143.25),0),0.)
    def test_actual_large_crown_has_optical_depth(self):
        # This is a real 12.77m-radius canopy in the map near (-489,143).
        a=(-489.+90.,143.25,8.)
        b=(-489.,143.25,8.)
        self.assertGreater(self.woods.screen_depth(a,b),1.5)
    def test_ray_ending_at_crown_center_uses_half_chord(self):
        from collections import defaultdict
        from foliage_v9 import CELL
        canopy=Foliage.__new__(Foliage)
        canopy.density=.35
        canopy.block_t=.25
        # One 10m crown; put trunk far away to isolate crown geometry.
        canopy.trees=[(0.,0.,3.,15.,10.,100.,100.,.2,0.)]
        canopy.cells=defaultdict(list)
        for cx in range(-3,3):
            for cy in range(-2,3):
                canopy.cells[(cx,cy)]=[0]
        depth=canopy.screen_depth((-30.,0.,8.),(0.,0.,8.))
        self.assertAlmostEqual(depth,3.5,places=4)

    def test_short_uncovered_line_has_no_canopy_depth(self):
        a=(0.,0.,200.)
        b=(5.,0.,200.)
        self.assertAlmostEqual(self.woods.screen_depth(a,b),0.)
    def test_ghost_only_while_safe(self):
        me={"hp":700.,"max_hp":1400.,"in_zone":True}
        z={"dps":35}
        self.assertTrue(should_ghost(15,13,12,z,me))
        self.assertFalse(should_ghost(15,13,12,dict(z,dps=260),me))
    def test_stealth_speed_command(self):
        me={"pos":[0,0,0]}
        move=stealth_vector(me,[50,0])
        self.assertLess(math.hypot(*move)*11.7,5.)
        self.assertEqual(stealth_vector(me,[1,1]),[0.,0.])
    def test_refuge_respects_next_zone_margin(self):
        me={"pos":[-480.,143.,0.],"cubes":0}
        enemy={"kind":"mech","pos":[-380.,143.,0.],"cubes":0}
        z={"center":[0,0],"radius":600,"next_center":[0,0],"next_radius":30}
        self.assertIsNone(self.woods.refuge(me,[enemy],z,SimpleArena(),
                                            time.perf_counter()+.03))
    def test_shadow_behind_crown_when_trunk_center_is_unusable(self):
        from collections import defaultdict
        shade=Foliage.__new__(Foliage)
        shade.density=.35
        shade.block_t=.25
        shade.trees=[(0.,0.,2.,15.,6.,0.,0.,.6,0.)]
        shade.cells=defaultdict(list)
        for cx in range(-2,3):
            for cy in range(-2,3):
                shade.cells[(cx,cy)]=[0]
        class BlockedTrunk:
            def ground(self,x,y):return 0.
            def clear(self,x,y,*args):return math.hypot(x,y)>5.2
            def walk(self,*args):return True
        me={"pos":[12.,0.,0.],"cubes":0}
        enemy={"kind":"mech","pos":[-80.,0.,0.],"cubes":0}
        zone={"center":[0.,0.],"radius":100.,
              "next_center":[0.,0.],"next_radius":80.}
        result=shade.refuge(me,[enemy],zone,BlockedTrunk(),
                            time.perf_counter()+.1,limit=35.)
        self.assertIsNotNone(result)
        self.assertGreater(result[1][0],5.2)
        self.assertGreaterEqual(result[2],.7)

    def test_hide_refuge_never_chosen_inside_proximity(self):
        me={"pos":[-480.,143.,0.],"cubes":0}
        enemy={"kind":"mech","pos":[-465.,143.,0.],"cubes":0}
        z={"center":[0,0],"radius":600,"next_center":[-490,143],"next_radius":150}
        self.assertIsNone(self.woods.refuge(me,[enemy],z,SimpleArena(),
                                            time.perf_counter()+.03))

if __name__=="__main__":unittest.main()
