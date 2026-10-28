"""Busca efeitos sonoros REAIS (gravacoes com licenca livre) na API do Openverse e baixa com os creditos.

Uso:
  python buscar_sons.py "whoosh" --n 8 --out sons/whoosh
  python buscar_sons.py "camera shutter" --n 5 --out sons/shutter --licencas cc0      # so dominio publico
  python buscar_sons.py "paper page turn" --n 6 --out sons/papel --rank "a single paper page turning"

Por padrao aceita apenas licencas que permitem uso comercial sem obrigar a mesma licenca: CC0, PDM e CC BY.
(NC, ND e SA ficam fora, porque o video e publicado em perfil comercial.)
Cada arquivo vira WAV 48 kHz e entra em <out>/manifest.json com titulo, autor, licenca e pagina de origem.
<out>/CREDITOS.txt traz as linhas de credito para colar na legenda do post quando a licenca for CC BY.
Com --rank, usa o earshot (se instalado) para ordenar os arquivos pela descricao do som.
A API funciona sem chave (com limite de requisicoes). Para mais volume, registre um app gratuito no Openverse
e passe o token em OPENVERSE_TOKEN."""
import argparse, json, os, re, subprocess, sys, time, urllib.parse, urllib.request
from pathlib import Path

API = "https://api.openverse.org/v1/audio/"

def get(url, binary=False):
    req = urllib.request.Request(url, headers={"User-Agent": "EditorVideoIA/1.0 (sound sourcing)"})
    if os.environ.get("OPENVERSE_TOKEN"):
        req.add_header("Authorization", "Bearer " + os.environ["OPENVERSE_TOKEN"])
    with urllib.request.urlopen(req, timeout=40) as r:
        data = r.read()
    return data if binary else json.loads(data)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("busca"); ap.add_argument("--n", type=int, default=8); ap.add_argument("--out", required=True)
    ap.add_argument("--licencas", default="cc0,pdm,by"); ap.add_argument("--max-seg", type=float, default=12.0)
    ap.add_argument("--categoria", default="sound_effect", help="sound_effect, music, audiobook, podcast... ou vazio")
    ap.add_argument("--rank", default=None, help="descricao do som para ordenar com earshot")
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    q = {"q": a.busca, "license": a.licencas, "page_size": 40, "mature": "false"}
    if a.categoria: q["category"] = a.categoria
    res = get(API + "?" + urllib.parse.urlencode(q)).get("results", [])
    man_path = out / "manifest.json"
    man = json.loads(man_path.read_text(encoding="utf-8")) if man_path.exists() else []
    have = {m["id"] for m in man}
    got = 0
    for r in res:
        if got >= a.n: break
        dur = (r.get("duration") or 0) / 1000
        if r["id"] in have or not r.get("url") or (dur and dur > a.max_seg): continue
        lic = (r.get("license") or "").lower()
        if any(x in lic for x in ("nc", "nd", "sa", "sampling")): continue
        slug = re.sub(r"[^a-z0-9]+", "-", (r.get("title") or "som").lower()).strip("-")[:40] or "som"
        raw = out / f"ov-{r['id'][:8]}_{slug}.src"; wav = raw.with_suffix(".wav")
        try:
            raw.write_bytes(get(r["url"], binary=True)); time.sleep(0.6)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-ar", "48000", "-ac", "2", str(wav)], check=True)
            raw.unlink()
        except Exception as exc:
            print("  pulei", r.get("title"), "->", exc); raw.unlink(missing_ok=True); continue
        lv = r.get("license_version") or ""
        credit = (f'"{r.get("title")}" por {r.get("creator") or "autor desconhecido"} ({r.get("source")}), '
                  f'licença {lic.upper()} {lv}, {r.get("foreign_landing_url")}')
        man.append(dict(id=r["id"], arquivo=wav.name, titulo=r.get("title"), autor=r.get("creator"), fonte=r.get("source"),
                        licenca=lic, versao=lv, pagina=r.get("foreign_landing_url"), duracao_s=dur, credito=credit,
                        precisa_credito=lic not in ("cc0", "pdm")))
        print(f"  ok  {wav.name}  [{lic} {lv}]  {dur:.1f}s")
        got += 1
    man_path.write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "CREDITOS.txt").write_text("\n".join(m["credito"] for m in man if m["precisa_credito"]) + "\n", encoding="utf-8")
    print(f"{got} novos arquivos em {out} (total {len(man)})")
    if a.rank and man:
        try:
            subprocess.run([sys.executable, "-m", "earshot", "rank", a.rank, *[str(out / m["arquivo"]) for m in man], "--top", "5"], check=False)
        except Exception as exc:
            print("earshot indisponivel:", exc)

if __name__ == "__main__":
    main()
