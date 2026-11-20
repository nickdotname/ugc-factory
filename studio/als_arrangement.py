import gzip, json, os, sys
import xml.etree.ElementTree as ET
def load(path):
    root = ET.fromstring(gzip.open(path,'rb').read()); ls = root.find('LiveSet')
    t = ls.find('.//MainTrack//Tempo/Manual')
    if t is None: t = ls.find('.//MasterTrack//Tempo/Manual')
    tempo = float(t.get('Value'))
    out=[]
    for tr in ls.find('Tracks'):
        name = tr.find('Name/EffectiveName').get('Value')
        col = tr.find('Color'); color = int(col.get('Value')) if col is not None else 0
        gid = tr.find('TrackGroupId'); gid = int(gid.get('Value')) if gid is not None else -1
        sp = tr.find('DeviceChain/Mixer/Speaker/Manual'); on = sp.get('Value')=='true' if sp is not None else True
        notes=[]; clips=[]
        for c in tr.findall('.//ArrangerAutomation/Events/MidiClip'):
            if c.find('Disabled') is not None and c.find('Disabled').get('Value')=='true': continue
            s=float(c.find('CurrentStart').get('Value')); e=float(c.find('CurrentEnd').get('Value'))
            L=c.find('Loop'); ls_=float(L.find('LoopStart').get('Value')); le=float(L.find('LoopEnd').get('Value'))
            rel=float(L.find('StartRelative').get('Value')); lon=L.find('LoopOn').get('Value')=='true'
            clips.append((s,e,'midi'))
            raw=[]
            for kt in c.iter('KeyTrack'):
                key=int(kt.find('MidiKey').get('Value'))
                for n in kt.iter('MidiNoteEvent'):
                    if n.get('IsEnabled')=='false': continue
                    raw.append((float(n.get('Time')),float(n.get('Duration')),key,float(n.get('Velocity'))))
            ll=le-ls_; sm=ls_+rel
            for (nt,nd,k,v) in raw:
                if lon and ll>0:
                    # note occurs at arrangement time s + (nt - sm) + i*ll for all i
                    i0=int(((0-(nt-sm))//ll))-1
                    for i in range(i0, i0+int((e-s)/ll)+3):
                        a=s+(nt-sm)+i*ll
                        if nt<ls_ and i>0: continue
                        if nt>=le: continue
                        if a>=s-1e-6 and a<e-1e-6: notes.append((a,min(nd,e-a),k,v))
                else:
                    a=s+(nt-sm)
                    if a>=s-1e-6 and a<e: notes.append((a,min(nd,e-a),k,v))
        for c in tr.findall('.//ArrangerAutomation/Events/AudioClip'):
            if c.find('Disabled') is not None and c.find('Disabled').get('Value')=='true': continue
            clips.append((float(c.find('CurrentStart').get('Value')),float(c.find('CurrentEnd').get('Value')),'audio'))
        out.append(dict(kind=tr.tag,name=name,color=color,group=gid,on=on,notes=sorted(set(notes)),clips=sorted(clips)))
    return tempo,out
if __name__=='__main__':
    tempo,tr=load(sys.argv[1]); json.dump(dict(tempo=tempo,tracks=tr),open(sys.argv[2],'w'))
    for i,t in enumerate(tr):
        if t['notes'] or t['clips']:
            ks=sorted(set(n[2] for n in t['notes']))
            print(i,t['kind'][:4],t['name'][:26],'on' if t['on'] else 'MUTED','notes',len(t['notes']),'keys',ks[:8],'clips',len(t['clips']),'span',(round(min(c[0] for c in t['clips'])),round(max(c[1] for c in t['clips']))) if t['clips'] else '')
