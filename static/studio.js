
(() => {
  const $ = (id) => document.getElementById(id);
  const state = { mode: "edit", video: null, images: [], music: null, job: null, poll: null, savedJob: null, musicRemoved: false, baseSettings: {} };
  const STEPS_ANALYZE = [["prepare", "Lendo o vídeo"], ["transcribe", "Transcrevendo a fala"], ["frames", "Extraindo quadros"], ["describe", "Descrevendo as cenas"], ["report", "Montando o relatório"]];
  const STEPS_EDIT = [["prepare", "Analisando arquivos"], ["transcribe", "Transcrevendo a fala"], ["plan", "Planejando a edição"],
                 ["cut", "Removendo pausas"], ["subs", "Criando legendas"], ["final", "Montando o vídeo final"]];
  const STEPS_REVIEW = [["prepare", "Lendo o vídeo"], ["transcribe", "Transcrevendo a fala"], ["preview", "Preparando a prévia"]];
  let STEPS = STEPS_EDIT;
  const EXAMPLES = [
    "Corte as pausas de forma agressiva, legenda amarela estilo Hormozi, formato vertical para Reels",
    "Legenda verde no centro da tela, imagens em tela cheia com zoom, música baixa",
    "Ritmo calmo e natural, legenda suave, imagens como cartões centralizados",
    "Sem legenda, só corte as pausas e normalize o áudio"
  ];

  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  };

  // ---------- saude do sistema
  fetch("/api/health").then(r => r.json()).then(h => {
    const chips = $("chips");
    const add = (txt, ok) => { const s = document.createElement("span"); s.className = "chip " + (ok ? "ok" : "bad"); s.textContent = txt; chips.appendChild(s); };
    add(h.ffmpeg ? "Exportação disponível" : "Motor de vídeo ausente", h.ffmpeg);
    add(h.whisper ? "Transcrição disponível" : "Transcrição indisponível", h.whisper);
    if (h.hyperframes) { const ready = !!h.hyperframes.available; add(ready ? "Animação disponível" : "Animação indisponível", ready); $("engineHint").textContent = ready ? "Pré-requisitos encontrados. O motor é verificado antes da exportação." : "HyperFrames indisponível: " + (h.hyperframes.reason || "verifique as dependências do motor."); } else { $("engineHint").textContent = "O estado do motor de animação será verificado ao exportar."; }
    const ia = document.createElement("span"); ia.className = "chip"; ia.textContent = h.api_key_env ? "IA ligada (chave no sistema)" : "IA opcional"; chips.appendChild(ia);
    const msgs = [];
    if (!h.ffmpeg) msgs.push("FFmpeg não encontrado. Rode o iniciar.bat novamente.");
    if (h.ffmpeg_missing_filters && h.ffmpeg_missing_filters.length) msgs.push("Seu FFmpeg não tem os filtros: " + h.ffmpeg_missing_filters.join(", ") + ". Instale a versão completa: winget install Gyan.FFmpeg");
    if (!h.whisper) msgs.push("A biblioteca faster-whisper não está instalada. Rode o iniciar.bat novamente.");
    if (msgs.length) { $("warn").textContent = msgs.join(" "); $("warn").classList.remove("hidden"); }
  }).catch(() => {});

  // ---------- helpers
  const fmtSize = (b) => b > 1e9 ? (b / 1e9).toFixed(2) + " GB" : (b / 1e6).toFixed(1) + " MB";
  const fmtTime = (s) => { s = Math.round(s); return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0"); };
  const esc = (s) => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  function wireDrop(zone, input, onFiles) {
    zone.addEventListener("click", (e) => { if (e.target.closest("button")) return; input.click(); });
    ["dragenter", "dragover"].forEach(ev => zone.addEventListener(ev, e => { e.preventDefault(); zone.classList.add("over"); }));
    ["dragleave", "drop"].forEach(ev => zone.addEventListener(ev, e => { e.preventDefault(); zone.classList.remove("over"); }));
    zone.addEventListener("drop", e => onFiles([...e.dataTransfer.files]));
    input.addEventListener("change", () => { onFiles([...input.files]); input.value = ""; });
  }

  function refreshGo() {
    const ok = !!state.video && !state.job;
    $("projectSelect").disabled = !!state.job;
    $("videoChange").disabled = !!state.job;
    $("go").disabled = !ok; $("analyze").disabled = !ok; $("review").disabled = !ok;
    $("goHint").textContent = !state.video ? "Envie um vídeo para começar." :
      (state.job ? "Processando..." : "Pronto. Clique para editar, revisar as legendas ou analisar.");
  }

  // ---------- video
  wireDrop($("dropVideo"), $("videoInput"), (files) => {
    if(state.job)return;
    const f = files.find(x => x.type.startsWith("video/") || /\.(mkv|mov|mp4|avi|webm|m4v)$/i.test(x.name));
    if (!f) return;
    state.savedJob = null; state.baseSettings={}; state.lastExport=null; $("rvLast").disabled=true; document.body.classList.remove("has-project"); rv.id=null; rv.lines=[]; store.set("editorProject", "");
    document.dispatchEvent(new CustomEvent("studio:reset"));
    state.video = f;
    $("videoEmpty").classList.add("hidden"); $("videoFile").classList.remove("hidden");
    $("videoName").textContent = f.name;
    const v = $("videoThumb"); if (v.src.startsWith("blob:")) URL.revokeObjectURL(v.src); v.src = URL.createObjectURL(f); document.dispatchEvent(new CustomEvent("studio:video", {detail: {file:f, url:v.src}}));
    v.onloadedmetadata = () => { $("videoMeta").textContent = fmtSize(f.size) + " · " + fmtTime(v.duration) + " · " + v.videoWidth + "x" + v.videoHeight; };
    refreshGo();
  });
  $("videoChange").addEventListener("click", () => $("videoInput").click());

  // ---------- imagens
  function renderThumbs() {
    const box = $("thumbs"); box.innerHTML = "";
    state.images.forEach((f, i) => {
      const d = document.createElement("div"); d.className = "thumb";
      d.innerHTML = `<img alt=""><button type="button" title="Remover">×</button><span>${esc(f.name)}</span>`;
      d.querySelector("img").src = f.url || URL.createObjectURL(f);
      d.querySelector("button").addEventListener("click", () => { state.images.splice(i, 1); renderThumbs(); });
      box.appendChild(d);
    });
  }
  wireDrop($("dropImages"), $("imagesInput"), (files) => {
    files.filter(f => f.type.startsWith("image/")).forEach(f => state.images.push(f));
    renderThumbs();
  });

  // ---------- musica
  wireDrop($("dropMusic"), $("musicInput"), (files) => {
    const f = files.find(x => x.type.startsWith("audio/") || /\.(mp3|wav|m4a|aac|ogg|flac)$/i.test(x.name));
    if (!f) return;
    state.musicRemoved=false; state.music = f; $("musicEmpty").classList.add("hidden"); $("musicFile").classList.remove("hidden");
    $("musicName").textContent = f.name + " (" + fmtSize(f.size) + ")";
  });
  $("musicRemove").addEventListener("click", (e) => {
    e.stopPropagation(); state.musicRemoved=true; state.music = null; $("musicEmpty").classList.remove("hidden"); $("musicFile").classList.add("hidden");
  });

  // ---------- exemplos e preferencias salvas
  EXAMPLES.forEach(t => { const b = document.createElement("button"); b.type = "button"; b.className = "ex"; b.textContent = ["Ritmo dinâmico", "Verde & imagens", "Calmo & natural", "Só cortes"][EXAMPLES.indexOf(t)]; b.title = t; b.onclick = () => { $("prompt").value = t; }; $("examples").appendChild(b); });
  const FIELDS = ["font", "caption_animation", "font_scale", "motion_intensity", "caption_engine", "look", "cut_engine", "image_engine", "aspect", "subtitle_style", "subtitle_position", "min_silence", "image_duration", "quality", "whisper_model", "language", "active_color"];
  const CHECKS = ["use_color", "punch_zoom", "subtitles"];
  try {
    const saved = JSON.parse(store.get("editorPrefs") || "{}");
    delete saved.api_key; store.set("editorPrefs", JSON.stringify(saved));
    FIELDS.forEach(k => { if (saved[k] !== undefined && $(k)) $(k).value = saved[k]; });
    CHECKS.forEach(k => { if (saved[k] !== undefined && $(k)) $(k).checked = saved[k]; });
    if (saved.prompt) $("prompt").value = saved.prompt;
  } catch (e) {}
  function savePrefs() {
    const o = { prompt: $("prompt").value };
    FIELDS.forEach(k => o[k] = $(k).value); CHECKS.forEach(k => o[k] = $(k).checked);
    store.set("editorPrefs", JSON.stringify(o));
  }

  // ---------- envio
  function buildOptions() {
    const s = {...state.baseSettings};
    const pick = (k, conv) => { const v = $(k).value; if (v && v !== "auto") s[k] = conv ? conv(v) : v; };
    pick("font"); pick("caption_animation"); pick("font_scale", parseFloat); pick("motion_intensity"); pick("aspect"); pick("look"); pick("caption_engine"); pick("cut_engine"); pick("image_engine"); pick("subtitle_style"); pick("subtitle_position"); pick("min_silence", parseFloat); pick("image_duration", parseFloat);
    if ($("use_color").checked) s.active_color = $("active_color").value.toUpperCase();
    s.punch_zoom = $("punch_zoom").checked; s.subtitles = $("subtitles").checked;
    if (s.min_silence) s.pad = s.min_silence < 0.3 ? 0.07 : (s.min_silence > 0.6 ? 0.14 : 0.09);
    return { settings: s, whisper_model: $("whisper_model").value, language: $("language").value, quality: $("quality").value, api_key: $("api_key").value.trim() };
  }

  function show(view) { ["viewEmpty", "viewWork", "viewDone", "viewAnalysis", "viewReview"].forEach(v => $(v).classList.toggle("hidden", v !== view)); document.dispatchEvent(new CustomEvent("studio:view", {detail: view})); }

  function renderSteps(stage) {
    const idx = STEPS.findIndex(s => s[0] === stage);
    $("steps").innerHTML = STEPS.map((s, i) => `<li class="${i < idx || stage === "done" ? "done" : (i === idx ? "cur" : "")}">${s[1]}</li>`).join("");
  }

  $("go").addEventListener("click", () => submit("edit"));
  $("analyze").addEventListener("click", () => submit("analyze"));
  $("review").addEventListener("click", () => openReview());

  async function submit(mode, extra) {
    if (!state.video) return;
    if (state.job) return;
    if (!(await flushProject())) return;
    state.mode = mode; STEPS = mode === "analyze" ? STEPS_ANALYZE : (mode === "review" ? STEPS_REVIEW : STEPS_EDIT);
    savePrefs();
    const fd = new FormData();
    if (state.savedJob && !extra?.reuse_job) fd.append("reuse_job",state.savedJob);
    else if (!extra?.reuse_job) fd.append("video", state.video);
    if (extra) Object.keys(extra).forEach(k => fd.append(k, extra[k]));
    state.images.filter(f=>f instanceof File).forEach(f => fd.append("images", f));
    fd.append("retain_images",JSON.stringify(state.images.filter(f=>!(f instanceof File)).map(f=>f.index)));
    if (state.music instanceof File) fd.append("music", state.music);
    fd.append("remove_music",state.musicRemoved?"1":"0");
    fd.append("prompt", $("prompt").value); fd.append("options", JSON.stringify(buildOptions())); fd.append("mode", mode);
    state.job = "uploading"; refreshGo();
    document.dispatchEvent(new CustomEvent("studio:renderstart"));
    show("viewWork"); $("errBox").classList.add("hidden"); $("log").textContent = "";
    $("workTitle").textContent = "Enviando arquivos"; $("stageLabel").textContent = "Enviando para o editor..."; renderSteps("");
    $("barFill").style.width = "0%"; $("pctLabel").textContent = "0%"; $("cancel").classList.remove("hidden");

    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/jobs");
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) { const p = Math.round(e.loaded / e.total * 100); $("stageLabel").textContent = "Enviando arquivos... " + p + "%"; } };
    xhr.onload = async () => {
      let data = {}; try { data = JSON.parse(xhr.responseText); } catch (e) {}
      if (xhr.status !== 200 || !data.id) { fail(data.error || "Falha no envio."); return; }
      state.job = data.id; state.savedJob=data.id; document.body.classList.add("has-project"); store.set("editorProject",data.id); rv.id=null;
      await syncAssets(data.id); refreshProjects();
      document.dispatchEvent(new CustomEvent("studio:job",{detail:{id:data.id,stage_label:"Preparando projeto"}}));
      $("workTitle").textContent = state.mode === "analyze" ? "Analisando o vídeo" : (state.mode === "review" ? "Preparando a revisão" : "Processando"); startPolling();
    };
    xhr.onerror = () => fail("Não consegui falar com o servidor. A janela do iniciar.bat ainda está aberta?");
    xhr.send(fd);
  }

  function fail(msg) {
    $("errBox").textContent = msg; $("errBox").classList.remove("hidden");
    $("workTitle").textContent = "Algo deu errado"; $("cancel").classList.add("hidden");
    if (state.poll) clearInterval(state.poll);
    state.job = null; refreshGo();
    if (!$("viewWork").querySelector(".actions .retry")) {
      const b = document.createElement("button"); b.className = "sec retry"; b.textContent = "Voltar"; b.onclick = () => { show("viewEmpty"); b.remove(); };
      $("viewWork").querySelector(".actions").appendChild(b);
    }
  }

  function startPolling() {
    if (state.poll) clearInterval(state.poll);
    state.poll = setInterval(async () => {
      let j; try { j = await (await fetch("/api/jobs/" + state.job)).json(); } catch (e) { return; }
      if (j.error && !j.status) return;
      document.dispatchEvent(new CustomEvent("studio:job",{detail:j}));
      const pct = Math.round(j.percent || 0);
      $("barFill").style.width = pct + "%"; $("pctLabel").textContent = pct + "%";
      $("stageLabel").textContent = j.status === "queued" ? "Na fila (posição " + (j.queue_pos || 1) + ")" : (j.stage_label || "");
      renderSteps(j.stage);
      const logEl = $("log"); const atEnd = logEl.scrollTop + logEl.clientHeight >= logEl.scrollHeight - 8;
      logEl.textContent = (j.log || []).join("\n"); if (atEnd) logEl.scrollTop = logEl.scrollHeight;
      if (j.status === "done") { clearInterval(state.poll); done(j); }
      else if (j.status === "error") { fail(j.error || "Erro desconhecido."); }
      else if (j.status === "cancelled") { clearInterval(state.poll); state.job = null; refreshGo(); show("viewEmpty"); }
    }, 1000);
  }

  $("cancel").addEventListener("click", () => { if (state.job && state.job !== "uploading") fetch("/api/jobs/" + state.job + "/cancel", { method: "POST" }); });

  async function copy(text, label) {
    try { await navigator.clipboard.writeText(text); $("aMsg").textContent = label + " copiado."; }
    catch (e) {
      const t = document.createElement("textarea"); t.value = text; document.body.appendChild(t); t.select();
      try { document.execCommand("copy"); $("aMsg").textContent = label + " copiado."; } catch (_) { $("aMsg").textContent = "Não consegui copiar. Selecione o texto e use Ctrl+C."; }
      t.remove();
    }
  }

  function showAnalysis(j) {
    const r = j.result; const id = state.job; const st = r.stats;
    show("viewAnalysis");
    $("aStats").innerHTML = [
      ["Duração", fmtTime(r.info.duration)], ["Tamanho", r.info.size], ["Palavras", st.words],
      ["Palavras por minuto", st.wpm], ["Pausas longas", st.pauses], ["Idioma", r.language]
    ].map(a => `<div class="stat"><b>${esc(String(a[1]))}</b>${a[0]}</div>`).join("");
    $("aAiNote").textContent = r.ai_used ? "" : "Descrição visual desligada: cole a chave da API da Anthropic em Opções avançadas e analise de novo para a IA descrever cada cena. O prompt abaixo foi montado só com regras.";
    let html = "";
    if (r.summary) html += `<div class="sub">Resumo</div><div class="box">${esc(r.summary)}</div>`;
    if (r.visual_style) html += `<div class="sub">Estilo visual</div><div class="box">${esc(r.visual_style)}</div>`;
    if (r.keywords && r.keywords.length) html += `<div class="sub">Palavras mais usadas</div><div class="box">${esc(r.keywords.join(", "))}</div>`;
    $("aSummary").innerHTML = html;
    $("aPrompt").value = r.suggested_prompt || "";
    $("aFrames").innerHTML = r.frames.map(f => `<div class="frame"><img src="/api/jobs/${id}/frame/${encodeURIComponent(f.file)}" alt=""><div><b>${fmtTime(f.time)}</b> ${esc(f.description || "")}</div></div>`).join("");
    let extra = "";
    if (r.highlights && r.highlights.length) extra += `<div class="sub">Momentos fortes</div><div class="box">` + r.highlights.map(h => `${fmtTime(Number(h.time) || 0)}  ${esc(h.note || "")}`).join("\n") + `</div>`;
    if (r.image_ideas && r.image_ideas.length) extra += `<div class="sub">Ideias de imagens de apoio</div><div class="box">` + r.image_ideas.map(h => `${esc(h.file || "")} aos ${esc(String(h.time || ""))} s: ${esc(h.why || "")}`).join("\n") + `</div>`;
    $("aExtra").innerHTML = extra;
    $("aTranscript").textContent = r.transcript_timed || "(nenhuma fala detectada)";
    $("aDl").href = "/api/jobs/" + id + "/report";
    $("aMsg").textContent = "Tudo foi salvo também na pasta saída: " + r.output_name;
    state.analysis = r;
    state.job = null; refreshGo();
  }
  $("aUse").addEventListener("click", () => { $("prompt").value = $("aPrompt").value; savePrefs(); show("viewEmpty"); $("prompt").scrollIntoView({ behavior: "smooth", block: "center" }); $("prompt").focus(); });
  $("aCopyPrompt").addEventListener("click", () => copy($("aPrompt").value, "Prompt"));
  $("aCopyTr").addEventListener("click", () => copy(state.analysis.transcript_timed, "Transcrição"));
  $("aCopyPlain").addEventListener("click", () => copy(state.analysis.transcript_plain, "Texto"));
  $("aCopySrt").addEventListener("click", () => copy(state.analysis.srt, "Legendas"));
  $("aCopyAll").addEventListener("click", () => copy(state.analysis.report_md, "Relatório"));
  $("aBack").addEventListener("click", () => show("viewEmpty"));
  $("aFolder").addEventListener("click", () => $("openFolder").click());

  // ---------- revisao de legendas
  const rv = { id: null, lines: [], cur: -1 };
  const fmtSrt = (t) => { const ms = Math.round(Math.max(t, 0) * 1000); const h = Math.floor(ms / 3600000), m = Math.floor(ms % 3600000 / 60000), s = Math.floor(ms % 60000 / 1000), x = ms % 1000; const z = (n, w) => String(n).padStart(w, "0"); return z(h, 2) + ":" + z(m, 2) + ":" + z(s, 2) + "," + z(x, 3); };
  const lineText = (L) => L.words.map(w => w.emph ? "*" + w.word + "*" : w.word).join(" ");
  const r2 = (n) => Math.round(n * 100) / 100;

  function showReview(j) {
    const r = j.result;
    rv.id = j.id || state.savedJob; rv.lines = r.lines.map(l => ({ start: l.start, end: l.end, words: l.words.map(w => ({ ...w })), cut: !!l.cut, del: !!l.del, ...(l.reason ? { reason: l.reason } : {}) }));
    show("viewReview");
    $("rvProxy").classList.add("hidden");
    $("rvPlayer").src = "/api/jobs/" + rv.id + "/source";
    $("rvMsg").textContent = r.lines.length ? (r.suggested ? "A limpeza sugeriu cortar " + r.suggested + " trecho(s), marcados com ✂ e em vermelho. Passe o mouse para ver o motivo; clique no ✂ para manter o trecho." : "") : "Nenhuma fala foi detectada. Você ainda pode seguir sem legendas.";
    drawRows(false);
    state.job = null; refreshGo();
  }

  function drawRows(save = true) {
    $("rvList").innerHTML = rv.lines.map((L, i) =>
      `<div class="row${L.cut ? " cutrow" : ""}${L.del ? " delrow" : ""}" data-i="${i}"${L.reason ? ` title="${esc(L.reason)}"` : ""}>` +
      `<input class="t ts" type="number" step="0.1" min="0" value="${r2(L.start)}" title="início (s)">` +
      `<input class="t te" type="number" step="0.1" min="0" value="${r2(L.end)}" title="fim (s)">` +
      `<input class="tx" type="text" value="${esc(lineText(L))}">` +
      `<div class="rvtools"><button class="ic cut${L.cut ? " on" : ""}" title="Cortar este trecho do vídeo" type="button">✂</button>` +
      `<button class="ic del${L.del ? " on" : ""}" title="Apagar só a legenda" type="button">✕</button>` +
      `<button class="ic split" title="Dividir onde está o cursor" type="button">⎘</button>` +
      `<button class="ic join" title="Juntar com a próxima" type="button">⇣</button></div></div>`).join("");
    reviewChanged(save);
  }

  function reviewChanged(save = true) {
    document.dispatchEvent(new CustomEvent("studio:review",{detail:{lines:rv.lines,id:rv.id}}));
    if(save) scheduleSave();
    $("rvPlayer").dispatchEvent(new Event("timeupdate"));
  }
  $("rvList").addEventListener("input",e=>{const row=e.target.closest(".row");if(row && e.target.classList.contains("tx")){setText(+row.dataset.i,e.target.value);reviewChanged();}});

  function setText(i, text) {
    const L = rv.lines[i]; if (!L) return;
    const toks = text.trim().split(/\s+/).filter(Boolean).map(t => { const m = /^\*(.+)\*$/.exec(t); return m ? { word: m[1], emph: true } : { word: t.replace(/\*/g, ""), emph: false }; });
    if (!toks.length) { L.words = []; return; }
    if (toks.length === L.words.length) { L.words.forEach((w, k) => { w.word = toks[k].word; w.emph = toks[k].emph; }); return; }
    const total = Math.max(L.end - L.start, 0.2), wt = toks.map(t => t.word.length + 1), sum = wt.reduce((a, b) => a + b, 0);
    let c = L.start;
    L.words = toks.map((t, k) => { const d = total * wt[k] / sum; const w = { word: t.word, emph: t.emph, start: r2(c), end: r2(c + d) }; c += d; return w; });
  }

  function setTimes(i, s, e) {
    const L = rv.lines[i]; if (!L) return;
    s = Math.max(0, Number(s)); e = Math.max(s + 0.2, Number(e));
    const os = L.start, oe = L.end, span = oe - os;
    L.words.forEach(w => {
      const f0 = span > 0 ? (w.start - os) / span : 0, f1 = span > 0 ? (w.end - os) / span : 1;
      w.start = r2(s + f0 * (e - s)); w.end = r2(s + f1 * (e - s));
    });
    L.start = r2(s); L.end = r2(e);
  }

  $("rvList").addEventListener("change", (ev) => {
    const row = ev.target.closest(".row"); if (!row) return; const i = +row.dataset.i;
    if (ev.target.classList.contains("tx")) { setText(i, ev.target.value); drawRows(); }
    else if (ev.target.classList.contains("ts") || ev.target.classList.contains("te")) {
      setTimes(i, row.querySelector(".ts").value, row.querySelector(".te").value); drawRows();
    }
  });
  $("rvList").addEventListener("focusin", (ev) => {
    const row = ev.target.closest(".row");
    if (row && ev.target.classList.contains("tx")) { const L = rv.lines[+row.dataset.i]; if (L) $("rvPlayer").currentTime = Math.max(L.start - 0.05, 0); }
  });
  $("rvList").addEventListener("click", (ev) => {
    const row = ev.target.closest(".row"); if (!row) return; const i = +row.dataset.i; const L = rv.lines[i];
    const b = ev.target.closest("button");
    if (!b) { if (!ev.target.closest("input")) $("rvPlayer").currentTime = Math.max(L.start - 0.05, 0); return; }
    const txt = row.querySelector(".tx");
    if (b.classList.contains("cut")) { setText(i, txt.value); L.cut = !L.cut; if (L.cut) L.del = false; drawRows(); }
    else if (b.classList.contains("del")) { setText(i, txt.value); L.del = !L.del; if (L.del) L.cut = false; drawRows(); }
    else if (b.classList.contains("join")) {
      if (i + 1 >= rv.lines.length) return;
      setText(i, txt.value); const N = rv.lines[i + 1];
      L.words = L.words.concat(N.words); L.end = N.end; L.cut = L.cut || N.cut; L.del = L.del && N.del;
      rv.lines.splice(i + 1, 1); drawRows();
    } else if (b.classList.contains("split")) {
      setText(i, txt.value);
      const caret = txt.selectionStart == null ? txt.value.length : txt.selectionStart;
      const k = txt.value.slice(0, caret).trim().split(/\s+/).filter(Boolean).length;
      if (k <= 0 || k >= L.words.length) { $("rvMsg").textContent = "Clique dentro do texto, entre duas palavras, e use ⎘ para dividir."; return; }
      const A = { start: L.start, end: L.words[k - 1].end, words: L.words.slice(0, k), cut: L.cut, del: L.del };
      const B = { start: L.words[k].start, end: L.end, words: L.words.slice(k), cut: L.cut, del: L.del };
      rv.lines.splice(i, 1, A, B); $("rvMsg").textContent = ""; drawRows();
    }
  });

  // legenda de previa sobre o player e linha em destaque
  $("rvPlayer").addEventListener("timeupdate", () => {
    const t = $("rvPlayer").currentTime; let idx = -1;
    for (let i = 0; i < rv.lines.length; i++) { if (t >= rv.lines[i].start - 0.05 && t <= rv.lines[i].end + 0.25) { idx = i; break; } }
    if (idx !== rv.cur) {
      rv.cur = idx; const rows = $("rvList").querySelectorAll(".row");
      rows.forEach((r, i) => r.classList.toggle("active", i === idx));
      const act = idx >= 0 ? rows[idx] : null; const ae = document.activeElement;
      if (act && !(ae && ae.closest && ae.closest("#rvList"))) act.scrollIntoView({ block: "nearest" });
    }
    const cap = $("rvCap");
    if (idx < 0 || rv.lines[idx].del || rv.lines[idx].cut) { cap.innerHTML = ""; return; }
    const ws = rv.lines[idx].words; let a = ws.findIndex(w => t >= w.start && t <= w.end); if (a < 0) a = ws.findIndex(w => w.start > t) - 1;
    if (a < 0) a = 0; const from = Math.floor(a / 3) * 3;
    cap.innerHTML = ws.slice(from, from + 3).map((w, k) => (from + k === a ? "<b>" : "") + esc(w.word) + (from + k === a ? "</b>" : "")).join(" ");
  });

  function collect() {
    const keep = rv.lines.filter(L => !L.del && !L.cut), cuts = rv.lines.filter(L => L.cut);
    const words = keep.flatMap(L => L.words.map(w => ({ word: w.word, start: w.start, end: w.end, ...(w.emph ? { emph: true } : {}) })));
    words.sort((a, b) => a.start - b.start);
    return { words, cuts: cuts.map(L => [L.start, L.end]), keep };
  }
  $("rvRender").addEventListener("click", () => {
    const c = collect();
    $("rvPlayer").pause();
    submit("edit", { reuse_job: rv.id, words: JSON.stringify(c.words), cut_ranges: JSON.stringify(c.cuts) });
  });
  $("rvSrt").addEventListener("click", async () => {
    const c = collect(); let n = 1;
    const srt = c.keep.map(L => (n++) + "\n" + fmtSrt(L.start) + " --> " + fmtSrt(L.end) + "\n" + L.words.map(w => w.word).join(" ") + "\n").join("\n");
    try { await navigator.clipboard.writeText(srt); $("rvMsg").textContent = "Legendas copiadas (.srt)."; } catch (e) { $("rvMsg").textContent = "Não consegui copiar."; }
  });
  $("rvPlayer").addEventListener("error",()=>{$("rvProxy").classList.remove("hidden");$("rvMsg").textContent="Este formato precisa de uma prévia leve para o navegador. A transcrição salva será reutilizada.";});
  $("rvProxy").addEventListener("click",()=>submit("review"));
  $("rvLast").addEventListener("click",()=>{if(state.lastExport)done(state.lastExport);});
  $("rvBack").addEventListener("click", () => { $("rvPlayer").pause(); show("viewEmpty"); });

  function done(j) {
    if (j.result && j.result.kind === "review") { showReview(j); return; }
    if (j.result && j.result.kind === "analysis") { showAnalysis(j); return; }
    state.baseSettings={...j.result.settings};
    state.lastExport=j;$("rvLast").disabled=false;
    const r = j.result; const id = j.id || state.savedJob;
    show("viewDone");
    const p = $("player"); p.src = "/api/jobs/" + id + "/video?t=" + Date.now();
    $("dl").href = "/api/jobs/" + id + "/download";
    const st = r.stats;
    $("stats").innerHTML = [
      ["Duração final", fmtTime(st.final_duration)], ["Duração original", fmtTime(st.original_duration)],
      ["Trechos mantidos", st.cuts], ["Palavras", st.words], ["Tamanho", st.size], ["Imagens", r.images.length]
    ].map(a => `<div class="stat"><b>${a[1]}</b>${a[0]}</div>`).join("");
    $("imgPlan").innerHTML = r.images.length ? `<table><tr><th>Imagem</th><th>Entra em</th><th>Duração</th><th>Modo</th><th>Animação</th></tr>` +
      r.images.map(i => `<tr><td>${esc(i.image)}</td><td>${String(i.start).replace(".", ",")} s</td><td>${i.duration}s</td><td>${i.mode === "full" ? "tela cheia" : "cartão"}</td><td>${esc(i.animation)}</td></tr>`).join("") + "</table>" : "";
    if (window.renderStudioReport) window.renderStudioReport(r);
    state.job = null; refreshGo();
  }

  $("again").addEventListener("click", () => { $("player").pause(); openReview(); });
  $("openFolder").addEventListener("click", async () => {
    try { const r = await (await fetch("/api/open-output", { method: "POST" })).json(); if (!r.ok && r.path) alert("Pasta de saída: " + r.path); } catch (e) {}
  });
  let saveTimer=null, saveQueue=Promise.resolve(true), dirty=false;
  const preferences=()=>Object.fromEntries([...FIELDS,...CHECKS,"prompt"].map(k=>[k,CHECKS.includes(k)?$(k).checked:$(k).value]));
  function scheduleSave(){if(!state.savedJob)return;dirty=true;$("saveStatus").textContent="Salvando alterações…";clearTimeout(saveTimer);saveTimer=setTimeout(flushProject,500);}
  function flushProject(){
    clearTimeout(saveTimer); if(!state.savedJob||!dirty)return saveQueue;
    const id=state.savedJob, data={preferences:preferences()};
    if(rv.id===id)data.lines=rv.lines;
    const body=JSON.stringify(data);store.set("editorDraft:"+id,body);dirty=false;
    saveQueue=saveQueue.catch(()=>false).then(async()=>{
      try{const res=await fetch("/api/jobs/"+id+"/project",{method:"PUT",headers:{"Content-Type":"application/json"},body});if(!res.ok)throw Error();
        if(store.get("editorDraft:"+id)===body)store.set("editorDraft:"+id,"");$("saveStatus").textContent="Legendas e ajustes salvos neste computador.";return true;
      }catch(_){dirty=true;$("saveStatus").textContent="Não foi possível salvar no servidor. Rascunho protegido neste navegador; tente novamente.";return false;}
    });return saveQueue;
  }
  async function syncAssets(id){
    const r=await fetch("/api/jobs/"+id+"/project");if(!r.ok)return null;const p=await r.json();
    state.images=p.images;state.music=p.music?{name:p.music}:null;state.musicRemoved=false;renderThumbs();
    $("musicFile").classList.toggle("hidden",!p.music);$("musicEmpty").classList.toggle("hidden",!!p.music);$("musicName").textContent=p.music||"";return p;
  }
  async function refreshProjects(){try{const list=await(await fetch("/api/projects")).json();$("projectSelect").innerHTML='<option value="">Abrir um projeto…</option>'+list.map(p=>'<option value="'+p.id+'">'+esc(p.name)+' · '+new Date(p.created*1000).toLocaleString('pt-BR',{dateStyle:'short',timeStyle:'short'})+'</option>').join('');$("projectSelect").value=state.savedJob||"";}catch(_){}}
  async function openReview(){
    if(state.job)return;
    if(state.savedJob){
      if(!(await flushProject()))return;
      try{const p=await(await fetch("/api/jobs/"+state.savedJob+"/project")).json();if(p.lines!==null&&p.lines!==undefined){showReview({id:state.savedJob,result:{lines:p.lines}});return;}}catch(_){}
    }
    submit("review");
  }
  async function restoreProject(id){
    if(state.job||!(await flushProject()))return;
    try{
      const p=await syncAssets(id);if(!p)throw Error("Projeto indisponível");
      document.dispatchEvent(new CustomEvent("studio:reset"));
      state.lastExport=p.job.status==="done" && !p.job.result?.kind?p.job:null;$("rvLast").disabled=!state.lastExport;
      document.body.classList.add("has-project");
      state.savedJob=id;store.set("editorProject",id);state.video={name:p.job.name};rv.id=null;rv.lines=[];
      const draft=JSON.parse(store.get("editorDraft:"+id)||"null");
      state.baseSettings={...p.settings};
      const prefs=draft?.preferences||p.preferences||{...p.settings,prompt:p.prompt};
      for(const [k,v] of Object.entries(prefs)){if(!$(k)||k==='api_key')continue;if(CHECKS.includes(k))$(k).checked=!!v;else $(k).value=v;}
      if(prefs.active_color && !p.preferences)$("use_color").checked=true;
      if(prefs.font && !$("font").value){const opt=new Option(prefs.font,prefs.font);$("font").add(opt);$("font").value=prefs.font;}
      savePrefs();$("subtitle_style").dispatchEvent(new Event("input"));
      $("videoEmpty").classList.add("hidden");$("videoFile").classList.remove("hidden");$("videoName").textContent=p.job.name;$("videoMeta").textContent="Arquivo salvo · pronto para continuar";$("videoThumb").src=p.source_url;
      $("projectStatus").textContent=p.job.name+" · projeto local";
      document.dispatchEvent(new CustomEvent("studio:video",{detail:{url:p.source_url,file:state.video}}));
      const lines=draft?.lines||p.lines;
      if(["running","queued"].includes(p.job.status)){state.job=id;state.mode=p.job.mode;show("viewWork");startPolling();}
      else if(lines!==null&&lines!==undefined)showReview({id,result:{lines}});
      else show("viewEmpty");
      if(draft){dirty=true;await flushProject();}else $("saveStatus").textContent="Projeto recuperado do disco.";
      refreshGo();refreshProjects();document.dispatchEvent(new CustomEvent("studio:job",{detail:p.job}));
    }catch(e){$("saveStatus").textContent="Não consegui abrir o projeto: "+e.message;}
  }
  $("projectSelect").addEventListener("change",()=>{if($("projectSelect").value)restoreProject($("projectSelect").value);});
  document.addEventListener("change",e=>{if([...FIELDS,...CHECKS,"prompt"].includes(e.target.id)){if(e.target.id==="prompt")state.baseSettings={};else if(e.target.value==="auto")delete state.baseSettings[e.target.id];savePrefs();scheduleSave();}});
  window.addEventListener("beforeunload",()=>{if(dirty&&state.savedJob){const data={preferences:preferences()};if(rv.id===state.savedJob)data.lines=rv.lines;store.set("editorDraft:"+state.savedJob,JSON.stringify(data));}});
  refreshProjects();setTimeout(()=>{const id=store.get("editorProject");if(id)restoreProject(id);},0);
  ["prompt"].forEach(k => $(k).addEventListener("change", savePrefs));
  refreshGo();
})();

(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const portrait = $('portrait'), caption = $('demoCaption'), video = $('studioVideo');
  const safe = value => String(value == null ? '' : value).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  const time = seconds => { const s = Math.max(0, Math.floor(Number(seconds) || 0)); return String(Math.floor(s/60)).padStart(2,'0') + ':' + String(s%60).padStart(2,'0'); };
  const phrases = [['UMA','IDEIA','MUDA','TUDO.'],['SUA','VOZ','EM','MOVIMENTO.'],['CRIE','ALGO','QUE','CONECTA.']];
  const presets = {
    hormozi:{font:'Impact',animation:'spring',color:'#ffe600'},
    editorial:{font:'Georgia',animation:'smooth',color:'#d5e4bf'},
    creator:{font:'Segoe UI',animation:'smooth',color:'#c4ef79'},
    cinetico:{font:'Impact',animation:'punch',color:'#b6f16a'},
    verde:{color:'#9bff65'},neon:{color:'#51f2e2'},caixa:{color:'#c4ef79'},suave:{color:'#d5e4bf'}
  };
  let playing = !matchMedia('(prefers-reduced-motion: reduce)').matches, tick = 0, hasVideo = false, activeView = 'viewEmpty', sourceRatio = 9/16;
  const fontRecords = new Map(), loadedFaces = new Map();
  function previewFont() {
    const selected = $('font').value, option = $('font').selectedOptions[0];
    const record = fontRecords.get(selected);
    if (!selected || selected === 'auto') return (presets[model()] || presets.hormozi).font || (model() === 'suave' ? 'Segoe UI' : 'Impact');
    if (!record || !record.url || !window.FontFace) return option?.dataset.family || record?.family || selected;
    if (!loadedFaces.has(selected)) {
      loadedFaces.set(selected, null);
      const alias = 'preview_' + String(record.id || selected).replace(/[^a-zA-Z0-9_]/g,'_');
      const face = new FontFace(alias, 'url(' + JSON.stringify(record.url) + ')');
      face.load().then(loaded => { document.fonts.add(loaded); loadedFaces.set(selected,alias); if ($('font').value === selected) updateSettings(); }).catch(() => { $('fontStatus').textContent = 'PRÉVIA DO SISTEMA'; });
    }
    return loadedFaces.get(selected) || record.family || record.name;
  }
  const model = () => $('subtitle_style').value === 'auto' ? 'hormozi' : $('subtitle_style').value;
  function renderCaption() {
    if(window.projectTimelineActive)return;
    const words = phrases[Math.floor(tick/12)%phrases.length], current = Math.floor(tick/3)%4;
    const editorial = ['editorial','creator','suave'].includes(model());
    caption.innerHTML = [0,2].map(start => '<span class="cap-line">' + words.slice(start,start+2).map((word,i) => '<span class="cap-word' + (start+i===current?' is-active':'') + '">' + safe(editorial ? word.toLocaleLowerCase('pt-BR') : word) + '</span>').join(' ') + '</span>').join('');
  }
  function setPlayState() {
    portrait.classList.toggle('is-paused',!playing);
    $('demoPlay').textContent = playing ? 'Ⅱ' : '▶';
    $('demoPlay').setAttribute('aria-label',playing?'Pausar demonstração':'Reproduzir demonstração');
    if (hasVideo && playing && activeView==='viewEmpty') video.play().catch(()=>{}); else video.pause();
  }
  function updateSettings() {
    const style = model(), custom = $('use_color').checked;
    caption.className = 'demo-caption style-' + style + ' anim-' + $('caption_animation').value;
    caption.style.fontFamily = JSON.stringify(previewFont()) + ', sans-serif';
    $('rvCap').style.fontFamily=caption.style.fontFamily; $('rvCap').style.fontSize=(22*Math.min(1,Math.max(140,$('rvPlayer').clientWidth)/280)*Number($('font_scale').value))+'px';
    $('rvCap').style.bottom=$('subtitle_position').value==='centro'?'46%':'16%';
    $('rvCap').style.setProperty('--rv-accent',custom ? $('active_color').value : (presets[style]||presets.hormozi).color);
    $('rvCap').classList.toggle('hidden',!$('subtitles').checked);
    portrait.style.setProperty('--caption-size',$('font_scale').value);
    portrait.style.setProperty('--cap-accent',custom ? $('active_color').value : (presets[style]||presets.hormozi).color);
    caption.style.top = $('subtitle_position').value==='centro' ? '50%' : ($('subtitle_position').value==='baixo'?'76%':'65%');
    caption.classList.toggle('hidden',!$('subtitles').checked);
    ['off','subtle','balanced','bold'].forEach(m => portrait.classList.toggle('motion-'+m,$('motion_intensity').value===m));
    portrait.classList.toggle('no-camera-motion',!$('punch_zoom').checked);
    $('motionCard').classList.toggle('is-visible',!window.projectTimelineActive && $('motion_intensity').value!=='off' && tick%36>=18 && tick%36<30);
    const value = Math.round(Number($('font_scale').value)*100);
    $('fontScaleValue').textContent = value+'%';
    $('font_scale').style.background = 'linear-gradient(90deg,#a5cb73 ' + ((Number($('font_scale').value)-.7)/.7*100) + '%,#36432f 0)';
    $('colorHex').textContent = $('active_color').value.toUpperCase();
    const hints={off:'Destaques gráficos desativados. O zoom entre cortes é independente.',subtle:'Destaques gráficos discretos a partir da fala.',balanced:'Destaques gráficos a partir da fala, com intensidade equilibrada.',bold:'Destaques gráficos expressivos a partir da fala.'};
    $('motionHint').textContent=hints[$('motion_intensity').value];
    document.querySelectorAll('.style-tile').forEach(tile=>{const selected=tile.dataset.style===style;tile.classList.toggle('selected',selected);tile.setAttribute('aria-pressed',String(selected));});
    const ratioValue=$('aspect').value;
    const ratio=ratioValue==='original'?sourceRatio:({'1:1':1,'4:5':.8,'16:9':16/9}[ratioValue]||9/16);
    portrait.style.aspectRatio=String(ratio);
    portrait.classList.toggle('is-wide',ratio>.57);
    $('portrait').querySelector('.portrait-meta span:last-child').textContent=ratioValue==='auto'?'9:16 · DEMO':ratioValue==='original'?'ORIGINAL':ratioValue;
    $('exportFormat').innerHTML='MP4 <b>↑</b>';
    renderCaption();
  }
  document.querySelectorAll('.style-tile').forEach(tile=>tile.addEventListener('click',()=>{
    const style=tile.dataset.style, preset=presets[style];
    $('subtitle_style').value=style;
    $('font').value='auto';
    $('caption_animation').value=preset.animation;
    tick=0;updateSettings();
    $('subtitle_style').dispatchEvent(new Event('change',{bubbles:true}));
  }));
  const liveControls=['subtitle_style','font','caption_animation','font_scale','subtitle_position','motion_intensity','active_color','use_color','subtitles','aspect','punch_zoom'];
  liveControls.forEach(id=>$(id).addEventListener('input',updateSettings));
  document.addEventListener('change',()=>{
    const values={};
    try{Object.assign(values,JSON.parse(localStorage.getItem('editorPrefs')||'{}'));}catch(_){} delete values.api_key;
    document.querySelectorAll('input:not([type=file]),select,textarea#prompt').forEach(el=>{if(el.id && el.id!=='api_key')values[el.id]=el.type==='checkbox'?el.checked:el.value;});
    try{localStorage.setItem('editorPrefs',JSON.stringify(values));}catch(_){}
  });
  ['dropVideo','dropImages','dropMusic'].forEach(id=>$(id).addEventListener('keydown',event=>{if((event.key==='Enter'||event.key===' ')&&event.target===$(id)){event.preventDefault();$(id).click();}}));
  $('demoPlay').addEventListener('click',()=>{playing=!playing;setPlayState();});
  $('demoSound').addEventListener('click',()=>{video.muted=!video.muted;$('demoSound').textContent=video.muted?'♪':'♫';$('demoSound').setAttribute('aria-label',video.muted?'Ativar som do vídeo':'Silenciar vídeo');$('demoSound').title=video.muted?'Ativar som':'Silenciar';});
  document.addEventListener('studio:video',event=>{
    hasVideo=true;video.src=event.detail.url;video.classList.remove('hidden');$('demoArt').classList.add('hidden');$('sourceLabel').textContent='SEU VÍDEO · DEMO';$('demoSound').disabled=false;playing=true;
    $('demoSound').title='Ativar som';$('previewNote').innerHTML='<span class="status-dot"></span>Estilo demonstrativo sobre o vídeo original. A fala e os cortes são sincronizados na exportação.';
    video.onloadedmetadata=()=>{sourceRatio=video.videoWidth/video.videoHeight||9/16;updateSettings();setPlayState();};
    video.onerror=()=>{$('previewNote').textContent='Este formato não toca no navegador. O arquivo pode ser enviado para edição; a prévia de estilo continua disponível.';video.classList.add('hidden');$('demoArt').classList.remove('hidden');};
    setPlayState();
  });
  video.addEventListener('timeupdate',()=>{$('previewTime').innerHTML=time(video.currentTime)+' <span>/ '+time(video.duration)+'</span>';});
  document.addEventListener('studio:view',event=>{
    activeView=event.detail;
    $('previewBadge').textContent=({viewEmpty:'DEMONSTRAÇÃO',viewWork:'PROCESSANDO',viewDone:'EXPORTADO',viewReview:'REVISÃO',viewAnalysis:'ANÁLISE'})[activeView]||'PRÉVIA';
    if(activeView!=='viewReview')$('rvPlayer').pause();if(activeView!=='viewDone')$('player').pause();setPlayState();
  });
  setInterval(()=>{if(playing&&activeView==='viewEmpty'&&!document.hidden){tick++;if(tick%3===0)renderCaption();$('motionCard').classList.toggle('is-visible',$('motion_intensity').value!=='off' && tick%36>=18 && tick%36<30);if(!hasVideo)$('previewTime').innerHTML=time((tick/6)%6)+' <span>/ DEMO</span>';}},170);
  window.renderStudioReport=result=>{
    const report=$('renderInfo'),info=result.render_info;if(!report||!info)return;
    const engineNames={hyperframes:'HyperFrames · animadas',ass_animated:'FFmpeg · animadas',ass:'FFmpeg · simples',disabled:'Desativadas',none:'Sem imagens',ffmpeg:'FFmpeg'};
    const rows=[['Legendas',engineNames[info.captions]||info.captions],['Imagens',engineNames[info.cards]||info.cards],['Fonte utilizada',info.font],['Eventos de movimento',info.motion_events]];
    report.className='render-report';
    report.innerHTML='<h3>Aplicado na exportação</h3>'+rows.filter(r=>r[1]!=null).map(r=>'<div class="render-line"><span>'+safe(r[0])+'</span><b>'+safe(r[1])+'</b></div>').join('')+(info.warnings||[]).map(w=>'<p class="render-warning">'+safe(w)+'</p>').join('');
    if(result.motion_plan && result.motion_plan.length){const detail=document.createElement('details');detail.className='motion-events';detail.innerHTML='<summary>Ver plano de movimentos · '+result.motion_plan.length+' eventos</summary><div>'+result.motion_plan.map(event=>'<div class="motion-event"><time>'+time(event.start)+'</time><span>'+safe(event.label||event.text||event.type||'Movimento')+(event.animation?' · '+safe(event.animation):'')+'</span></div>').join('')+'</div>';report.appendChild(detail);}
  };
  fetch('/api/fonts').then(response=>{if(!response.ok)throw Error('Fontes locais');return response.json();}).then(data=>{
    const fonts=Array.isArray(data)?data:(data.fonts||[]);if(!fonts.length)return;
    let selected=$('font').value;
    if (!selected) { try { selected=JSON.parse(localStorage.getItem('editorPrefs')||'{}').font; } catch(_) {} }
    $('font').innerHTML='<option value="auto">Padrão do estilo</option>';
    fonts.forEach(font=>{
      const id=font.id||font.family||font.name; fontRecords.set(id,font);
      const option=document.createElement('option');option.value=id;option.dataset.family=font.family||font.name;option.textContent=font.name||font.family||font.id;$('font').appendChild(option);
    });
    const match=fonts.find(font=>(font.id||font.family||font.name)===selected||font.family===selected);
    $('font').value=match?(match.id||match.family||match.name):'auto';
    $('fontStatus').textContent=fonts.length+' FONTES';updateSettings();
  }).catch(()=>{$('fontStatus').textContent='FONTES DO SISTEMA';});
  updateSettings();setPlayState();
})();
