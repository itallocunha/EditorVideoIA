"""Two real local exports; synthetic media only. Verifies cached cut reuse and draft recovery."""
import json
import sys
import time
from pathlib import Path
import urllib.request
import uuid
class Response:
    def __init__(self,res):
        self.status_code=res.status
        self.body=res.read()
    def json(self): return json.loads(self.body)
    def raise_for_status(self): assert self.status_code < 400, self.body
class Client:
    def call(self, method, url, data=None, files=None, json=None, headers=None):
        import json as js
        headers=dict(headers or {})
        if json is not None:
            body=js.dumps(json).encode();headers['Content-Type']='application/json'
        elif files:
            boundary=uuid.uuid4().hex;parts=[]
            for k,v in (data or {}).items(): parts.append(('--'+boundary+'\r\nContent-Disposition: form-data; name="'+k+'"\r\n\r\n'+v+'\r\n').encode())
            for k,(name,f,mime) in files.items(): parts.append(('--'+boundary+'\r\nContent-Disposition: form-data; name="'+k+'"; filename="'+name+'"\r\nContent-Type: '+mime+'\r\n\r\n').encode()+f.read()+b'\r\n')
            parts.append(('--'+boundary+'--\r\n').encode());body=b''.join(parts);headers['Content-Type']='multipart/form-data; boundary='+boundary
        elif data is not None:
            from urllib import parse
            body=parse.urlencode(data).encode();headers['Content-Type']='application/x-www-form-urlencoded'
        else: body=None
        with urllib.request.urlopen(urllib.request.Request(url,data=body,headers=headers,method=method),timeout=20) as res:return Response(res)
    def get(self,url,**kw):return self.call('GET',url,**kw)
    def post(self,url,**kw):return self.call('POST',url,**kw)
    def put(self,url,**kw):return self.call('PUT',url,**kw)
requests=Client()
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from editor.media import probe
root=Path(__file__).resolve().parents[1]
base='http://127.0.0.1:8766'
source=root/'workspace/validation/motion_smoke_final/prova_motion.mp4'
words=[{'word':text,'start':start,'end':start+.36} for text,start in [('Seu',.2),('resultado',.65),('em',1.1),('30',1.55),('dias.',2),('Fontes',2.7),('com',3.1),('movimento.',3.6)]]
opts={'quality':'rapido','settings':{'cut_silence':False,'punch_zoom':False,'font':'Georgia','subtitle_style':'editorial','caption_engine':'ass','image_engine':'ffmpeg','motion_intensity':'bold','aspect':'original','look':'none'}}
def wait(ident):
    deadline=time.monotonic()+150
    timeline_before_done=False
    while time.monotonic()<deadline:
        j=requests.get(base+'/api/jobs/'+ident).json()
        timeline=requests.get(base+'/api/jobs/'+ident+'/timeline').json()
        if timeline.get('ready') and j['status']!='done': timeline_before_done=True
        if j['status']=='done':
            print('DONE',ident,'timeline_before_done',timeline_before_done,flush=True)
            return j,timeline
        if j['status'] in ('error','cancelled'): raise AssertionError(j)
        time.sleep(.3)
    raise AssertionError('Timeout')
with source.open('rb') as f:
    r=requests.post(base+'/api/jobs',files={'video':('teste_timeline.mp4',f,'video/mp4')},data={'options':json.dumps(opts),'words':json.dumps(words)})
r.raise_for_status();first=r.json()['id'];print('FIRST',first,flush=True)
j1,t1=wait(first)
p=requests.get(base+'/api/jobs/'+first+'/project').json();p['lines'][0]['words'][0]['word']='Novo'
prefs={'subtitle_style':'editorial','caption_animation':'spring','font':'Georgia','aspect':'original','caption_engine':'ass','image_engine':'ffmpeg','motion_intensity':'bold','quality':'rapido','subtitles':True,'punch_zoom':False,'prompt':'Não corte as pausas'}
requests.put(base+'/api/jobs/'+first+'/project',json={'lines':p['lines'],'preferences':prefs}).raise_for_status()
r=requests.post(base+'/api/jobs',data={'reuse_job':first,'options':json.dumps(opts)})
r.raise_for_status();second=r.json()['id'];print('SECOND',second,flush=True)
j2,t2=wait(second)
assert any('Vídeo cortado reutilizado' in s for s in j2['log']),j2['log']
assert any('Plano de cortes salvo reutilizado' in s for s in j2['log']),j2['log']
assert any('Legendas revisadas reutilizadas' in s for s in j2['log']),j2['log']
assert t2['words'][0]['word']=='Novo'
assert t2['images'] and t2['preview_url']
assert requests.get(base+t2['images'][0]['url']).status_code==200
assert requests.get(base+t2['preview_url'],headers={'Range':'bytes=0-99'}).status_code==206
assert probe(root/'workspace/jobs'/second/'final.mp4')['has_audio']
(root/'workspace/validation/project-reuse.json').write_text(json.dumps({'first':first,'second':second,'logs':j2['log']},ensure_ascii=False,indent=2),encoding='utf-8')
print('REUSE_SMOKE_OK',first,second,flush=True)
