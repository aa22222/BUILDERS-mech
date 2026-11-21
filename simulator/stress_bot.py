"""Worst-case tracked-actor decision timing; run separately from simulation batches."""
import argparse
import gzip
import importlib.util
import json
import math
from pathlib import Path
import sys
import time

root=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser()
p.add_argument('--bot',type=Path,default=(root/'submission/avoid_bot.py' if (root/'submission/avoid_bot.py').exists() else root/'avoid_bot.py'))
p.add_argument('--map-dir',type=Path,default=root/'arena')
p.add_argument('--stream',type=Path,default=root/'check/stream.jsonl.gz')
a=p.parse_args()
sys.path.insert(0,str(a.bot.resolve().parent))
spec=importlib.util.spec_from_file_location('stress_target',a.bot)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
with gzip.open(a.stream,'rt') as f:hello=json.loads(next(f));obs=json.loads(next(f))
hello['map']['dir']=str(a.map_dir.resolve());bot=m.Bot(hello)
x,y,z=obs['self']['pos']
obs['mechs']=[dict(id=i+1,kind='mech' if i<15 else 'npc',pos=[x+150*math.cos(i*math.tau/27),y+150*math.sin(i*math.tau/27),z],vel=[0,0,0],cubes=0) for i in range(27)]
obs['sounds']=[dict(kind='gun',bearing=i,dist='mid',age=0) for i in range(6)]
times=[]
for i in range(50):
    obs['t']=i*.1;obs['tick']=i*2
    start=time.perf_counter();action=bot.act(obs);times.append((time.perf_counter()-start)*1000)
    assert action['tick']==obs['tick'] and action['fire']==[False,False]
late=sum(t>50 for t in times)
print(json.dumps(dict(decisions=len(times),maximum_ms=round(max(times),2),mean_ms=round(sum(times)/len(times),2),over_50_ms=late),indent=2))
raise SystemExit(late/len(times)>.02)
