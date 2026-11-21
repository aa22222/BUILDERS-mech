"""Passive map-aware survivor. Standard library only; run via mechfight wrapper."""
import array
import json
import math
from pathlib import Path
import sys
import mechfight as mf


def inside(x, y, ring):
    result = False
    ax, ay = ring[-2:]
    for i in range(0, len(ring), 2):
        bx, by = ring[i:i+2]
        if (ay > y) != (by > y) and x < (bx-ax)*(y-ay)/(by-ay)+ax:
            result = not result
        ax, ay = bx, by
    return result


class Bot:
    name = 'quiet-border'

    def __init__(self, hello):
        self.config = hello['config']
        root = Path(hello['map']['dir']) / 'v2'
        self.world = json.loads((root / 'world.json').read_text())
        self.terrain = array.array('h')
        self.terrain.frombytes((root / 'terrain.i16').read_bytes())
        if sys.byteorder != 'little':
            self.terrain.byteswap()
        self.bins = {}
        for p in self.world['prisms']:
            r = p['ring']
            for ix in range(math.floor(min(r[::2])/32), math.floor(max(r[::2])/32)+1):
                for iy in range(math.floor(min(r[1::2])/32), math.floor(max(r[1::2])/32)+1):
                    self.bins.setdefault((ix, iy), []).append(p)
        self.memory = {}
        self.previous = (0, 0)

    def height(self, x, y):
        t = self.world['terrain']
        u = max(0, min(t['nx']-1.000001, (x-t['minX'])/t['step']))
        v = max(0, min(t['ny']-1.000001, (y-t['minY'])/t['step']))
        i, j = int(u), int(v)
        a, b = u-i, v-j
        k = j*t['nx']+i
        h = self.terrain
        return ((h[k]*(1-a)+h[k+1]*a)*(1-b)+(h[k+t['nx']]*(1-a)+h[k+t['nx']+1]*a)*b)*t.get('scale', .01)

    def solid(self, x, y, low, high):
        return any(p['top'] > low and p['base'] < high and inside(x, y, p['ring'])
                   and not any(inside(x, y, h) for h in p.get('holes', []))
                   for p in self.bins.get((math.floor(x/32), math.floor(y/32)), []))

    def clear(self, x, y, radius, height):
        b = self.world['bounds']
        if not (b['minX']+radius < x < b['maxX']-radius and b['minY']+radius < y < b['maxY']-radius):
            return False
        z = self.height(x, y)
        return not any(self.solid(x+radius*math.cos(a), y+radius*math.sin(a), z+0.1, z+height)
                       for a in [i*math.pi/4 for i in range(8)]) and not self.solid(x, y, z+.1, z+height)

    def covered(self, point, enemy, height):
        # Both center and top must be occluded from the observer's eyes.
        # Ignore facing: a robot can turn toward us at any moment.
        position = enemy['pos']
        scale = 1 + self.config.get('cubes', {}).get('size_per_cube', .05)*enemy.get('cubes', 0)
        eye = (3.5 if enemy.get('kind') == 'npc' else self.config['mech'].get('eye_height', 8)*scale)
        steps = max(2, math.ceil(math.dist(point[:2], position[:2])/3))
        for target_height in (height*.5, height):
            blocked = False
            for i in range(1, steps):
                f = i/steps
                x, y = (point[k]+f*(position[k]-point[k]) for k in (0, 1))
                z = point[2]+target_height+f*(position[2]+eye-point[2]-target_height)
                if self.solid(x, y, z, z+.01) or self.height(x, y) > z:
                    blocked = True
                    break
            if not blocked:
                return False
        return True

    def act(self, obs):
        me, zone, now = obs['self'], obs['zone'], obs['t']
        x, y, z = me['pos']
        stats = {**self.config['mech'], **me['stats']}
        radius = stats.get('radius', 2.5)
        height = stats.get('height', 9)
        speed = stats['walk_speed']
        for e in obs['mechs']:
            self.memory[e['id']] = (dict(e), now)
        self.memory = {k: v for k, v in self.memory.items() if now-v[1] < 10}
        robots = [e for e, t in self.memory.values()]
        threats = [e['pos'] for e in robots]
        for s in obs['sounds']:
            if s['kind'] in ('drop', 'death', 'crate'):
                continue
            d = {'near': 40, 'mid': 110, 'far': 230}[s['dist']]
            threats.append([x+d*math.cos(s['bearing']), y+d*math.sin(s['bearing']), z])
        for e in obs['events']:
            if e['type'] == 'damaged' and e.get('bearing') is not None:
                a = e['bearing']
                threats.append([x+40*math.cos(a), y+40*math.sin(a), z])
        threats.sort(key=lambda p: math.dist(p[:2], (x, y)))
        # Predict 12 seconds ahead using the remaining shrink interval.
        start = max(now, zone['shrink_start'])
        f = max(0, min(1, (now+12-start)/max(.001, zone['shrink_end']-start)))
        center = [zone['center'][i]+f*(zone['next_center'][i]-zone['center'][i]) for i in (0, 1)]
        r = zone['radius']+f*(zone['next_radius']-zone['radius'])
        margin = radius+max(8, speed*1.5)
        target_r = max(0, r-margin)
        urgent = math.dist((x, y), center) > target_r+4
        exposed = any(not self.covered((x, y, z), e, height) for e in robots)
        boost = (urgent or exposed) and me['energy'] > me['max_energy']*.25 and me['grounded']
        travel = stats['boost_speed'] if boost else speed
        best, direction = None, (0, 0)
        for i in range(25):
            dx, dy = (0, 0) if i == 24 else (math.cos(i*math.tau/24), math.sin(i*math.tau/24))
            px, py, oldz = x, y, self.height(x, y)
            valid = True
            # Sample a one-second path, including cylinder clearance and slope.
            steps = max(1, math.ceil(travel))
            for j in range(1, steps+1):
                px, py = x+dx*travel*j/steps, y+dy*travel*j/steps
                nz = self.height(px, py)
                if not self.clear(px, py, radius+.5, height) or nz-oldz > max(stats.get('step_up', 1.2), math.tan(math.radians(stats.get('max_slope_deg', 50)))):
                    valid = False
                    break
                oldz = nz
            if not valid:
                continue
            dist = math.dist((px, py), center)
            score = abs(dist-target_r)*.7 + max(0, dist-target_r)*12
            score += max(0, math.dist((px, py), zone['center'])-zone['radius']+radius+3)*100
            for enemy in threats:
                d = math.dist((px, py), enemy[:2])
                score += 16000/(d+12)
            score -= 2*(dx*self.previous[0]+dy*self.previous[1])
            if not threats and abs(dist-target_r) < 8 and i == 24:
                score -= 12
            exposure = sum(not self.covered((px, py, oldz), e, height) for e in robots)
            # Safety first, then hide from ALL known robots. Border proximity
            # and distance are tie-breakers; do not abandon safe cover for them.
            danger = max(0, dist-target_r) if urgent else max(0, dist-r+radius+3)
            outside = max(0, math.dist((px, py), zone['center'])-zone['radius']+radius+3)
            hold_cover = not exposed and not urgent and bool(robots)
            rank = (outside, danger, exposure,
                    0 if hold_cover and i == 24 else 1, score + (100 if exposed and i == 24 else 0))
            if best is None or rank < best:
                best, direction = rank, (dx, dy)
        self.previous = direction
        # Face immediate danger for front armor; otherwise sweep using actual aim.
        yaw = me['aim'][0]+.3
        if threats and math.dist(threats[0][:2], (x, y)) < 70:
            yaw = math.atan2(threats[0][1]-y, threats[0][0]-x)
        action = {'tick': obs['tick'], 'move': list(direction), 'boost': bool(boost and direction != (0, 0)), 'aim': [yaw, 0], 'fire': [False, False]}
        if obs.get('offer'):
            priority = ['speed', 'energy', 'regen', 'armor', 'sensors', 'health']
            choices = obs['offer']['choices']
            action['pick'] = min(range(len(choices)), key=lambda i: next((j for j, p in enumerate(priority) if p in choices[i]['id']), 99))
        return action


if __name__ == '__main__':
    mf.run(Bot)
