/* Extras do editor: varios videos na ordem, roteiro, limpeza da fala e lista do que foi removido.
   Fica separado do studio.js: se algo aqui falhar, o editor continua funcionando normalmente. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const fmt = t => { t = Math.max(0, Number(t) || 0); return String(Math.floor(t / 60)).padStart(2, '0') + ':' + (t % 60).toFixed(1).padStart(4, '0'); };
  const isVideo = f => f.type.startsWith('video/') || /\.(mkv|mov|mp4|avi|webm|m4v)$/i.test(f.name);
  let extra = [];   // videos adicionais, em ordem (o principal e o do quadro "Sua midia")

  function draw() {
    const box = $('vlist');
    if (!extra.length) { box.classList.add('hidden'); box.innerHTML = ''; return; }
    box.classList.remove('hidden');
    const main = document.getElementById('videoName') && $('videoName').textContent;
    box.innerHTML = '<div class="vtotal">Ordem final: o vídeo principal' + (main ? ' (' + esc(main) + ')' : '') + ' e depois estes ' + extra.length + '.</div>' +
      extra.map((f, i) => '<div class="vrow" data-i="' + i + '"><span class="n">' + (i + 2) + '</span><video muted preload="metadata" src="' + URL.createObjectURL(f) + '#t=0.1"></video>' +
        '<div class="meta"><div class="name">' + esc(f.name) + '</div><div class="hint">' + (f.size / 1048576).toFixed(1) + ' MB</div></div>' +
        '<button type="button" data-act="up" title="Subir"' + (i === 0 ? ' disabled' : '') + '>↑</button>' +
        '<button type="button" data-act="down" title="Descer"' + (i === extra.length - 1 ? ' disabled' : '') + '>↓</button>' +
        '<button type="button" data-act="rm" title="Remover">✕</button></div>').join('');
  }
  function add(files) {
    const vids = files.filter(isVideo);
    if (!vids.length) return;
    extra.push(...vids);
    draw();
  }
  const drop = $('dropMore'), input = $('moreInput');
  drop.addEventListener('click', () => input.click());
  drop.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); } });
  ['dragenter', 'dragover'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add('over'); }));
  ['dragleave', 'drop'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove('over'); }));
  drop.addEventListener('drop', e => add([...e.dataTransfer.files]));
  input.addEventListener('change', () => { add([...input.files]); input.value = ''; });
  $('vlist').addEventListener('click', e => {
    const b = e.target.closest('button[data-act]'); if (!b) return;
    const i = +b.closest('.vrow').dataset.i, act = b.dataset.act;
    if (act === 'rm') extra.splice(i, 1);
    else { const j = act === 'up' ? i - 1 : i + 1; if (j >= 0 && j < extra.length) [extra[i], extra[j]] = [extra[j], extra[i]]; }
    draw();
  });
  $('videoChange').addEventListener('click', () => setTimeout(draw, 0));

  // Antes do envio: acrescenta os videos extras, o roteiro e as opcoes de limpeza ao formulario.
  const send = XMLHttpRequest.prototype.send, open = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (m, u) { this._extras = m === 'POST' && /\/api\/jobs$/.test(u); return open.apply(this, arguments); };
  XMLHttpRequest.prototype.send = function (body) {
    if (this._extras && body instanceof FormData) {
      try {
        const reuse = body.has('reuse_job');
        if (!reuse && extra.length && body.has('video')) {
          extra.forEach(f => body.append('video', f));
          this.addEventListener('load', () => { if (this.status === 200) { extra = []; draw(); } });
        }
        body.append('script', $('script').value);
        const opts = JSON.parse(body.get('options') || '{}');
        opts.cleanup = { takes: $('cl_takes').checked, fillers: $('cl_fillers').checked, offtopic: $('cl_offtopic').checked };
        body.set('options', JSON.stringify(opts));
      } catch (e) { /* segue sem os extras */ }
    }
    return send.apply(this, arguments);
  };

  // Lista do que a limpeza removeu, na tela final.
  const prev = window.renderStudioReport;
  window.renderStudioReport = result => {
    if (prev) prev(result);
    const rm = (result && result.removed) || [];
    $('removedBox').innerHTML = rm.length
      ? '<div class="removed-box"><h3>Removido da fala (' + rm.length + ')</h3><table><tr><th>Em</th><th>Trecho</th><th>Motivo</th></tr>' +
        rm.map(r => '<tr><td>' + fmt(r.start) + '</td><td>' + esc(r.text) + '</td><td class="why">' + esc(r.reason) + '</td></tr>').join('') + '</table></div>'
      : '';
  };
})();
