"""Limpeza inteligente da fala: acha o que deve sair do video antes de cortar as pausas.

Detecta, usando as palavras com tempo do Whisper:
  - tomadas repetidas (a pessoa errou, parou e falou a frase de novo): sai a tentativa errada;
  - gagueira e palavra cortada ("o o neto", "pre- precisa");
  - recomeco no meio da frase ("o neto precisa o neto precisa provar");
  - vicios de som (eh, ahn, hum);
  - conversa de gravacao ("pera ai", "vou repetir", "pode cortar");
  - trechos fora do assunto (comparando com o roteiro/pedido; com uma chave da Anthropic, a IA decide).

Cada achado volta com o motivo, para o usuario ver o que foi cortado e por que."""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher


def norm(s: str) -> str:
    s = unicodedata.normalize("NFD", str(s).lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9 ]+", "", s).strip()


STOP = set(norm(w) for w in """
de da do das dos a o as os e em um uma uns umas que para pra por com no na nos nas se ao aos eu voce vc ele ela
eles elas meu minha seu sua ja nao mais muito mas ou como quando esta esse essa isso este ser ter foi sao tem vai
vem entao ai la ca so tambem ate sobre entre depois antes the and of to in is it for on
""".split())

FILLERS = {"eh", "ehh", "eee", "ahn", "ahnn", "hum", "hmm", "hm", "humm", "uhm", "uh", "aa", "aaa", "ee"}

META = re.compile(
    r"\b(vou repetir|vamos de novo|vou de novo|vou falar de novo|comecar de novo|vou comecar de novo|pode cortar|"
    r"corta essa|corta isso|errei|erro meu|pera ai|perai|espera ai|esqueci o que|como e que eu falo)\b")


def _tok(w):
    return norm(w["word"]).replace(" ", "")


def _phrases(words, gap=0.45):
    out, s = [], 0
    for i, w in enumerate(words):
        last = i == len(words) - 1
        if last or words[i + 1]["start"] - w["end"] > gap or w["word"].rstrip()[-1:] in ".!?…":
            out.append((s, i))
            s = i + 1
    return out


def _item(words, i0, i1, reason, kind, conf):
    return {"i0": i0, "i1": i1, "start": words[i0]["start"], "end": words[i1]["end"], "reason": reason,
            "kind": kind, "conf": conf, "text": " ".join(w["word"] for w in words[i0:i1 + 1])}


# ------------------------------------------------------------------ tomadas erradas

def find_takes(words):
    """Repeticoes, gagueira, recomecos e conversa de gravacao."""
    items = []
    toks = [_tok(w) for w in words]

    # gagueira e palavra cortada
    for i in range(len(words) - 1):
        a, b = toks[i], toks[i + 1]
        if not a or not b or words[i + 1]["start"] - words[i]["end"] > 0.8:
            continue
        if a == b and len(a) <= 3 and not a.isdigit():
            items.append(_item(words, i, i, "palavra repetida (gagueira)", "repeticao", "alta"))
        elif (len(a) >= 2 and a not in STOP and b.startswith(a) and len(b) >= len(a) + 2
              and words[i]["end"] - words[i]["start"] <= 0.45):
            items.append(_item(words, i, i, "palavra cortada no meio", "erro", "alta"))

    ph = _phrases(words)
    ptoks = [[t for t in toks[a:b + 1] if t] for a, b in ph]

    # recomeco dentro da mesma frase: "X Y Z ... X Y"
    for (a, b), t in zip(ph, ptoks):
        n = len(t)
        i = 0
        while i < n - 2:
            found = None
            for j in range(i + 2, min(n - 1, i + 9)):
                if t[i] == t[j] and t[i + 1] == t[j + 1] and not (t[i] in STOP and t[i + 1] in STOP):
                    found = j
            if found:
                items.append(_item(words, a + i, a + found - 1, "recomeço da frase", "repeticao", "alta"))
                i = found
            else:
                i += 1

    # tomada repetida: a frase e dita de novo logo depois
    for k, (a, b) in enumerate(ph):
        ta = ptoks[k]
        if len(ta) < 2:
            continue
        for j in range(k + 1, min(k + 3, len(ph))):
            c, d = ph[j]
            tb = ptoks[j]
            if len(tb) < 2 or words[c]["start"] - words[b]["end"] > 6.0:
                continue
            head = ta[:2] == tb[:2] and not (ta[0] in STOP and ta[1] in STOP)
            ratio = SequenceMatcher(None, ta, tb).ratio() if len(ta) >= 3 and len(tb) >= 3 else 0.0
            if head or ratio >= 0.6:
                if len(tb) < 0.5 * len(ta) and words[b]["word"].rstrip()[-1:] in ".!?…":
                    items.append(_item(words, c, d, "tomada incompleta (manteve a frase completa)", "repeticao", "media"))
                else:
                    items.append(_item(words, a, b, "tomada repetida (manteve a última)", "repeticao", "alta"))
                break

    # vicios de som
    for i, t in enumerate(toks):
        if t in FILLERS:
            items.append(_item(words, i, i, "vício de fala", "vicio", "alta"))

    # conversa de gravacao
    for a, b in ph:
        if b - a + 1 <= 12 and META.search(" ".join(t for t in (norm(w["word"]) for w in words[a:b + 1]))):
            items.append(_item(words, a, b, "comentário de gravação", "erro", "alta"))
    return items


# ------------------------------------------------------------------ fora do assunto

def _stems(text: str):
    out = set()
    for t in norm(text).split():
        if len(t) >= 4 and t not in STOP and not t.isdigit():
            out.add(t[:5])
    return out


def find_offtopic(words, topic: str):
    """Trechos longos sem nenhuma palavra em comum com o roteiro/pedido (heuristica prudente)."""
    topic_stems = _stems(topic)
    if len(topic_stems) < 6:
        return []
    ph = _phrases(words, gap=0.6)
    flags = []  # True = sem relacao, False = relacionado, None = neutro (poucas palavras de conteudo)
    for a, b in ph:
        content = [t[:5] for t in (norm(w["word"]) for w in words[a:b + 1])
                   if len(t) >= 4 and t not in STOP and not t.isdigit()]
        if len(content) < 3:
            flags.append(None)
        else:
            flags.append(not any(c in topic_stems for c in content))
    items, k = [], 0
    while k < len(ph):
        if flags[k] is True:
            j = k
            while j + 1 < len(ph) and flags[j + 1] in (True, None):
                j += 1
            while flags[j] is None:
                j -= 1
            a, b = ph[k][0], ph[j][1]
            if b - a + 1 >= 8 and words[b]["end"] - words[a]["start"] >= 2.5:
                items.append(_item(words, a, b, "fora do assunto do roteiro", "fora_do_assunto", "media"))
            k = j + 1
        else:
            k += 1
    return items


# ------------------------------------------------------------------ comparacao com o roteiro

def spoken_script(script: str = "", prompt: str = "") -> str:
    """Texto que a pessoa deveria falar: o roteiro, ou as falas entre aspas dentro do pedido."""
    if script and script.strip():
        return script
    text = (prompt or "").replace("“", '"').replace("”", '"')
    quotes = [m.group(1) for m in re.finditer(r'"([^"\n]*)"', text)]
    # falas sao frases longas em minusculas; textos de tela costumam ser curtos e em CAIXA ALTA
    spoken = [q for q in quotes if len(q) >= 25 and re.search(r"[a-zà-ú]{3}", q)]
    return "\n".join(spoken)


def _stem_list(text):
    return [t[:5] for t in norm(text).split() if len(t) >= 3 and t not in STOP and not t.isdigit()] + \
           [t for t in norm(text).split() if t.isdigit()]


def find_offscript(words, script: str):
    """Frases que nao estao no roteiro (improviso, comentario, erro) e tomadas repetidas do mesmo trecho.

    So age quando o video segue o roteiro de verdade (a maior parte da fala bate com ele)."""
    sstems = _stem_list(script)
    if len(sstems) < 12 or not words:
        return []
    sset = set(sstems)
    ph = _phrases(words, gap=0.45)
    info = []
    total = hit = 0
    for a, b in ph:
        stems = []
        for w in words[a:b + 1]:
            t = norm(w["word"])
            for tok in t.split():
                if tok.isdigit():
                    stems.append(tok)
                elif len(tok) >= 3 and tok not in STOP:
                    stems.append(tok[:5])
        m = sum(1 for x in stems if x in sset)
        total += len(stems)
        hit += m
        # posicao no roteiro: onde os trechos em comum (2+ palavras seguidas) caem
        blocks = [bl for bl in SequenceMatcher(None, stems, sstems, autojunk=False).get_matching_blocks()
                  if bl.size >= 2]
        span = (blocks[0].b, blocks[-1].b + blocks[-1].size) if blocks else None
        info.append({"a": a, "b": b, "n": len(stems), "m": m, "span": span, "stems": stems})
    if total == 0 or hit / total < 0.45:  # a fala nao segue o roteiro: melhor nao mexer
        return []
    items = []
    for k, it in enumerate(info):
        a, b = it["a"], it["b"]
        cov = it["m"] / it["n"] if it["n"] else 1.0
        if it["n"] >= 2 and cov < 0.35:
            items.append(_item(words, a, b, "fora do roteiro", "fora_do_assunto", "media"))
        elif it["n"] == 1 and cov == 0 and b - a + 1 <= 2:
            items.append(_item(words, a, b, "palavra solta fora do roteiro", "fora_do_assunto", "media"))
        elif it["span"]:
            # o mesmo trecho do roteiro e dito de novo logo depois: fica a ultima tomada
            for nxt in info[k + 1:k + 4]:
                if not nxt["span"] or words[nxt["a"]]["start"] - words[b]["end"] > 15:
                    continue
                s0, e0 = it["span"]
                s1, e1 = nxt["span"]
                inter = min(e0, e1) - max(s0, s1)
                same = SequenceMatcher(None, it["stems"], nxt["stems"], autojunk=False).ratio()
                if inter > 0 and inter >= 0.6 * min(e0 - s0, e1 - s1) and same >= 0.65:
                    items.append(_item(words, a, b, "tomada repetida do roteiro (manteve a última)", "repeticao", "alta"))
                    break
    return items


LLM_SYSTEM = """Voce e um editor de video experiente. Recebe a transcricao de uma gravacao dividida em linhas numeradas e o assunto/roteiro do video.
Marque as linhas que devem ser CORTADAS. Responda SOMENTE com JSON: {"cut":[{"id":3,"kind":"erro|repeticao|fora_do_assunto","reason":"motivo curto em portugues"}]}
Marque:
- erro: a pessoa se enganou, se corrigiu ou comentou a gravacao ("pera ai", "vou repetir"); marque a versao errada, nunca a corrigida;
- repeticao: a mesma frase foi gravada mais de uma vez; marque as tomadas piores e mantenha a melhor (normalmente a ultima completa);
- fora_do_assunto: falas que nao combinam com a proposta do video (conversa paralela, historias sem relacao, pedidos para a equipe).
Seja conservador: na duvida NAO marque. Nunca marque o gancho do inicio nem a chamada final para acao. Se nada deve ser cortado, responda {"cut":[]}."""


def llm_review(api_key, words, topic, log=None):
    from .planner import _llm_json
    ph = []
    for a, b in _phrases(words, gap=0.6):
        while b - a + 1 > 18:  # frases longas viram mais de uma linha
            ph.append((a, a + 17)); a += 18
        ph.append((a, b))
    lines = [f"{n}. [{words[a]['start']:.1f}s] " + " ".join(w["word"] for w in words[a:b + 1]) for n, (a, b) in enumerate(ph)]
    user = f"Assunto/roteiro do video:\n{topic.strip() or '(nao informado: considere apenas erros e repeticoes)'}\n\nTranscricao:\n" + "\n".join(lines)
    data = _llm_json(api_key, LLM_SYSTEM, user, log=log, max_tokens=1800)
    if not isinstance(data, dict) or not isinstance(data.get("cut"), list):
        return None
    items = []
    for c in data["cut"]:
        try:
            n = int(c["id"])
            a, b = ph[n]
        except (KeyError, ValueError, IndexError, TypeError):
            continue
        kind = c.get("kind") if c.get("kind") in ("erro", "repeticao", "fora_do_assunto") else "erro"
        items.append(_item(words, a, b, "IA: " + str(c.get("reason") or "não combina")[:80], kind, "alta"))
    return items


# ------------------------------------------------------------------ juncao

def analyze_words(words, topic="", cfg=None, api_key=None, log=None, script=""):
    """Retorna os trechos que devem sair, sem sobreposicao, em ordem de tempo."""
    cfg = {"takes": True, "fillers": True, "offtopic": True, **(cfg or {})}
    if not words:
        return []
    found = []
    if cfg["takes"] or cfg["fillers"]:
        for it in find_takes(words):
            if it["kind"] == "vicio" and not cfg["fillers"]:
                continue
            if it["kind"] != "vicio" and not cfg["takes"]:
                continue
            found.append(it)
    ai = None
    if api_key and (cfg["takes"] or cfg["offtopic"]):
        ai = llm_review(api_key, words, topic, log=log)
        if ai is not None and log:
            log(f"IA revisou a transcrição: {len(ai)} trecho(s) para cortar.")
        for it in ai or []:
            if it["kind"] == "fora_do_assunto" and not cfg["offtopic"]:
                continue
            if it["kind"] != "fora_do_assunto" and not cfg["takes"]:
                continue
            found.append(it)
    if cfg["offtopic"] and ai is None and topic.strip():
        off = find_offscript(words, spoken_script(script, topic)) if (script or topic) else []
        found += off if off else find_offtopic(words, topic)
    found.sort(key=lambda x: (x["i0"], -(x["i1"] - x["i0"])))
    merged = []
    for it in found:
        if merged and it["i0"] <= merged[-1]["i1"]:
            if it["i1"] > merged[-1]["i1"]:
                merged[-1] = _item(words, merged[-1]["i0"], it["i1"], merged[-1]["reason"], merged[-1]["kind"], merged[-1]["conf"])
            continue
        merged.append(it)
    # nunca corta o video inteiro: se sobrar menos de 30% das palavras, a deteccao provavelmente errou
    cut_words = sum(m["i1"] - m["i0"] + 1 for m in merged)
    if cut_words > 0.7 * len(words):
        if log:
            log("A limpeza marcaria quase tudo; ignorei por segurança.")
        return []
    return merged


def to_cut_ranges(words, items, duration=None):
    """Converte os achados em intervalos de tempo (s, e), sem invadir as palavras vizinhas mantidas."""
    drop = set()
    for it in items:
        drop.update(range(it["i0"], it["i1"] + 1))
    out = []
    for it in items:
        prev_end = max((words[i]["end"] for i in range(it["i0"]) if i not in drop), default=0.0)
        nxt = min((words[i]["start"] for i in range(it["i1"] + 1, len(words)) if i not in drop),
                  default=duration if duration else words[it["i1"]]["end"] + 0.3)
        a = max(it["start"] - 0.02, prev_end)
        b = min(it["end"] + 0.04, nxt)
        if b > a:
            out.append((round(a, 3), round(b, 3)))
    return out
