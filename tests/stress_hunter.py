"""Crowded-observation timing for the hunter, including loot and combat selection."""
import argparse
import gzip
import json
import math
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser()
p.add_argument('--bot-dir',type=Path,default=ROOT/'python' if (ROOT/'python').exists() else ROOT)
a=p.parse_args()
sys.path.insert(0,str(a.bot_dir))
from hunter_bot import Bot
import mechfight as mf
with gzip.open(ROOT/'check/stream.jsonl.gz','rt') as f:
    hello=json.loads(next(f));obs=json.loads(next(f))
hello['map']['dir']=str(ROOT/'arena');bot=Bot(hello)
x,y,z=obs['self']['pos']
obs['mechs']=[dict(id=i+1,kind='mech' if i<15 else 'npc',pos=[x+100*math.cos(i*math.tau/27),y+100*math.sin(i*math.tau/27),z],vel=[0,0,0],aim=[0,0],hp=350,max_hp=1400,cubes=0,weapons=['gun']) for i in range(27)]
obs['crates']=[dict(id=1000+i,pos=[x+25*math.cos(i),y+25*math.sin(i),z],hp=300) for i in range(36)]
obs['cubes']=[dict(id=5000+i,pos=[x+20*math.cos(i),y+20*math.sin(i),z]) for i in range(60)]
times=[]
for i in range(50):
    obs['t']=i*.1;obs['tick']=i*2;mf.draw.clear()
    start=time.perf_counter();action=bot.act(obs);times.append((time.perf_counter()-start)*1000)
    assert action['tick']==obs['tick']
late=sum(t>50 for t in times)
print(json.dumps(dict(decisions=len(times),max_ms=round(max(times),2),mean_ms=round(sum(times)/len(times),2),late=late)))
raise SystemExit(late/len(times)>.02)
