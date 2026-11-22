"""Hunter policy and shooting tests; not claims of match performance."""
import copy
import gzip
import json
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python' if (ROOT / 'python').exists() else ROOT))
from hunter_bot import Bot, Navigator, intercept
import mechfight as mf


class HunterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with gzip.open(ROOT / 'check/stream.jsonl.gz', 'rt') as f:
            cls.hello = json.loads(next(f))
            cls.recorded = json.loads(next(f))
        cls.hello['map']['dir'] = str(ROOT / 'arena')

    def setUp(self):
        self.bot = Bot(self.hello)
        self.obs = copy.deepcopy(self.recorded)
        for key in ('mechs', 'crates', 'cubes', 'pickups', 'events', 'sounds', 'projectiles', 'drops', 'beams'):
            self.obs[key] = []
        self.obs['offer'] = None
        me = self.obs['self']
        me.update(hp=1400, max_hp=1400, cubes=0, energy=100, max_energy=100, aim=[0,0], vel=[0,0,0], grounded=True, in_zone=True)
        me['weapons'] = [dict(kind='gun', stats=copy.deepcopy(self.hello['config']['weapons']['gun']), ammo=12, reload=0, cooldown=0), None]
        self.bot.map.ray_blocked = lambda a,b: False
        mf.draw.clear()

    def actor(self, ident=1, kind='mech', hp=1400, cubes=0, distance=65):
        x,y,z = self.obs['self']['pos']
        return dict(id=ident, kind=kind, hp=hp, max_hp=1400, cubes=cubes, pos=[x+distance,y,z], vel=[0,0,0], aim=[math.pi,0], weapons=['gun'])

    def nav_stub(self):
        return patch.object(Navigator, 'act', return_value=dict(tick=self.obs['tick'], move=[0,0], boost=False, aim=[0,0], fire=[False,False]))

    def test_farms_drone_before_ten(self):
        self.obs['mechs'] = [self.actor(101,'npc',350)]
        mode,key,goal,target = self.bot.choose(self.obs)
        self.assertEqual(mode,'HUNT')
        self.assertEqual(target['id'],101)

    def test_prefers_free_cubes(self):
        self.obs['mechs'] = [self.actor(101,'npc',350)]
        p = list(self.obs['self']['pos']);p[0]+=10
        self.obs['cubes'] = [dict(id=5000,pos=p)]
        self.assertEqual(self.bot.choose(self.obs)[0],'LOOT')

    def test_farms_crates_but_stops_at_ten(self):
        c=self.actor(1000,'crate',300,distance=30)
        self.obs['crates']=[c]
        self.assertEqual(self.bot.choose(self.obs)[0],'FARM')
        self.obs['self']['cubes']=10
        self.assertEqual(self.bot.choose(self.obs)[0],'HIDE')
        self.assertTrue(self.bot.hide_unlocked)

    def test_only_fights_weaker_mechs(self):
        me=self.obs['self'];equal=self.actor()
        self.assertFalse(self.bot.weaker(me,equal))
        equal['hp']=400
        self.assertTrue(self.bot.weaker(me,equal))
        del equal['hp']
        self.assertFalse(self.bot.weaker(me,equal))

    def test_hiding_ambushes_weak_but_not_strong(self):
        self.obs['self']['cubes']=10
        weak=self.actor(hp=300)
        self.obs['mechs']=[weak]
        self.assertEqual(self.bot.choose(self.obs)[0],'AMBUSH')
        weak.update(hp=2500,cubes=20,weapons=['gun','laser'])
        self.assertEqual(self.bot.choose(self.obs)[0],'HIDE')

    def test_avoids_supported_target(self):
        self.obs['mechs']=[self.actor(hp=300), self.actor(2,hp=2500,cubes=20,distance=80)]
        self.assertNotIn(self.bot.choose(self.obs)[0],('HUNT','AMBUSH'))

    def test_recovery_hysteresis(self):
        self.obs['mechs']=[self.actor(101,'npc',350)]
        self.obs['self']['hp']=600
        self.assertEqual(self.bot.choose(self.obs)[0],'RECOVER')
        self.obs['self']['hp']=900
        self.assertEqual(self.bot.choose(self.obs)[0],'RECOVER')
        self.obs['self']['hp']=1300
        self.assertEqual(self.bot.choose(self.obs)[0],'HUNT')

    def test_zone_takes_priority(self):
        self.obs['self']['in_zone']=False
        self.obs['mechs']=[self.actor(101,'npc',350)]
        self.assertEqual(self.bot.choose(self.obs)[0],'ZONE')

    def test_actual_aim_and_wall_gate_fire(self):
        target=self.actor(hp=300)
        me=self.obs['self'];me['aim']=[math.pi,0]
        action,_=self.bot.firing_action(me,target)
        self.assertFalse(action['fire'][0])
        # Slew toward the commanded direction until barrel-offset aim settles.
        for _ in range(4):
            me['aim']=action['aim'];action,_=self.bot.firing_action(me,target)
        self.assertTrue(action['fire'][0])
        self.bot.map.ray_blocked=lambda a,b:True
        action,_=self.bot.firing_action(me,target)
        self.assertFalse(action['fire'][0])

    def test_reload_and_target_leading(self):
        target=self.actor(hp=300)
        self.obs['self']['weapons'][0]['ammo']=0
        action,_=self.bot.firing_action(self.obs['self'],target)
        self.assertTrue(action['reload'])
        self.assertFalse(action['fire'][0])
        p=intercept([0,0,0],[100,0,0],[0,10,0],100)
        self.assertGreater(p[1],10)
        self.assertAlmostEqual(math.dist([0,0,0],p)/100,p[1]/10)

    def test_kill_then_loot_then_hide(self):
        self.obs['self']['cubes']=10
        target=self.actor(hp=100)
        self.bot.last_victim=target
        self.obs['events']=[dict(type='kill',target=target['id'])]
        with self.nav_stub(): self.bot.act(self.obs)
        self.assertEqual(self.bot.mode,'LOOT')
        self.obs['self']['pos']=list(target['pos'])
        self.obs['self']['cubes']=12
        self.obs['events']=[]
        self.obs['t']+=.1
        with self.nav_stub(): self.bot.act(self.obs)
        self.assertEqual(self.bot.mode,'HIDE')

    def test_collects_delayed_kill_after_switching_targets(self):
        self.obs['self']['cubes']=10
        previous=self.actor(5,hp=100,distance=50)
        self.bot.actor_memory[5]=(previous,self.obs['t'])
        self.bot.last_victim=self.actor(6,hp=100,distance=90)
        self.obs['events']=[dict(type='kill',target=5)]
        with self.nav_stub(): self.bot.act(self.obs)
        self.assertEqual(self.bot.mode,'LOOT')
        self.assertEqual(self.bot.mission_goal,previous['pos'])

    def test_five_drone_kills_collect_ten_then_hide(self):
        # Deterministic policy integration, not a match simulator: flat movement,
        # stationary drones, ideal registered hits, and automatic cube pickup.
        me=self.obs['self'];me['pos']=[0,0,0]
        npc=None;defeated=0;spawned=0;pending=[];reload_left=0;cooldown=0
        def navigate(_obs):
            goal=self.bot.mission_goal
            dx,dy=(goal[0]-me['pos'][0],goal[1]-me['pos'][1]) if goal else (0,0)
            length=max(1,math.hypot(dx,dy))
            return dict(tick=_obs['tick'],move=[dx/length,dy/length],boost=False,aim=me['aim'],fire=[False,False])
        with patch.object(Navigator,'act',side_effect=navigate):
            for i in range(2000):
                if npc is None and spawned<5 and me['cubes']>=defeated*2:
                    npc=dict(id=101+spawned,kind='npc',pos=[me['pos'][0]+30,me['pos'][1],0],vel=[0,0,0],hp=350,max_hp=350,aim=[0,0])
                    spawned+=1
                self.obs.update(t=i*.1,tick=i*2,mechs=[npc] if npc else [],events=pending)
                pending=[];gun=me['weapons'][0]
                if reload_left>0:
                    reload_left=max(0,reload_left-.1)
                    if reload_left==0:gun['ammo']=gun['stats']['mag']
                cooldown=max(0,cooldown-.1)
                gun['reload']=reload_left;gun['cooldown']=cooldown
                mf.draw.clear();action=self.bot.act(self.obs)
                if action.get('reload') and reload_left==0:
                    reload_left=gun['stats']['reload']
                if action['fire'][0] and npc:
                    damage=gun['stats']['damage']*self.bot.damage_scale(me['cubes'])
                    npc['hp']-=damage;gun['ammo']-=1;cooldown=gun['stats']['cooldown']
                    pending.append(dict(type='hit',target=npc['id'],amount=damage,weapon='gun'))
                    if npc['hp']<=0:
                        pending.append(dict(type='kill',target=npc['id']))
                        for j in range(2):self.obs['cubes'].append(dict(id=5000+defeated*2+j,pos=list(npc['pos'])))
                        defeated+=1;npc=None
                for k in (0,1):me['pos'][k]+=action['move'][k]*11.7*.1
                for k,rate in ((0,4),(1,3)):
                    delta=action['aim'][k]-me['aim'][k]
                    if k==0:delta=(delta+math.pi)%math.tau-math.pi
                    me['aim'][k]+=max(-rate*.1,min(rate*.1,delta))
                collected=[c for c in self.obs['cubes'] if math.dist(c['pos'],me['pos'])<=3.5]
                me['cubes']+=len(collected)
                self.obs['cubes']=[c for c in self.obs['cubes'] if c not in collected]
                if me['cubes']>=10 and self.bot.mode=='HIDE':break
        self.assertEqual(defeated,5)
        self.assertEqual(me['cubes'],10)
        self.assertEqual(self.bot.mode,'HIDE')

    def test_ground_hill_allowed_but_unreachable_roof_skipped(self):
        me=self.obs['self'];me['pos']=[0,0,0]
        self.bot.map.height=lambda x,y:0
        self.assertFalse(self.bot.reachable_surface([20,0,10],me))
        self.bot.map.height=lambda x,y:10
        self.assertTrue(self.bot.reachable_surface([20,0,10],me))

    def test_abandons_blocked_unproductive_target(self):
        self.obs['mechs']=[self.actor(101,'npc',350)]
        self.bot.map.ray_blocked=lambda a,b:True
        with self.nav_stub():
            for i in range(10):
                self.obs['t']=i;self.obs['tick']=i*20
                self.bot.act(self.obs)
        self.assertNotEqual(self.bot.active_target,101)
        self.assertIn(('HUNT',101),self.bot.ignored_until)

    def test_scan_when_no_targets(self):
        with self.nav_stub(): action=self.bot.act(self.obs)
        self.assertEqual(action['fire'],[False,False])
        self.assertEqual(self.bot.mode,'EXPLORE')
        self.assertIsNotNone(mf.draw.take())


if __name__=='__main__': unittest.main()
