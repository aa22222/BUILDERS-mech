"""Map-aware passive survivor with bounded planning and one-second steering."""
import array
import heapq
import json
import math
from pathlib import Path
import sys
import time
import mechfight as mf

TAU = math.tau


def inside(x, y, ring):
    result = False
    ax, ay = ring[-2:]
    for i in range(0, len(ring), 2):
        bx, by = ring[i:i+2]
        if (ay > y) != (by > y) and x < (bx-ax)*(y-ay)/(by-ay)+ax:
            result = not result
        ax, ay = bx, by
    return result


def segment_distance(x, y, ax, ay, bx, by):
    dx, dy = bx-ax, by-ay
    f = max(0, min(1, ((x-ax)*dx+(y-ay)*dy)/max(1e-9, dx*dx+dy*dy)))
    return math.hypot(x-ax-f*dx, y-ay-f*dy)


class World:
    def __init__(self, hello):
        root = Path(hello['map']['dir'])
        name = next((n for n in hello['map']['files'] if n.endswith('world.json')), 'v2/world.json')
        path = root/name
        self.world = json.loads(path.read_text(encoding='utf-8'))
        self.grid = self.world['terrain']
        self.terrain = array.array('h')
        self.terrain.frombytes((path.parent/self.grid['file']).read_bytes())
        if sys.byteorder != 'little':
            self.terrain.byteswap()
        if len(self.terrain) != self.grid['nx']*self.grid['ny']:
            raise ValueError('Invalid terrain grid length')
        self.bins = {}
        for ident, p in enumerate(self.world['prisms']):
            p['_id'] = ident
            rings = [p['ring']]+p.get('holes', [])
            p['_edges'] = [(r[i-2], r[i-1], r[i], r[i+1]) for r in rings for i in range(0,len(r),2)]
            p['_bounds'] = (min(p['ring'][::2]), min(p['ring'][1::2]), max(p['ring'][::2]), max(p['ring'][1::2]))
            a,b,c,d = p['_bounds']
            for ix in range(math.floor(a/32), math.floor(c/32)+1):
                for iy in range(math.floor(b/32), math.floor(d/32)+1):
                    self.bins.setdefault((ix,iy), []).append(p)

    def height(self, x, y):
        t = self.grid
        u = max(0,min(t['nx']-1.000001,(x-t['minX'])/t['step']))
        v = max(0,min(t['ny']-1.000001,(y-t['minY'])/t['step']))
        i,j = int(u),int(v); a,b=u-i,v-j; k=j*t['nx']+i; h=self.terrain
        return ((h[k]*(1-a)+h[k+1]*a)*(1-b)+(h[k+t['nx']]*(1-a)+h[k+t['nx']+1]*a)*b)*t.get('scale',.01)

    @staticmethod
    def contains(p,x,y):
        return inside(x,y,p['ring']) and not any(inside(x,y,h) for h in p.get('holes',[]))

    def nearby(self,x,y,r=0):
        seen=set()
        for ix in range(math.floor((x-r)/32),math.floor((x+r)/32)+1):
            for iy in range(math.floor((y-r)/32),math.floor((y+r)/32)+1):
                for p in self.bins.get((ix,iy),[]):
                    if p['_id'] not in seen:
                        seen.add(p['_id']);yield p

    def surface(self,x,y,feet,step=1.2,radius=0):
        floor=self.height(x,y)
        for p in self.nearby(x,y,radius):
            overlaps=self.contains(p,x,y) or (radius>0 and any(segment_distance(x,y,*e)<radius for e in p['_edges']))
            if p['top']<=feet+step and overlaps:
                floor=max(floor,p['top'])
        return floor

    def clear(self,x,y,z,r,h):
        b=self.world['bounds']
        if not (b['minX']+r+.1<x<b['maxX']-r-.1 and b['minY']+r+.1<y<b['maxY']-r-.1):return False
        for p in self.nearby(x,y,r):
            if p['top']<=z+.08 or p['base']>=z+h:continue
            if self.contains(p,x,y) or any(segment_distance(x,y,*edge)<r for edge in p['_edges']):return False
        return True

    def ray_blocked(self,a,b):
        # Exact footprint intersections and vertical slabs; terrain is sampled.
        dx,dy,dz=[b[i]-a[i] for i in range(3)]
        distance=math.hypot(dx,dy)
        seen=set()
        for i in range(max(1,math.ceil(distance/16))+1):
            f=i/max(1,math.ceil(distance/16))
            for p in self.nearby(a[0]+dx*f,a[1]+dy*f,16):
                if p['_id'] in seen:continue
                seen.add(p['_id'])
                if max(a[2],b[2])<p['base'] or min(a[2],b[2])>p['top']:continue
                cuts=[0.,1.]
                for ax,ay,bx,by in p['_edges']:
                    ex,ey=bx-ax,by-ay
                    cross=dx*ey-dy*ex
                    if abs(cross)<1e-9:continue
                    t=((ax-a[0])*ey-(ay-a[1])*ex)/cross
                    u=((ax-a[0])*dy-(ay-a[1])*dx)/cross
                    if 0<t<1 and 0<=u<=1:cuts.append(t)
                cuts.sort()
                for lo,hi in zip(cuts,cuts[1:]):
                    mid=(lo+hi)/2
                    if self.contains(p,a[0]+dx*mid,a[1]+dy*mid):
                        zlo,zhi=sorted((a[2]+dz*lo,a[2]+dz*hi))
                        if zhi>p['base']+.02 and zlo<p['top']-.02:return True
        steps=max(1,math.ceil(distance/5))
        for i in range(1,steps):
            f=i/steps
            if self.height(a[0]+dx*f,a[1]+dy*f)>a[2]+dz*f:return True
        return False


class Bot:
    name='quiet-border-v2'

    def __init__(self,hello):
        self.config=hello['config'];self.map=World(hello)
        self.memory={};self.last_t=None;self.last_pos=None;self.stuck=0
        self.route=[];self.goal=None;self.search=None;self.refuge_search=None;self.last_plan=-100
        self.previous=(0,0);self.wants_move=False;self.last_recovery=-100;self.sprinting=False;self.damage_until=-100;self.damage_bearing=0
        self.visibility_cache={};self.scanning=True;self.scan_remaining=TAU;self.next_scan=0;self.last_yaw=None
        self.nav={};self.edges={};self.nav_step=8
        s=self.config['mech'];r=s.get('radius',2.5)+.4;h=s.get('height',9)
        self.nav_radius=r;self.nav_height=h;self.node_valid={}
        b=self.map.world['bounds']
        # Startup preprocessing is outside the per-observation budget.
        for ix in range(math.ceil((b['minX']+r)/8),math.floor((b['maxX']-r)/8)+1):
            for iy in range(math.ceil((b['minY']+r)/8),math.floor((b['maxY']-r)/8)+1):
                x,y=ix*8,iy*8;z=self.map.height(x,y)
                if self.map.clear(x,y,z,r,h):
                    self.nav[(ix,iy)]=(x,y,z);self.node_valid[(ix,iy)]=True
        self.fallback_seed=hello.get('seed',0)%24

    def covered(self,point,enemy,height):
        scale=1+self.config.get('cubes',{}).get('size_per_cube',.05)*enemy.get('cubes',0)
        eye=3.5 if enemy.get('kind')=='npc' else self.config['mech'].get('eye_height',8)*scale
        e=enemy['pos'];origin=(e[0],e[1],e[2]+eye)
        return all(self.map.ray_blocked(origin,(point[0],point[1],point[2]+dz)) for dz in (height,height*.5))

    def risk(self,point,robots,height,deadline):
        score=0
        for enemy in robots:
            d=math.dist(point[:2],enemy['pos'][:2])
            if d>330:continue
            key=(round(point[0],2),round(point[1],2),round(point[2],2),enemy['id'])
            cover=self.visibility_cache.get(key)
            if cover is None:
                # Unknown visibility stays dangerous if the work budget is exhausted.
                cover=False
                if time.perf_counter()<deadline:
                    cover=self.covered(point,enemy,height);self.visibility_cache[key]=cover
            weight=enemy.get('_weight',1)
            score+=weight*((0 if cover else 100+6000/(d+30))+3500/(d+25)+max(0,70-d)*3)
        return score

    @staticmethod
    def forecast(zone,now,seconds):
        start=max(now,zone['shrink_start']);remaining=zone['shrink_end']-start
        f=max(0,min(1,(now+seconds-start)/max(.001,remaining)))
        return ([zone['center'][i]+f*(zone['next_center'][i]-zone['center'][i]) for i in (0,1)],zone['radius']+f*(zone['next_radius']-zone['radius']))

    def nearest_node(self,point):
        ix,iy=round(point[0]/8),round(point[1]/8)
        for ring in range(6):
            nodes=[(ix+dx,iy+dy) for dx in range(-ring,ring+1) for dy in range(-ring,ring+1)
                   if max(abs(dx),abs(dy))==ring and (ix+dx,iy+dy) in self.nav]
            for n in sorted(nodes,key=lambda n:math.dist(self.nav[n][:2],point[:2])):
                if n not in self.node_valid:self.node_valid[n]=self.map.clear(*self.nav[n],self.nav_radius,self.nav_height)
                if self.node_valid[n]:return n
        return None

    def neighbors(self,node):
        if node in self.edges:return self.edges[node]
        result=[];a=self.nav[node];s=self.config['mech']
        for dx,dy in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(-1,1),(1,-1),(-1,-1)):
            n=(node[0]+dx,node[1]+dy)
            if n not in self.nav:continue
            b=self.nav[n];valid=True;old=a[2]
            for i in range(1,5):
                x,y=a[0]+(b[0]-a[0])*i/4,a[1]+(b[1]-a[1])*i/4;z=self.map.height(x,y)
                if z-old>s.get('step_up',1.2) or not self.map.clear(x,y,z,self.nav_radius,self.nav_height):
                    valid=False;break
                old=z
            if valid:result.append(n)
        self.edges[node]=result
        return result

    def plan(self,pos,center,radius,robots,height,now,deadline):
        # Both refuge evaluation and A* continue across observations. A CPU
        # cutoff must not turn a partially evaluated refuge list into a choice.
        if self.search:
            heap,cost,parent,target=self.search
            while heap and time.perf_counter()<deadline:
                _,node=heapq.heappop(heap)
                if node==target:
                    route=[]
                    while node in parent:route.append(self.nav[node]);node=parent[node]
                    self.route=list(reversed(route));self.search=None;return
                for n in self.neighbors(node):
                    threat_cost=sum(max(0,90-math.dist(self.nav[n][:2],e['pos'][:2]))*.08 for e in robots[:6])
                    new=cost[node]+math.dist(self.nav[node],self.nav[n])+threat_cost
                    if new<cost.get(n,float('inf')):
                        cost[n]=new;parent[n]=node
                        heapq.heappush(heap,(new+math.dist(self.nav[n],self.nav[target]),n))
            if not heap:self.search=None;self.goal=None
            return
        if self.refuge_search is None:
            if now-self.last_plan<3 and self.goal is not None and math.dist(pos[:2],self.goal[:2])>8:return
            self.last_plan=now
            current_risk=self.risk(pos,robots,height,deadline)
            if robots and current_risk<25 and min(math.dist(pos,e['pos']) for e in robots)>130 and now>self.damage_until and math.dist(pos[:2],center)<radius-20 and self.stuck<1:
                self.goal=None;self.route=[];return
            candidates=[]
            for p in sorted(self.map.world['prisms'],key=lambda p:(p['_bounds'][0]-pos[0])**2+(p['_bounds'][1]-pos[1])**2)[:25]:
                a,b,c,d=p['_bounds']
                for x,y in ((a-8,b-8),(a-8,d+8),(c+8,b-8),(c+8,d+8),((a+c)/2,b-8),((a+c)/2,d+8)):
                    n=self.nearest_node((x,y))
                    if n is not None:candidates.append(n)
            angle=math.atan2(pos[1]-center[1],pos[0]-center[0])
            target_r=max(0,radius-min(35,radius*.35))
            for k in range(12):
                a=angle+k*TAU/12
                n=self.nearest_node((center[0]+target_r*math.cos(a),center[1]+target_r*math.sin(a)))
                if n is not None:candidates.append(n)
            n=self.nearest_node(center)
            if n is not None:candidates.append(n)
            candidates=sorted(set(candidates),key=lambda n:math.dist(pos,self.nav[n]))
            candidates=[n for n in candidates if math.dist(pos,self.nav[n])>=6 and math.dist(self.nav[n][:2],center)<max(1,radius-12)]
            self.refuge_search=dict(nodes=candidates,index=0,enemy_index=0,risk=0,best=None,score=float('inf'),pos=tuple(pos),robots=robots,center=center,target_r=target_r)
        state=self.refuge_search
        while state['index']<len(state['nodes']):
            if time.perf_counter()>=deadline:return
            n=state['nodes'][state['index']];q=self.nav[n]
            while state['enemy_index']<len(state['robots']):
                if time.perf_counter()>=deadline:return
                e=state['robots'][state['enemy_index']];d=math.dist(q[:2],e['pos'][:2])
                if d<=330:
                    cover=self.covered(q,e,height)
                    state['risk']+=e.get('_weight',1)*((0 if cover else 100+6000/(d+30))+3500/(d+25)+max(0,70-d)*3)
                state['enemy_index']+=1
            score=math.dist(state['pos'],q)*.7+state['risk']*2
            if not state['robots']:score+=abs(math.dist(q[:2],state['center'])-state['target_r'])*.35
            if score<state['score']:state['score']=score;state['best']=n
            state['index']+=1;state['enemy_index']=0;state['risk']=0
        best=state['best'];self.refuge_search=None
        if best is None:
            if self.goal is not None and math.dist(self.goal[:2],center)<radius:return
            best=self.nearest_node(center)
        if best is None:return
        self.goal=self.nav[best]
        start=self.nearest_node(pos)
        if start is not None:self.search=([(0,start)],{start:0},{},best)

    def trajectory(self,me,direction,speed,stats):
        pos=list(me['pos']);vel=list(me['vel']);points=[]
        radius=stats.get('radius',2.5);height=stats.get('height',9)
        # Exactly one second, including inertia, falling, and partial wall slides.
        for i in range(10):
            dt=.1;accel=stats.get('ground_accel',58.5) if me['grounded'] else stats.get('air_accel',12)
            for k in (0,1):vel[k]+=max(-accel*dt,min(accel*dt,direction[k]*speed-vel[k]))
            candidate=[pos[0]+vel[0]*dt,pos[1]+vel[1]*dt,pos[2]]
            floor=self.map.surface(candidate[0],candidate[1],pos[2],stats.get('step_up',1.2),radius)
            if floor-pos[2]>stats.get('step_up',1.2):break
            if floor<pos[2]-.1:vel[2]-=stats.get('gravity',22)*dt
            else:vel[2]=0
            candidate[2]=max(floor,pos[2]+vel[2]*dt)
            if not self.map.clear(*candidate,radius,height):break
            pos=candidate;points.append(tuple(pos))
        return points

    def act(self,obs):
        started=time.perf_counter();deadline=started+.032
        me=obs['self'];now=obs['t'];pos=me['pos'];zone=obs['zone']
        stats={**self.config['mech'],**me['stats']};height=stats.get('height',9);radius=stats.get('radius',2.5)
        if abs(self.nav_radius-radius-.4)>.01 or abs(self.nav_height-height)>.01:
            self.nav_radius=radius+.4;self.nav_height=height;self.node_valid.clear();self.edges.clear();self.route=[];self.search=None;self.refuge_search=None;self.goal=None
        dt=.1 if self.last_t is None else max(.01,min(1,now-self.last_t))
        if self.last_pos is not None and self.wants_move:
            self.stuck=self.stuck+dt if math.dist(pos,self.last_pos)<.15 else max(0,self.stuck-dt*2)
        else:self.stuck=0
        self.last_t=now;self.last_pos=list(pos)
        for enemy in obs['mechs']:self.memory[enemy['id']]=(dict(enemy),now)
        self.memory={i:v for i,v in self.memory.items() if now-v[1]<12}
        robots=[]
        for enemy,seen in self.memory.values():
            e=dict(enemy);age=now-seen;e['pos']=[enemy['pos'][k]+enemy.get('vel',[0,0,0])[k]*min(age,.75) for k in range(3)];e['_weight']=max(.3,1-age/15);robots.append(e)
        for event in obs['events']:
            if event['type']=='damaged' and event.get('bearing') is not None:
                self.damage_until=now+2;self.damage_bearing=event['bearing']
                if not any(e['id']==event.get('by') for e in robots):
                    a=event['bearing'];robots.append(dict(id=-100,kind='mech',pos=[pos[0]+50*math.cos(a),pos[1]+50*math.sin(a),pos[2]],_weight=.7))
        for i,sound in enumerate(obs['sounds'][:6]):
            if sound['kind'] in ('drop','death','crate'):continue
            d={'near':40,'mid':110,'far':230}[sound['dist']];a=sound['bearing']
            robots.append(dict(id=-200-i,kind='mech',pos=[pos[0]+d*math.cos(a),pos[1]+d*math.sin(a),pos[2]],_weight=.2))
        robots.sort(key=lambda e:math.dist(pos,e['pos']))
        # Invalidate each observation: even a stationary bot may have moving enemies.
        self.visibility_cache={}
        center,future_r=self.forecast(zone,now,18)
        margin=min(radius+14,max(0,future_r*.3));safe_r=max(0,future_r-margin)
        urgent=math.dist(pos[:2],center)>safe_r
        current_risk=self.risk(pos,robots,height,started+.007)
        if self.stuck>1.2 and now-self.last_recovery>2:
            self.route=[];self.goal=None;self.search=None;self.refuge_search=None;self.last_plan=-100;self.last_recovery=now
        self.plan(pos,center,safe_r,robots,height,now,started+.012)
        if self.route:
            nearest=min(range(len(self.route)),key=lambda i:math.dist(pos[:2],self.route[i][:2]))
            if math.dist(pos[:2],self.route[nearest][:2])<12:self.route=self.route[nearest:]
        while self.route and math.dist(pos[:2],self.route[0][:2])<6:self.route.pop(0)
        waypoint=self.route[0] if self.route else self.goal
        if waypoint is None:waypoint=(center[0],center[1],pos[2]) if urgent else pos
        # Hysteresis gives energy time to regenerate instead of flickering at 25%.
        need_boost=urgent or current_risk>80
        if self.sprinting and (me['energy']<18 or not need_boost):self.sprinting=False
        elif not self.sprinting and need_boost and me['energy']>65:self.sprinting=True
        boost=self.sprinting and me['grounded']
        speed=stats['boost_speed'] if boost else stats['walk_speed']
        # Follow a reachable point farther down the route rather than braking
        # for every 8 m grid vertex. The steering horizon remains one second.
        for q in self.route[:4]:
            d=math.dist(pos[:2],q[:2])
            if d>speed+3 or d<1:continue
            direction=((q[0]-pos[0])/d,(q[1]-pos[1])/d)
            probe=self.trajectory(me,direction,min(speed,d),stats)
            if len(probe)==10 and math.dist(probe[-1][:2],q[:2])<3:waypoint=q
            else:break
        angle=math.atan2(waypoint[1]-pos[1],waypoint[0]-pos[0])
        directions=[(math.cos(angle),math.sin(angle)),(0,0)]
        directions += [(math.cos(angle+k*TAU/16),math.sin(angle+k*TAU/16)) for k in range(1,16)]
        directions += [(directions[0][0]*.35,directions[0][1]*.35)]
        if self.stuck>1:
            directions = [(d[0]*.35,d[1]*.35) for d in directions[:17]]+directions
        best=float('inf');chosen=(0,0);chosen_points=[]
        bounds=self.map.world['bounds']
        for direction in directions:
            if time.perf_counter()>deadline:break
            points=self.trajectory(me,direction,speed,stats)
            if not points:continue
            q=points[-1];progress=math.dist(pos[:2],q[:2])
            # Do not reject a useful short step because the full path ends at a wall.
            shortfall=(10-len(points))*2
            zone_penalty=max(0,math.dist(q[:2],zone['center'])-max(0,zone['radius']-radius-2))*90
            zone_penalty+=max(0,math.dist(q[:2],center)-safe_r)*8
            edge=min(q[0]-bounds['minX'],bounds['maxX']-q[0],q[1]-bounds['minY'],bounds['maxY']-q[1])
            edge_penalty=max(0,25-edge)*2
            risk=self.risk(q,robots,height,deadline)
            # Check the route midpoint too, not just its destination.
            if robots:risk=.7*risk+.3*self.risk(points[len(points)//2],robots,height,deadline)
            route_cost=math.dist(q[:2],waypoint[:2])*7
            if current_risk>80 and progress<.2:route_cost+=45
            score=zone_penalty+edge_penalty+risk+route_cost+shortfall
            score-=2*(direction[0]*self.previous[0]+direction[1]*self.previous[1])
            if current_risk<25 and not urgent and now>self.damage_until and robots and direction==(0,0):score-=15
            if self.stuck>1:score-=progress*3
            if score<best:best=score;chosen=direction;chosen_points=points
        # Shorten commands that would drive into a wall before the next decision.
        if chosen_points and len(chosen_points)<3:chosen=(chosen[0]*.4,chosen[1]*.4);boost=False
        self.previous=chosen
        self.wants_move=urgent or current_risk>40 or math.dist(pos[:2],waypoint[:2])>12
        self.diagnostic=dict(risk=round(current_risk,1),goal=self.goal,waypoint=waypoint,route_nodes=len(self.route),searching=self.search is not None or self.refuge_search is not None,stuck=round(self.stuck,2))
        # Finish a full measured sweep, rather than resetting the scan every
        # time a nearby threat pulls the torso back toward it.
        actual=me['aim'][0]
        if self.scanning and self.last_yaw is not None:
            turned=abs((actual-self.last_yaw+math.pi)%TAU-math.pi)
            self.scan_remaining-=turned
            if self.scan_remaining<=.05:
                self.scanning=False;self.next_scan=now+2.5
        if not self.scanning and now>=self.next_scan:
            self.scanning=True;self.scan_remaining=TAU
        self.last_yaw=actual
        yaw=actual
        if self.scanning:
            yaw=actual+min(.32,stats.get('turn_rate',4)*dt*.8)
        elif now<self.damage_until:
            yaw=self.damage_bearing
        elif robots:
            e=robots[0];yaw=math.atan2(e['pos'][1]-pos[1],e['pos'][0]-pos[0])
        action=dict(tick=obs['tick'],move=list(chosen),boost=bool(boost and math.hypot(*chosen)>.1),aim=[yaw,0],fire=[False,False])
        if obs.get('offer'):
            priorities=['speed','energy','regen','armor','sensors','health'];choices=obs['offer']['choices']
            action['pick']=min(range(len(choices)),key=lambda i:next((j for j,k in enumerate(priorities) if k in choices[i]['id']),99))
        return action


if __name__=='__main__':
    mf.run(Bot)
