# Preparar o ambiente

Este guia lista tudo o que o EditorVideoIA precisa para editar do mesmo jeito em qualquer lugar: no seu computador, no Claude Code ou numa sessão do Claude na nuvem.

Resumo: **um comando prepara tudo** e outro confere.

```bash
bash scripts/preparar.sh     # Mac, Linux ou sessão na nuvem
bash scripts/verificar.sh    # confere o que está pronto e o que falta
```

No Windows, dê dois cliques em `iniciar.bat` (faz o mesmo na primeira vez).

## O que é instalado

| Item | Para quê | Obrigatório | Como |
|---|---|---|---|
| Python 3.10 ou mais novo | roda o editor | sim | python.org (Windows: marcar "Add python.exe to PATH") |
| FFmpeg e ffprobe (versão completa) | cortes, legendas, render | sim | Windows: `winget install Gyan.FFmpeg`. Mac: `brew install ffmpeg`. Linux: `sudo apt-get install -y ffmpeg` |
| Pacotes Python (`requirements.txt`) | Flask, faster-whisper, auto-editor, Pillow, anthropic e outros | sim | `scripts/preparar.sh` cria o `.venv` e instala |
| Modelo Whisper `small` (cerca de 484 MB) | transcrição com tempo por palavra | sim | `scripts/preparar.sh` baixa para `modelos/` |
| auto-editor | detecção de pausas pela voz | recomendado | vem no `requirements.txt` |
| Node.js 22 ou mais novo | animações HyperFrames (legendas e cartões) | opcional | nodejs.org. Sem ele o editor usa a animação simples do FFmpeg |
| Chrome, Edge ou Chromium | o HyperFrames renderiza por ele | opcional | Em sessão na nuvem já existe em `/opt/pw-browsers/chromium` |
| `ANTHROPIC_API_KEY` | o pedido é interpretado por IA e a análise de cenas lê os quadros | opcional | variável de ambiente. **Nunca coloque a chave no repositório** |

O HyperFrames e o GSAP são instalados pelo próprio app, em `hf_runtime/`, na primeira edição animada (precisa de npm e internet).

Modelos maiores (`medium`, `large-v3`) são melhores e mais lentos: `EDITOR_WHISPER_MODEL=medium bash scripts/preparar.sh`.

## Rede (sessões na nuvem com rede restrita)

Em ambientes com lista de hosts permitidos, libere estes (nomes exatos, sem curinga):

- **Pacotes:** PyPI e npm. Em geral já vêm liberados como "gerenciadores de pacotes".
- **Modelo Whisper:** `huggingface.co` e `us.aws.cdn.hf.co`.
- **Vídeos no Google Drive:** `drive.google.com`, `drive.usercontent.google.com`. Para arquivos grandes o Drive também redireciona para hosts `doc-XX-XX-docs.googleusercontent.com`. O ambiente "EditorVideoIA (Google Drive)" liberou estes cinco: `doc-0s-1g-docs.googleusercontent.com`, `doc-00-1g-docs.googleusercontent.com`, `doc-08-1g-docs.googleusercontent.com`, `doc-0o-1g-docs.googleusercontent.com`, `doc-0c-1g-docs.googleusercontent.com`. Se um download do Drive falhar com 403, o host bloqueado aparece no cabeçalho `location` de `curl -sI <link>`.

Observações:
- `scripts/preparar.sh` define `HF_HUB_DISABLE_XET=1`. Sem isso o Hugging Face tenta baixar o arquivo grande do modelo por `cas-server.xethub.hf.co`, que costuma estar bloqueado, e o download falha com `CAS Client Error`.
- Se mesmo assim der 403, descubra o host com `curl -sI https://huggingface.co/Systran/faster-whisper-small/resolve/main/model.bin | grep -i location` e libere esse host.
- Em rede aberta (seu computador) nada disso é necessário.

## MCPs e conectores

O editor **não usa MCP**. Ele roda local: FFmpeg, Whisper e auto-editor. Os vídeos do Google Drive entram por links compartilhados ou arquivos baixados para a pasta de trabalho, não por um conector. Se um dia você conectar um MCP (por exemplo, Drive), liste aqui qual e para quê.

## Contas e chaves

- Cada pessoa conecta a própria conta do Claude. Nada neste repositório guarda login.
- Chave da API (opcional): `export ANTHROPIC_API_KEY=...` ou colar nas Opções avançadas do app. O arquivo `.env` é ignorado pelo git.

## Onde ficam os arquivos

| Pasta | Conteúdo | No git? |
|---|---|---|
| `modelos/` | modelo Whisper baixado | não |
| `.venv/` | ambiente Python | não |
| `hf_runtime/` | HyperFrames instalado pelo app | não |
| `workspace/` | arquivos temporários de cada edição | não |
| `saida/` | vídeos prontos | não |
| `skills/`, `pulso/`, `narrado/`, `editor/` | instruções e código dos estilos | sim |

## Conferir que está tudo certo

```bash
bash scripts/verificar.sh
.venv/bin/python -m pytest -q tests     # instale antes: .venv/bin/pip install pytest
```

Para abrir o app: `HF_HOME=modelos .venv/bin/python app.py` e acessar http://127.0.0.1:5055. Em sessão na nuvem o app só é acessível dali; prefira os motores de linha de comando (veja `CLAUDE.md`).

## Problemas comuns

- **`CAS Client Error` ou 403 ao baixar o modelo:** veja a seção Rede.
- **FFmpeg 8 ou 9 com erro de filtro:** o editor já usa `-/filter_complex` quando precisa. Mantenha o código atualizado e use um FFmpeg completo.
- **Sem legendas animadas:** falta Node 22+ ou navegador. O editor avisa no log e cai para a legenda simples.
- **Pasta movida de lugar:** apague `.venv` e rode `scripts/preparar.sh` de novo.
