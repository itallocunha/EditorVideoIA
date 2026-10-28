(() => {
  'use strict';
  const $=id=>document.getElementById(id), esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  const time=s=>{s=Math.max(0,Number(s)||0);return String(Math.floor(s/60)).padStart(2,'0')+':'+(s%60).toFixed(2).padStart(5,'0');};
  let view='viewEmpty', data=null, review=null, job=null, loading=false, signature='', overlayKey='', sourceDuration=0, elements=[];
  const player=()=>$(view==='viewReview'?'rvPlayer':view==='viewDone'?'player':view==='viewWork'?'livePlayer':'studioVideo');
  function groups(words){const out=[];let cur=[];for(const w of words||[]){if(cur.length&&(cur.length>=3||w.start-cur.at(-1).end>.45||(cur.map(x=>x.word).join(' ')+' '+w.word).length>30)){out.push(cur);cur=[];}cur.push(w);if(/[.!?]$/.test(w.word)){out.push(cur);cur=[];}}if(cur.length)out.push(cur);return out;}
  function originalImages(){
    if(!data?.ready)return [];
    const out=[];
    for(const im of data.images||[]){let offset=0;for(const [a,b] of data.keep||[]){const start=Math.max(im.start,offset),end=Math.min(im.start+im.duration,offset+b-a);if(end>start)out.push({...im,start:a+start-offset,duration:end-start});offset+=b-a;}}
    return out;
  }
  function model(){
    if(['viewReview','viewEmpty'].includes(view)&&review){return {duration:sourceDuration||$('rvPlayer').duration||Math.max(1,...review.lines.map(l=>l.end)),words:review.lines.filter(l=>!l.del&&!l.cut).flatMap(l=>l.words),lines:review.lines,keep:null,images:originalImages(),music:data?.music,original:true};}
    if(data?.ready)return data;
    return {duration:sourceDuration||1,words:[],images:[],keep:null,original:true};
  }
  function rebuild(){
    const m=model(),dur=Math.max(.01,m.duration||1);elements=[];
    const rows=[];
    const add=(track,start,end,text,kind,extra={})=>{if(end<=start)return;const e={track,start:Math.max(0,start),end:Math.min(dur,end),text,kind,...extra};elements.push(e);};
    if(m.keep&&!m.original){let t=0;m.keep.forEach(([a,b],i)=>{add('Vídeo',t,t+b-a,'Trecho '+(i+1),'video',{description:'Original '+time(a)+' – '+time(b)});t+=b-a;});}
    else add('Vídeo',0,dur,'Vídeo original','video');
    const captions=groups(view==='viewDone'&&data?.settings?.subtitles===false?[]:m.words);captions.forEach(g=>add('Legendas',g[0].start,g.at(-1).end,g.map(w=>w.word).join(' '),'caption',{words:g}));
    (m.lines||[]).filter(l=>l.cut).forEach(l=>add('Cortes',l.start,l.end,'Remover trecho','cut'));
    (m.images||[]).forEach(im=>add(im.generated?'Movimentos':'Imagens',im.start,im.start+im.duration,im.label||im.text||im.image,im.generated?'motion':'image',{image:im}));
    if(m.music)add('Áudio',0,dur,'Trilha sonora','audio');
    const labels=['Vídeo','Legendas','Imagens','Movimentos',...(m.lines?.some(l=>l.cut)?['Cortes']:[]),...(m.music?['Áudio']:[])];
    const ticks=Array.from({length:7},(_,i)=>'<span style="left:'+i/6*100+'%">'+time(dur*i/6).slice(0,-3)+'</span>').join('');
    rows.push('<div class="tl-row tl-ruler"><span class="tl-label">TEMPO</span><div class="tl-lane">'+ticks+'</div></div>');
    for(const label of labels){let count=0;const bars=elements.map((e,i)=>{if(e.track!==label)return '';count++;return '<button class="tl-clip tl-'+e.kind+'" data-index="'+i+'" style="left:'+e.start/dur*100+'%;width:'+Math.max(.15,(e.end-e.start)/dur*100)+'%" title="'+esc(e.text)+' · '+time(e.start)+' – '+time(e.end)+'" aria-label="'+esc(label+': '+e.text)+'">'+esc(e.text)+'</button>';}).join('');rows.push('<div class="tl-row"><span class="tl-label">'+label+'</span><div class="tl-lane">'+(count?bars:'<span class="tl-empty">Nenhum elemento</span>')+'</div></div>');}
    $('timelineTracks').innerHTML=rows.join('')+'<div class="tl-cursor" aria-hidden="true"></div>';
    $('timelineTracks').style.width=(Number($('timelineZoom').value)*100)+'%';
    $('timelineSeek').max=dur;$('timelineSeek').disabled=!sourceDuration&&!data?.ready;
    $('timelinePlay').disabled=$('timelineSeek').disabled;
    $('timelineCount').textContent=elements.filter(e=>e.kind!=='video').length+' elementos';
    $('timelineMode').textContent=m.original?'TEMPO ORIGINAL':'TEMPO EDITADO';
    $('livePreview').classList.toggle('hidden',view!=='viewWork'||!data?.ready);
    $('timelineNote').textContent=view==='viewDone'?'Reprodução do MP4 exportado. As faixas mostram os elementos aplicados.':m.original?'Tempos originais. Legendas atualizam ao digitar; imagens e movimentos mostram o último plano gerado. Trechos vermelhos serão removidos.':'Cortes e tempos reais. A prévia dos efeitos é aproximada; o acabamento completo aparece no MP4 exportado.';
    $('timelineElements').dataset.key='reset';overlayKey='';update();
  }
  function update(){
    const p=player(),t=p.currentTime||0,m=model(),d=Math.max(.01,m.duration||1);
    $('timelineSeek').value=t;$('timelineTime').textContent=time(t)+' / '+time(d);$('timelinePlay').textContent=p.paused?'▶':'Ⅱ';$('timelinePlay').setAttribute('aria-label',p.paused?'Reproduzir timeline':'Pausar timeline');
    const cursor=$('timelineTracks').querySelector('.tl-cursor');if(cursor)cursor.style.left='calc(78px + (100% - 78px) * '+Math.min(1,t/d)+')';
    const active=elements.filter(e=>e.start<=t&&e.end>t);const key=active.map(e=>elements.indexOf(e)).join(',');
    if($('timelineElements').dataset.key!==key){$('timelineElements').dataset.key=key;$('timelineElements').innerHTML=active.length?active.map(e=>'<span class="element-chip tl-'+e.kind+'">'+esc(e.track+': '+e.text)+'</span>').join(''):'<span class="hint">Nenhum elemento neste momento.</span>';}
    $('timelineTracks').querySelectorAll('.tl-clip').forEach(el=>{const e=elements[+el.dataset.index];el.classList.toggle('is-current',e.start<=t&&e.end>t);});
    if(!['viewWork','viewReview'].includes(view)||!data?.ready)return;
    const overlay=view==='viewReview'?$('rvElements'):$('liveElements');
    const imageKey=active.filter(e=>e.image).map(e=>e.image.url).join(',');
    if(overlay.dataset.key!==imageKey){overlay.dataset.key=imageKey;overlay.innerHTML=active.filter(e=>e.image).map(e=>'<img class="live-element '+(e.image.mode==='full'?'full':e.image.generated?'graphic':'card')+'" src="'+esc(e.image.url)+'" alt="'+esc(e.text)+'">').join('');}
    if(view==='viewReview')return;
    const cap=active.find(e=>e.kind==='caption'),ws=cap?.words||[],word=ws.findIndex(w=>w.start<=t&&w.end>t);
    const style=$('subtitle_style').value,anim=$('caption_animation').value,capKey=key+':'+word+':'+style+':'+anim+':'+$('font_scale').value+':'+$('subtitles').checked;
    if(capKey!==overlayKey){
      overlayKey=capKey;
      const el=$('liveCaption');el.className='rvcap live-cap anim-'+anim;el.innerHTML=$('subtitles').checked?ws.map((w,i)=>'<span class="'+(i===word?'is-active':'')+'">'+esc(w.word)+'</span>').join(' '):'';
      el.style.fontFamily=$('rvCap').style.fontFamily;el.style.fontSize=(22*Number($('font_scale').value))+'px';el.style.bottom=$('subtitle_position').value==='centro'?'46%':'16%';el.style.setProperty('--rv-accent',$('rvCap').style.getPropertyValue('--rv-accent'));
      $('liveElements').innerHTML=active.filter(e=>e.image).map(e=>'<img class="live-element '+(e.image.mode==='full'?'full':e.image.generated?'graphic':'card')+'" src="'+esc(e.image.url)+'" alt="'+esc(e.text)+'">').join('');
    }
  }
  async function loadTimeline(j){
    const changed=job?.id!==j.id;job=j;if(changed){data=null;signature="";rebuild();}if(loading)return;loading=true;
    try{const r=await fetch('/api/jobs/'+j.id+'/timeline');if(!r.ok)return;const m=await r.json();if(job?.id!==j.id)return;
      if(m.ready){const sig=j.id+':'+JSON.stringify([m.words,m.images,m.keep]);if(sig!==signature){data=m;signature=sig;if($('livePlayer').getAttribute('src')!==m.preview_url)$('livePlayer').src=m.preview_url;rebuild();}}
      else if(view==='viewWork')$('timelineNote').textContent='Preparando as faixas · '+(m.stage||j.stage_label||'Carregando o projeto');
    }catch(_){}finally{loading=false;}
  }
  document.addEventListener('studio:renderstart',()=>{data=null;job=null;signature='';$('liveElements').innerHTML='';$('liveCaption').innerHTML='';rebuild();});
  document.addEventListener('studio:job',e=>loadTimeline(e.detail));
  document.addEventListener('studio:review',e=>{review=e.detail;window.projectTimelineActive=true;rebuild();});
  document.addEventListener('studio:video',()=>{data=null;signature='';sourceDuration=0;rebuild();});
  document.addEventListener('studio:reset',()=>{data=null;review=null;job=null;signature='';window.projectTimelineActive=false;sourceDuration=0;rebuild();});
  document.addEventListener('studio:view',e=>{
    view=e.detail;$('livePlayer').pause();
    const panel=document.querySelector('.timeline-panel');
    if(view==='viewReview')$('viewReview').insertBefore(panel,$('rvList'));
    else if(view==='viewDone')$('viewDone').insertBefore(panel,$('viewDone').querySelector('.actions'));
    else document.querySelector('.preview-column').insertBefore(panel,document.querySelector('.export-panel'));
    if(view!=='viewReview'&&job)loadTimeline(job);rebuild();
  });
  ['rvPlayer','studioVideo','player','livePlayer'].forEach(id=>{
    $(id).addEventListener('timeupdate',update);$(id).addEventListener('seeked',update);
    $(id).addEventListener('loadedmetadata',()=>{if(['rvPlayer','studioVideo'].includes(id)){sourceDuration=$(id).duration;}rebuild();});
    $(id).addEventListener('play',update);$(id).addEventListener('pause',update);
  });
  $('timelinePlay').addEventListener('click',()=>{const p=player();if(p.paused)p.play().catch(()=>{$('timelineNote').textContent='Prévia ainda indisponível. Aguarde a preparação do vídeo.';});else p.pause();});
  $('timelineSeek').addEventListener('input',()=>{player().currentTime=+$('timelineSeek').value;update();});
  $('timelineZoom').addEventListener('change',rebuild);
  $('timelineTracks').addEventListener('click',e=>{const clip=e.target.closest('[data-index]');if(clip){const item=elements[+clip.dataset.index];player().currentTime=item.start;update();return;}const lane=e.target.closest('.tl-lane');if(lane){const rect=lane.getBoundingClientRect();player().currentTime=(e.clientX-rect.left)/rect.width*model().duration;update();}});
  document.addEventListener('input',e=>{if(e.target.closest('.inspector')){overlayKey='';update();}});
  rebuild();
})();
