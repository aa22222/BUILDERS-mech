"""Render simulator paths and death locations on the map as a standalone SVG."""
import argparse
import html
import json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser()
p.add_argument('trace',type=Path)
p.add_argument('--out',type=Path)
a=p.parse_args()
world=json.loads((root/'arena/v2/world.json').read_text())
rows=[json.loads(line) for line in a.trace.read_text().splitlines()]
b=world['bounds'];width=b['maxX']-b['minX'];height=b['maxY']-b['minY']
def point(x,y):return f'{x-b["minX"]:.2f},{b["maxY"]-y:.2f}'
svg=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-10 -35 {width+20:.2f} {height+75:.2f}">','<rect x="-10" y="-35" width="1200" height="900" fill="#fafafa"/>',f'<text x="0" y="-12" font-family="sans-serif" font-size="16">{html.escape(a.trace.parent.name)} - approximate simulation, blue = tested bot</text>']
for prism in world['prisms']:
    parts=[]
    for ring in [prism['ring']]+prism.get('holes',[]):
        parts.append('M'+' L'.join(point(ring[i],ring[i+1]) for i in range(0,len(ring),2))+' Z')
    svg.append(f'<path d="{" ".join(parts)}" fill="#d0d3d8" fill-rule="evenodd"/>')
for ident in range(len(rows[0]['actors'])):
    positions=[r['actors'][ident] for r in rows]
    color='#1261bd' if ident==0 else '#b64b4055'
    coords=' '.join(point(*actor['pos'][:2]) for actor in positions)
    svg.append(f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="{2.5 if ident==0 else 1}"/>')
    last=positions[-1]
    if last['hp']<=0:
        x,y=point(*last['pos'][:2]).split(',')
        svg.append(f'<circle cx="{x}" cy="{y}" r="5" fill="{color}"/>')
for r in rows:
    if int(r['t'])%15==0:
        x,y=point(*r['actors'][0]['pos'][:2]).split(',')
        svg.append(f'<text x="{x}" y="{y}" font-family="sans-serif" font-size="9" fill="#124170">{r["t"]:g}s</text>')
last=rows[-1];c=last['zone']['center'];x,y=point(*c).split(',')
svg.append(f'<circle cx="{x}" cy="{y}" r="{last["zone"]["radius"]}" fill="none" stroke="#8f64b5" stroke-dasharray="6,6"/>')
svg.append('</svg>')
out=a.out or a.trace.with_name('paths.svg');out.write_text('\n'.join(svg),encoding='utf-8');print(out)
