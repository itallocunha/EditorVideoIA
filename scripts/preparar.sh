#!/usr/bin/env bash
# Prepara o EditorVideoIA em Mac, Linux ou sessao do Claude na nuvem.
# Seguro para rodar varias vezes (so instala o que falta).
#
# Variaveis opcionais:
#   EDITOR_VENV            pasta do ambiente Python (padrao: .venv)
#   EDITOR_WHISPER_MODEL   tiny | base | small | medium | large-v3 (padrao: small)
#   HF_HOME                onde guardar o modelo (padrao: ./modelos)
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$PWD"
VENV="${EDITOR_VENV:-$ROOT/.venv}"
MODELO="${EDITOR_WHISPER_MODEL:-small}"
export HF_HOME="${HF_HOME:-$ROOT/modelos}"
# O backend Xet do Hugging Face usa hosts que costumam ficar bloqueados em rede restrita.
# Com isto o download usa so huggingface.co e a CDN (veja SETUP.md, secao Rede).
export HF_HUB_DISABLE_XET=1

etapa() { printf '\n== %s\n' "$*"; }
falha() { printf '\nERRO: %s\n' "$*" >&2; exit 1; }

etapa "1/5 Programas do sistema"
command -v ffmpeg >/dev/null || falha "FFmpeg nao encontrado. Mac: brew install ffmpeg | Debian/Ubuntu: sudo apt-get install -y ffmpeg"
command -v ffprobe >/dev/null || falha "ffprobe nao encontrado (vem junto com o FFmpeg)."
PY="$(command -v python3 || true)"
[ -n "$PY" ] || falha "Python 3 nao encontrado. Instale o Python 3.10 ou mais novo."
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || falha "Python 3.10 ou mais novo e necessario (achei: $("$PY" --version))."
echo "ffmpeg: $(ffmpeg -version | head -1)"
echo "python: $("$PY" --version)"

etapa "2/5 Ambiente Python e dependencias"
if [ ! -x "$VENV/bin/python" ]; then
  "$PY" -m venv "$VENV"
fi
"$VENV/bin/python" -m pip install -q --upgrade pip
"$VENV/bin/python" -m pip install -q -r requirements.txt
"$VENV/bin/python" -c "import flask, faster_whisper, numpy, PIL, imageio_ffmpeg, anthropic; print('dependencias ok')"

etapa "3/5 Modelo Whisper ($MODELO)"
ok=0
for tentativa in 1 2 3; do
  if "$VENV/bin/python" - "$MODELO" <<'PY'
import sys
from huggingface_hub import snapshot_download
modelo = sys.argv[1]
print(snapshot_download("Systran/faster-whisper-" + modelo))
PY
  then ok=1; break; fi
  echo "Tentativa $tentativa falhou. Se for erro 403, veja SETUP.md (secao Rede)."
  sleep 5
done
[ "$ok" = 1 ] || falha "Nao consegui baixar o modelo Whisper. Libere os hosts do Hugging Face (SETUP.md) e rode de novo."

etapa "4/5 Node.js (animacoes HyperFrames)"
if command -v node >/dev/null; then
  major="$(node -p 'process.versions.node.split(".")[0]')"
  if [ "$major" -ge 22 ]; then echo "node $(node --version) ok. O HyperFrames e instalado pelo app na primeira vez, em hf_runtime/."
  else echo "AVISO: Node $(node --version) e antigo (precisa 22+). O editor usa a animacao simples do FFmpeg."; fi
else
  echo "AVISO: Node.js nao encontrado. O editor usa a animacao simples do FFmpeg. Instale o Node 22+ para as legendas e cartoes animados."
fi

etapa "5/5 Navegador para o HyperFrames"
NAV="${HYPERFRAMES_BROWSER_PATH:-}"
if [ -z "$NAV" ]; then
  for c in /opt/pw-browsers/chromium "$(command -v google-chrome || true)" "$(command -v chromium || true)" "$(command -v chromium-browser || true)" \
           "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"; do
    if [ -n "$c" ] && [ -e "$c" ]; then NAV="$c"; break; fi
  done
fi
if [ -n "$NAV" ]; then
  echo "navegador: $NAV"
  echo "Se o editor nao achar sozinho, rode antes: export HYPERFRAMES_BROWSER_PATH=\"$NAV\""
else
  echo "AVISO: nenhum Chrome/Chromium encontrado. O HyperFrames baixa o proprio navegador (precisa de internet) ou o editor usa a legenda simples."
fi

printf '\nPronto. Para abrir o editor:\n  HF_HOME="%s" "%s/bin/python" app.py   (http://127.0.0.1:5055)\nPara conferir tudo: scripts/verificar.sh\n' "$HF_HOME" "$VENV"
