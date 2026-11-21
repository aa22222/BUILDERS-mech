"""Approximate local arena; not the authoritative Mechfight server."""
import argparse
import copy
import gzip
import importlib.util
import json
import math
from pathlib import Path
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'python'))
CURRENT_BOT = ROOT/'python/avoid_bot.py' if (ROOT/'python/avoid_bot.py').exists() else ROOT/'avoid_bot.py'
from baseline_bot import Bot as Geometry


def load_bot(path, hello):
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location('tested_bot', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Bot(copy.deepcopy(hello))


class Arena:
    def __init__(self, seed, count, scenario, bot_path):
        self.rng = random.Random(seed)
        with gzip.open(ROOT / 'check/stream.jsonl.gz', 'rt') as f:
            self.hello = json.loads(f.readline())
        self.hello.update(seed=seed, slot=0)
        self.hello['map']['dir'] = str(ROOT / 'arena')
        self.cfg = self.hello['config']
        self.geo = Geometry(self.hello)
        self.bot = load_bot(bot_path, self.hello)
        self.actors = []
        self.memory = {}
        self.damage = {}
        self.events = []
        self.late = 0
        self.decisions = 0
        self.errors = []
        self.idle = 0
        self.zone_time = 0
        self.last_action = {}
        self.phase_list = []
        center = self.cfg['zone']['start_center']
        radius = self.cfg['zone']['start_radius']
        start = 0
        for phase in self.cfg['zone']['phases']:
            angle = self.rng.random()*math.tau
            offset = (radius-phase['radius'])*self.rng.random()*.65
            next_center = [center[0]+offset*math.cos(angle), center[1]+offset*math.sin(angle)]
            end = start+phase['hold_s']+phase['shrink_s']
            self.phase_list.append((start, end, center, radius, next_center, phase))
            start, center, radius = end, next_center, phase['radius']
        for i in range(count):
            self.actors.append(self.spawn(i))
        if scenario == 'rooftop':
            for p in self.geo.world['prisms']:
                if p['kind'] != 'building':
                    continue
                ring = p['ring']
                x, y = sum(ring[::2])/len(ring[::2]), sum(ring[1::2])/len(ring[1::2])
                z = p['top']
                if z-self.geo.height(x, y) > 10 and self.valid(x, y, z):
                    self.actors[0]['pos'] = [x, y, z]
                    break
            else:
                raise RuntimeError('No suitable rooftop')
        if scenario == 'pursuit' and count > 1:
            x, y, z = self.actors[0]['pos']
            for i in range(24):
                a = i*math.tau/24
                px, py = x+65*math.cos(a), y+65*math.sin(a)
                pz = self.geo.height(px, py)
                if self.valid(px, py, pz):
                    self.actors[1]['pos'] = [px, py, pz]
                    break

    def valid(self, x, y, z):
        b = self.geo.world['bounds']
        r = self.cfg['mech']['radius']
        if not (b['minX']+r < x < b['maxX']-r and b['minY']+r < y < b['maxY']-r):
            return False
        return not any(self.geo.solid(x+r*math.cos(a), y+r*math.sin(a), z+.05, z+self.cfg['mech']['height'])
                       for a in [i*math.pi/4 for i in range(8)])

    def surface(self, x, y, feet):
        # Supports roofs and bridge decks; can also pass below bridges.
        ground = self.geo.height(x, y)
        from baseline_bot import inside
        for p in {id(p):p for dx in (-3,0,3) for dy in (-3,0,3) for p in self.geo.bins.get((math.floor((x+dx)/32), math.floor((y+dy)/32)), [])}.values():
            r=self.cfg['mech']['radius']
            overlap=any(inside(x+r*math.cos(a),y+r*math.sin(a),p['ring']) and not any(inside(x+r*math.cos(a),y+r*math.sin(a),h) for h in p.get('holes', [])) for a in [i*math.pi/4 for i in range(8)])
            if p['top'] <= feet+self.cfg['mech']['step_up'] and overlap:
                ground = max(ground, p['top'])
        return ground

    def spawn(self, ident):
        b = self.geo.world['bounds']
        for _ in range(20000):
            x = self.rng.uniform(b['minX']+10,b['maxX']-10)
            y = self.rng.uniform(b['minY']+10,b['maxY']-10)
            z = self.geo.height(x,y)
            if self.valid(x,y,z) and math.dist((x,y),self.cfg['zone']['start_center']) < self.cfg['zone']['start_radius']*.8 and all(math.dist((x,y),a['pos'][:2])>65 for a in self.actors):
                break
        else:
            raise RuntimeError('Could not find spawn')
        stats = copy.deepcopy(self.cfg['mech'])
        return dict(id=ident, kind='mech', pos=[x,y,z], vel=[0,0,0], aim=[0,0], hp=stats['hp'], max_hp=stats['hp'], energy=stats['energy'], max_energy=stats['energy'], grounded=True, cubes=0, upgrades=[], stats=stats, in_zone=True, weapons=[None,None], last_damage=-100, last_energy=-100, shot_at=-100)

    def zone(self,t):
        for start,end,c,r,n,p in self.phase_list:
            if t < end:
                break
        shrink_start=start+p['hold_s']
        f=max(0,min(1,(t-shrink_start)/p['shrink_s']))
        return dict(center=[c[i]+f*(n[i]-c[i]) for i in (0,1)],radius=r+f*(p['radius']-r),next_center=n,next_radius=p['radius'],shrink_start=shrink_start,shrink_end=end,dps=p['dps'])

    def visible(self, observer, target):
        d=math.dist(observer['pos'],target['pos'])
        vision=self.cfg['vision']
        bearing=math.atan2(target['pos'][1]-observer['pos'][1],target['pos'][0]-observer['pos'][0])
        delta=(bearing-observer['aim'][0]+math.pi)%math.tau-math.pi
        if d>vision['near_range'] and (d>vision['range'] or abs(delta)>math.radians(vision['fov_deg'])/2):
            return False
        return not self.geo.covered(target['pos'],observer,self.cfg['mech']['height'])

    def observation(self,t,zone):
        me=self.actors[0]
        for a in self.actors[1:]:
            if a['hp']>0 and self.visible(me,a):
                self.memory[a['id']]=t
        enemies=[]
        for a in self.actors[1:]:
            if a['hp']>0 and t-self.memory.get(a['id'],-100)<=self.cfg['vision'].get('memory_s',5):
                enemies.append(copy.deepcopy(a))
        result=dict(type='obs',tick=round(t*20),t=t,alive=sum(a['hp']>0 for a in self.actors),self=copy.deepcopy(me),mechs=enemies,zone=zone,offer=None,projectiles=[],crates=[],cubes=[],pickups=[],sounds=[],beams=[],drops=[],events=self.events)
        self.events=[]
        return result

    def move(self,a,action,dt,t):
        s=a['stats'];dx,dy=action.get('move',[0,0]);length=max(1,math.hypot(dx,dy));dx/=length;dy/=length
        boost=action.get('boost',False) and a['energy']>=s['boost_drain']*dt
        if boost:
            a['energy']-=s['boost_drain']*dt;a['last_energy']=t
        elif t-a['last_energy']>=s['energy_regen_delay']:
            a['energy']=min(a['max_energy'],a['energy']+s['energy_regen']*dt)
        speed=s['boost_speed'] if boost else s['walk_speed']
        for k,d in enumerate((dx,dy)):
            change=d*speed-a['vel'][k]
            a['vel'][k]+=max(-s['ground_accel']*dt,min(s['ground_accel']*dt,change))
        x,y,z=a['pos']
        for k in (0,1):
            pos=list(a['pos']);pos[k]+=a['vel'][k]*dt
            floor=self.surface(pos[0],pos[1],z)
            nz=max(floor,z)
            if floor-z <= s['step_up'] and self.valid(pos[0],pos[1],nz):
                a['pos'][k]=pos[k]
            else:
                a['vel'][k]=0
        floor=self.surface(*a['pos'][:2],z)
        if z>floor+.05:
            a['vel'][2]-=s['gravity']*dt
            a['pos'][2]=max(floor,z+a['vel'][2]*dt)
        else:
            a['pos'][2]=floor;a['vel'][2]=0
        a['grounded']=a['pos'][2]<=floor+.05
        desired=action.get('aim',a['aim'])[0]
        delta=(desired-a['aim'][0]+math.pi)%math.tau-math.pi
        a['aim'][0]+=max(-s['turn_rate']*dt,min(s['turn_rate']*dt,delta))

    def hurt(self,a,amount,weapon,t,attacker=None):
        a['hp']-=amount;a['last_damage']=t
        if a['id']==0:
            self.damage[weapon]=self.damage.get(weapon,0)+amount
            bearing=None if attacker is None else math.atan2(attacker['pos'][1]-a['pos'][1],attacker['pos'][0]-a['pos'][0])
            self.events.append(dict(type='damaged',amount=amount,weapon=weapon,bearing=bearing,by=None if attacker is None else attacker['id']))

    def run(self,seconds,out):
        out.mkdir(parents=True,exist_ok=True)
        dead=[];dt=.1
        with (out/'trace.jsonl').open('w') as trace:
            for tick in range(math.ceil(seconds/dt)):
                t=round(tick*dt,3);zone=self.zone(t);me=self.actors[0]
                obs=self.observation(t,zone)
                before=time.perf_counter()
                try:
                    action=self.bot.act(obs)
                except Exception as exc:
                    self.errors.append(str(exc));action={}
                elapsed=(time.perf_counter()-before)*1000
                self.decisions+=1;self.late+=elapsed>50
                # Report timing, but apply late actions for deterministic geometry tests.
                if math.hypot(*action.get('move',[0,0]))<.01:self.idle+=1
                actions={0:action}
                targets={}
                for a in self.actors[1:]:
                    if a['hp']<=0:continue
                    seen=[e for e in self.actors if e['id']!=a['id'] and e['hp']>0 and self.visible(a,e)]
                    target=min(seen,key=lambda e:math.dist(e['pos'],a['pos'])) if seen else None
                    goal=target['pos'] if target else zone['next_center']
                    angle=math.atan2(goal[1]-a['pos'][1],goal[0]-a['pos'][0])
                    if target:targets[a['id']]=target
                    actions[a['id']]=dict(move=[math.cos(angle),math.sin(angle)],aim=[angle if target else a['aim'][0]+.25,0],boost=False)
                alive_before=[a for a in self.actors if a['hp']>0]
                for a in alive_before:
                    self.move(a,actions.get(a['id'],{}),dt,t)
                    a['in_zone']=math.dist(a['pos'][:2],zone['center'])<=zone['radius']
                    if not a['in_zone']:
                        self.hurt(a,zone['dps']*dt,'zone',t)
                        if a['id']==0:self.zone_time+=dt
                    elif t-a['last_damage']>=a['stats']['regen_delay']:
                        a['hp']=min(a['max_hp'],a['hp']+a['stats']['regen_per_s']*dt)
                # Simplified gun: instant probabilistic hit, no ammo/projectile physics.
                gun=self.cfg['weapons']['gun']
                for a in alive_before:
                    target=targets.get(a['id'])
                    if target and t-a['shot_at']>=gun['cooldown'] and math.dist(a['pos'],target['pos'])<gun['range'] and self.visible(a,target):
                        a['shot_at']=t;a['last_damage']=t
                        if self.rng.random()<.55:
                            self.hurt(target,gun['damage'],'gun',t,a)
                deaths=[a for a in alive_before if a['hp']<=0]
                for a in deaths:
                    dead.append(dict(id=a['id'],t=t,pos=list(a['pos']),place=len(alive_before)))
                if tick%10==0 or me['hp']<=0:
                    trace.write(json.dumps(dict(t=t,actors=[dict(id=a['id'],pos=a['pos'],hp=a['hp']) for a in self.actors],zone=zone,action=action,diagnostic=getattr(self.bot,'diagnostic',{}),energy=me['energy'],velocity=me['vel'],decision_ms=elapsed,damage=self.damage,events=self.events))+'\n')
                if me['hp']<=0 or sum(a['hp']>0 for a in self.actors)==1 and len(self.actors)>1:break
        result=dict(approximate=True,elapsed_s=t,bot_alive=me['hp']>0,bot_hp=me['hp'],bot_position=me['pos'],damage=self.damage,deaths=dead,idle_decisions=self.idle,decisions=self.decisions,over_budget=self.late,zone_seconds=round(self.zone_time,1),errors=self.errors[:10])
        (out/'summary.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result,indent=2))
        return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--seed',type=int,default=1)
    p.add_argument('--bots',type=int,default=16,choices=range(1,17))
    p.add_argument('--seconds',type=float,default=120)
    p.add_argument('--scenario',choices=['random','rooftop','pursuit'],default='random')
    p.add_argument('--bot',type=Path,default=CURRENT_BOT)
    p.add_argument('--out',type=Path,default=ROOT/'simulator/results')
    a=p.parse_args()
    if a.seconds<=0:p.error('--seconds must be positive')
    Arena(a.seed,a.bots,a.scenario,a.bot.resolve()).run(a.seconds,a.out)

if __name__=='__main__':main()
