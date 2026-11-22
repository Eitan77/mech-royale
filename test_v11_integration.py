"""V11 multi-tick integration against the authentic recorded hello and arena."""
import copy,gzip,json,math,os,unittest
from pathlib import Path
from unittest.mock import patch
from controller import Bot

KIT=Path(os.environ.get("MECH_KIT","/tmp/mech-kit/mechfight-kit"))

class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with gzip.open(KIT/"check"/"stream.jsonl.gz","rt") as f:
            cls.hello=json.loads(next(f))
            cls.first=json.loads(next(f))
        cls.hello["map"]["dir"]=str(KIT/"arena")

    def setup_pursuit(self):
        bot=Bot(copy.deepcopy(self.hello))
        o=copy.deepcopy(self.first)
        p=o["self"]["pos"]
        o["t"]=8.
        o["self"]["hp"]=800.
        o["self"]["grounded"]=True
        o["self"]["vel"]=[0.,0.,0.]
        o["events"]=[]
        o["zone"].update(center=p[:2],radius=560.,
                         next_center=p[:2],next_radius=380.,
                         shrink_start=60.,shrink_end=110.,dps=20.)
        o["mechs"]=[{"id":9,"kind":"mech",
                     "pos":[p[0]+105,p[1],p[2]],
                     "vel":[0.,0.,0.],"aim":[math.pi,0.],
                     "hp":1400,"max_hp":1400,"cubes":0,
                     "weapons":["gun"],"charging":False}]
        bot.last_damage=7.
        bot.arena.shot=lambda *args:True
        bot.arena.walk=lambda *args:True
        bot.cover_point=lambda *args:None
        bot.foliage.refuge=lambda *args:None
        destination=(p[0],p[1]+23)
        bot.shadow_atlas.search=lambda *args:(destination,125.)
        return bot,o,destination

    def test_early_focus_chases_hard_cover_not_enemy(self):
        bot,o,dest=self.setup_pursuit()
        with patch("controller.storm_screen",return_value=None),patch(
                "controller.choose_movement",
                side_effect=lambda arena,me,z,move,*a,**kw:(move,False)):
            act=bot.act(o)
        self.assertTrue(bot.shadow_active)
        self.assertEqual(bot.shadow_goal,dest)
        self.assertIn(bot.mode,("EVADE","HEAL"))
        self.assertGreater(act["move"][1],.25)
        self.assertFalse(any(act["fire"]))

    def test_shadow_holds_until_health_regens_after_losing_tracking(self):
        bot,o,dest=self.setup_pursuit()
        with patch("controller.storm_screen",return_value=None),patch(
                "controller.choose_movement",
                side_effect=lambda arena,me,z,move,*a,**kw:(move,False)):
            bot.act(o)
            later=copy.deepcopy(o)
            later["tick"]+=2
            later["t"]+=.1
            later["mechs"]=[]
            later["self"]["pos"]=[dest[0],dest[1],o["self"]["pos"][2]]
            later["events"]=[]
            act=bot.act(later)
        self.assertTrue(bot.shadow_active)
        self.assertTrue(bot.shadow_sheltered)
        self.assertEqual(act["move"],[0.,0.])
        self.assertEqual(act["fire"],[False,False])
        self.assertGreater(bot.shadow_until-later["t"],10)

    def test_close_sensor_threat_breaks_old_shadow_lock(self):
        bot,o,dest=self.setup_pursuit()
        with patch("controller.storm_screen",return_value=None):
            bot.act(o)
            o2=copy.deepcopy(o)
            o2["t"]+=.1
            o2["tick"]+=2
            o2["mechs"][0]["pos"]=[
                o2["self"]["pos"][0]+25,
                o2["self"]["pos"][1],o2["self"]["pos"][2]]
            bot.act(o2)
        self.assertFalse(bot.shadow_active)

    def test_storm_emergency_preempts_shadow(self):
        bot,o,dest=self.setup_pursuit()
        with patch("controller.storm_screen",return_value=None):
            bot.act(o)
            o2=copy.deepcopy(o)
            o2["tick"]+=2
            o2["t"]=108
            p=o["self"]["pos"]
            o2["zone"]["next_center"]=[p[0]+210,p[1]]
            o2["zone"]["next_radius"]=55
            o2["zone"]["shrink_start"]=60
            o2["zone"]["shrink_end"]=110
            o2["mechs"]=[]
            bot.act(o2)
        self.assertFalse(bot.shadow_active)
        self.assertEqual(bot.mode,"ZONE")

if __name__=="__main__":unittest.main()
