"""Repeat scenarios, retaining traces and an aggregate comparison table."""
import argparse
import concurrent.futures
import contextlib
import io
import json
from pathlib import Path
from simulate import Arena,ROOT,CURRENT_BOT


def run_case(task):
    scenario,seed,count,duration,bot,label=task
    folder=ROOT/'simulator/results'/label/f'{scenario}-{seed}'
    with contextlib.redirect_stdout(io.StringIO()):
        result=Arena(seed,count,scenario,Path(bot)).run(duration,folder)
    return dict(scenario=scenario,seed=seed,**result)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--bot',type=Path,default=CURRENT_BOT)
    p.add_argument('--label',default='candidate')
    p.add_argument('--seeds',type=int,nargs='+',default=[1,2,3,4,5])
    p.add_argument('--seconds',type=float,default=120)
    p.add_argument('--include-roof',action='store_true')
    p.add_argument('--workers',type=int,default=1)
    a=p.parse_args()
    if a.workers<1 or a.seconds<=0:p.error('workers and seconds must be positive')
    results=[]
    cases=[('pursuit',s,2,a.seconds) for s in a.seeds]+[('random',s,16,a.seconds) for s in a.seeds]
    if a.include_roof:cases.insert(0,('rooftop',1,1,350))
    tasks=[(*case,str(a.bot.resolve()),a.label) for case in cases]
    with concurrent.futures.ProcessPoolExecutor(max_workers=a.workers) as pool:
        for future in concurrent.futures.as_completed([pool.submit(run_case,t) for t in tasks]):
            r=future.result();results.append(r)
            print(f"{r['scenario']} seed={r['seed']} alive={r['bot_alive']} t={r['elapsed_s']} hp={r['bot_hp']:.0f} damage={r['damage']} late={r['over_budget']} errors={len(r['errors'])}",flush=True)
            (ROOT/'simulator/results'/a.label/'suite.json').write_text(json.dumps(sorted(results,key=lambda r:(r['scenario'],r['seed'])),indent=2))


if __name__=='__main__':main()
