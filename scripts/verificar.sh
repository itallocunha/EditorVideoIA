#!/usr/bin/env bash
# Confere se o ambiente do EditorVideoIA esta pronto. Nao instala nada.
# Sai com codigo 1 se algo obrigatorio faltar.
cd "$(dirname "$0")/.."
ROOT="$PWD"
VENV="${EDITOR_VENV:-$ROOT/.venv}"
MODELO="${EDITOR_WHISPER_MODEL:-small}"
export HF_HOME="${HF_HOME:-$ROOT/modelos}"

obrigatorio_falhou=0
ok()   { printf '  [ok]    %s\n' "$*"; }
aviso() { printf '  [aviso] %s\n' "$*"; }
erro()  { printf '  [FALTA] %s\n' "$*"; obrigatorio_falhou=1; }

echo "Programas"
command -v ffmpeg >/dev/null && ok "ffmpeg: $(ffmpeg -version | head -1)" || erro "ffmpeg"
command -v ffprobe >/dev/null && ok "ffprobe" || erro "ffprobe"
[ -x "$VENV/bin/python" ] && ok "ambiente Python em $VENV" || erro "ambiente Python (rode scripts/preparar.sh)"
if [ -x "$VENV/bin/python" ]; then
  "$VENV/bin/python" -c "import flask, faster_whisper, numpy, PIL, imageio_ffmpeg, anthropic" 2>/dev/null && ok "dependencias Python" || erro "dependencias Python (rode scripts/preparar.sh)"
  "$VENV/bin/auto-editor" --version >/dev/null 2>&1 && ok "auto-editor $("$VENV/bin/auto-editor" --version 2>/dev/null | head -1)" || aviso "auto-editor ausente: o corte de pausas cai para so Whisper"
fi

echo "Modelo Whisper ($MODELO)"
if ls "$HF_HOME"/hub/models--Systran--faster-whisper-"$MODELO"/snapshots/*/model.bin >/dev/null 2>&1; then ok "modelo em $HF_HOME/hub"; else erro "modelo $MODELO nao encontrado em $HF_HOME (rode scripts/preparar.sh)"; fi

echo "Animacoes (opcional)"
if command -v node >/dev/null; then
  major="$(node -p 'process.versions.node.split(".")[0]')"
  [ "$major" -ge 22 ] && ok "node $(node --version)" || aviso "node $(node --version) e antigo (precisa 22+)"
else aviso "node ausente: o editor usa a animacao simples do FFmpeg"; fi
if [ -n "${HYPERFRAMES_BROWSER_PATH:-}" ] || [ -e /opt/pw-browsers/chromium ] || command -v google-chrome >/dev/null || command -v chromium >/dev/null || command -v chromium-browser >/dev/null; then
  ok "navegador para o HyperFrames"
else aviso "sem Chrome/Chromium: o HyperFrames baixa o proprio ou usa a legenda simples"; fi

echo "Rede (so importa em ambiente com rede restrita; veja SETUP.md)"
for h in huggingface.co us.aws.cdn.hf.co drive.google.com drive.usercontent.google.com; do
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "https://$h" 2>/dev/null)"
  if [ "$code" = "000" ] || [ -z "$code" ]; then aviso "$h sem resposta (bloqueado?)"; else ok "$h responde ($code)"; fi
done

echo "Chave da Anthropic (opcional)"
[ -n "${ANTHROPIC_API_KEY:-}" ] && ok "ANTHROPIC_API_KEY definida" || aviso "sem ANTHROPIC_API_KEY: o pedido e lido por palavras-chave, sem IA"

echo
[ "$obrigatorio_falhou" = 0 ] && echo "Tudo que e obrigatorio esta pronto." || echo "Faltam itens obrigatorios (marcados [FALTA])."
exit "$obrigatorio_falhou"
