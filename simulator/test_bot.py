"""Regression tests for navigation and conservative visibility."""
import copy
import gzip
import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'python'))
from avoid_bot import Bot, World
from simulate import Arena, ROOT, CURRENT_BOT

class BotRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with gzip.open(ROOT/'check/stream.jsonl.gz','rt') as f:
            cls.hello=json.loads(next(f));cls.obs=json.loads(next(f))
        cls.hello['map']['dir']=str(ROOT/'arena')
        cls.world=World(cls.hello)

    def test_roof_floor_and_clearance(self):
        x,y,z=-37.4,-291.6375,24.27
        self.assertAlmostEqual(self.world.surface(x,y,z,radius=2.5),z)
        self.assertTrue(self.world.clear(x,y,z,2.5,9))
        self.assertFalse(self.world.clear(x,y,self.world.height(x,y),2.5,9))

    def test_escapes_rooftop(self):
        a=Arena(1,1,'rooftop',CURRENT_BOT)
        me=a.actors[0];initial=list(me['pos'])
        for i in range(150):
            t=i*.1;action=a.bot.act(a.observation(t,a.zone(t)))
            a.move(me,action,.1,t)
        self.assertGreater(__import__('math').dist(me['pos'],initial),10)
        self.assertLess(me['pos'][2],initial[2]-10)

    def test_outside_zone_moves_inward(self):
        b=Bot(self.hello);o=copy.deepcopy(self.obs)
        o.update(mechs=[],sounds=[],events=[])
        x,y,z=o['self']['pos']
        o['zone'].update(center=[x-50,y],radius=40,next_center=[x-50,y],next_radius=40,shrink_start=100,shrink_end=150)
        a=b.act(o)
        self.assertLess(a['move'][0],0)
        self.assertEqual(a['fire'],[False,False])

    def test_full_scan_completes(self):
        import math
        b=Bot(self.hello);o=copy.deepcopy(self.obs)
        o.update(mechs=[],sounds=[],events=[])
        total=0
        for i in range(28):
            o['t']=i*.1;o['tick']=i*2
            action=b.act(o)
            delta=(action['aim'][0]-o['self']['aim'][0]+math.pi)%math.tau-math.pi
            turn=max(-.4,min(.4,delta));total+=abs(turn)
            o['self']['aim'][0]+=turn
        self.assertGreaterEqual(total,math.tau-.05)
        self.assertGreater(b.next_scan,0)

    def test_refuge_choice_survives_short_cpu_slices(self):
        import time
        pos=(-321.5,-248.0,-5.39)
        enemy=dict(id=1,kind='mech',pos=[-256.5,-248.0,-5.47],cubes=0)
        goals=[]
        for budget in (.001,.2):
            b=Bot(self.hello)
            for _ in range(1000):
                b.plan(pos,[41.3,-72.8],544,[enemy],9,0,time.perf_counter()+budget)
                if b.goal is not None:break
            self.assertIsNotNone(b.goal)
            goals.append(b.goal)
        self.assertEqual(goals[0],goals[1])

    def test_size_growth_invalidates_navigation(self):
        b=Bot(self.hello);o=copy.deepcopy(self.obs)
        o['self']['stats']['radius']=4
        o['self']['stats']['height']=12
        b.act(o)
        self.assertAlmostEqual(b.nav_radius,4.4)
        self.assertEqual(b.nav_height,12)

    def test_initialization_failure_is_not_ready(self):
        import subprocess
        bad=dict(type='hello',config={},map=dict(dir='__missing_map__',files=['v2/world.json']))
        p=subprocess.run([sys.executable,'-u',str(CURRENT_BOT)],input=json.dumps(bad)+'\n',capture_output=True,text=True,timeout=10)
        self.assertNotEqual(p.returncode,0)
        self.assertNotIn('ready',p.stdout)

    def test_solid_ray_and_hole(self):
        w=World.__new__(World)
        p=dict(_id=0,base=0,top=20,ring=[0,0,10,0,10,10,0,10],holes=[],_edges=[(0,10,0,0),(0,0,10,0),(10,0,10,10),(10,10,0,10)])
        w.bins={(0,0):[p]};w.height=lambda x,y:-100
        self.assertTrue(w.ray_blocked((-10,5,8),(20,5,8)))
        self.assertFalse(w.ray_blocked((-10,5,25),(20,5,25)))
        self.assertFalse(w.ray_blocked((-10,-5,8),(20,-5,8)))

if __name__=='__main__':unittest.main()
