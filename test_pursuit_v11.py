"""V11 hard-cover geometry and anti-lead checks. Not a game score."""
import math,time,unittest,os
from pathlib import Path
from pursuit_v11 import ShadowAtlas,focus_fire,anti_lead,hold_shadow
from arena import Arena

class RectArena:
    def __init__(self):
        self.ring=((0.,0.),(10.,0.),(10.,10.),(0.,10.))
        prism=(0.,25.,self.ring,())
        self.bins={(0,0):[prism],(1,0):[prism]}
    def ground(self,x,y):return 0.
    def clear(self,x,y,z,radius,height):
        return not (0<=x<=10 and 0<=y<=10)
    def walk(self,a,b,size):return True
    def shot(self,a,b):
        if a[0]>b[0]:a,b=b,a
        if a[0]<=5<=b[0]:
            t=(5-a[0])/(b[0]-a[0])
            y=a[1]+t*(b[1]-a[1])
            if 0<y<10:return False
        return True

class Tests(unittest.TestCase):
    def setUp(self):
        self.me={"pos":(25.,25.,0.),"hp":1400.,"max_hp":1400.,
                 "cubes":0,"stats":{"walk_speed":11.7}}
        self.enemy={"pos":(-40.,5.,0.),"aim":[0.,0.],
                    "kind":"mech","weapons":["gun"],"cubes":0}
        self.zone={"center":(0.,0.),"radius":560.,
                   "next_center":(0.,0.),"next_radius":380.,
                   "shrink_end":110.}
    def test_shadow_really_blocks_prism_vision_and_shots(self):
        ar=RectArena()
        res=ShadowAtlas(ar).search(self.me,[self.enemy],self.zone,ar,10,
                                   time.perf_counter()+.1)
        self.assertIsNotNone(res)
        q=res[0]
        self.assertFalse(ar.shot((-40,5,7),(q[0],q[1],8.8)))
        self.assertTrue(ar.clear(*q,0.,2.7,9.))
    def test_shadow_rejects_next_zone_outside(self):
        ar=RectArena()
        zone=dict(self.zone,next_center=[400.,250.],next_radius=30.)
        self.assertIsNone(ShadowAtlas(ar).search(
            self.me,[self.enemy],zone,ar,10,time.perf_counter()+.1))
    def test_single_glance_does_not_cancel_safe_farm(self):
        p=self.me["pos"]
        enemy=dict(self.enemy,aim=[math.atan2(p[1]-5,p[0]+40),0])
        self.assertFalse(focus_fire(self.me,[enemy],[],8,-100))
        self.me["hp"]=1050
        self.assertTrue(focus_fire(self.me,[enemy],[],8,-100))
        self.me["hp"]=1400
        self.assertTrue(focus_fire(self.me,[enemy],[],8,7))
    def test_anti_lead_reverses_periodically(self):
        a=anti_lead(self.me,[self.enemy],10,9,self.zone)
        b=anti_lead(self.me,[self.enemy],10.31,9,self.zone)
        self.assertIsNotNone(a)
        self.assertIsNotNone(b)
        self.assertLess(a[0]*b[0]+a[1]*b[1],-.5)
    def test_shadow_persists_when_enemy_vision_vanishes(self):
        self.assertTrue(hold_shadow(
            self.me,(20,16),[],self.zone,RectArena(),
            time.perf_counter()+.1))
    def test_real_arena_has_corner_index(self):
        root=Path(os.environ.get("MECH_KIT","/tmp/mech-kit/mechfight-kit"))/"arena"
        atlas=ShadowAtlas(Arena(str(root)))
        self.assertGreater(len(atlas.corners),400)
if __name__=="__main__":unittest.main()
