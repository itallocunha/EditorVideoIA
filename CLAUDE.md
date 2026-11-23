# EditorVideoIA para o Claude

Este repositório edita vídeos (cortes de pausa, legendas, cartões animados, estilos Pulso e Narrado Neon) com FFmpeg, faster-whisper e HyperFrames. Leia este arquivo antes de editar. Detalhes de instalação estão em `SETUP.md`.

## Antes de qualquer edição

1. Rode `bash scripts/verificar.sh`.
2. Se faltar algo obrigatório, rode `bash scripts/preparar.sh` e verifique de novo.
3. Se o download do modelo ou do Drive der 403, é rede restrita: leia a seção Rede do `SETUP.md`. Não tente contornar com outros hosts nem desligue verificação de certificado. Diga ao usuário quais hosts precisam ser liberados.

## Como editar

- **Estilo Pulso** (Reels verticais, cortes zero pausa): siga `skills/edicao-pulso/SKILL.md`. Motor: `pulso/pulso.py`, plano de exemplo em `pulso/plano_exemplo.py`.
- **Estilo Narrado Neon** (vídeo narrado em motion graphics): siga `skills/narrado-neon/SKILL.md`. Motor: `narrado/narrado.py`.
- **Edição pelo app** (`app.py`, interface em `static/`): o usuário envia vídeo, imagens e trilha e escreve o pedido.
- **Módulos do editor** em `editor/`: `transcribe.py` (Whisper por palavra), `cuts.py` e `autoedit.py` (pausas), `cleanup.py` (limpeza da fala), `render.py` (FFmpeg), `hyperframes_fx.py` (animações), `planner.py` (interpreta o pedido).

### Ajustes para as skills neste repositório

As skills foram escritas para um Projeto do Claude com outras pastas. Aqui valem estes caminhos:
- onde a skill cita `claude/pulso/...` e `claude/narrado/...`, use `pulso/` e `narrado/` deste repositório;
- onde cita `/home/claude/EditorVideoIA/editor/`, use `editor/` deste repositório;
- onde cita rodar o Whisper "no PC dele" com `device_bash`, rode aqui mesmo: o modelo fica em `modelos/` (`HF_HOME=modelos`) e a transcrição é feita por `editor/transcribe.py` (faster-whisper; usa a GPU se houver, senão CPU);
- em sessão na nuvem, aponte o navegador do HyperFrames para o Chromium existente: `export HYPERFRAMES_BROWSER_PATH=/opt/pw-browsers/chromium`.

## Regras fixas do usuário (valem sempre)

- Texto em português e **sem travessão** (—).
- Estilo Pulso: sem botão "Saiba mais" no final; legenda da fala mais baixa (frase a 65% da altura, palavra solta a 69%); nunca terminar seco no meio da fala; corrigir nomes que o Whisper errou e conferir a ordem das palavras do gancho. As demais regras estão na skill.
- Dosar os efeitos: no máximo 1 título em arco, 2 a 3 etiquetas, 1 cena gráfica e 1 clarão por vídeo de cerca de 30 s.

## Entrada e saída

- Vídeos de entrada: coloque em `workspace/` (não vai para o git). Vídeos do Google Drive: baixe pelo link compartilhado para `workspace/` se os hosts do Drive estiverem liberados (`SETUP.md`).
- Resultados: `saida/`. Antes de entregar, confira quadros do MP4 final: orientação em pé, legenda fora do rosto, nada cortado, áudio presente.
- Nunca faça commit de vídeos, áudios, `modelos/`, `.venv/`, `hf_runtime/`, `workspace/` ou `saida/` (já estão no `.gitignore`).

## Segredos

- A chave `ANTHROPIC_API_KEY` é opcional e vem do ambiente do usuário. Nunca escreva chaves, tokens ou links privados em arquivos do repositório, logs ou mensagens de commit.
- Sem chave, o pedido é lido por palavras-chave e nada sai da máquina além do download do modelo.

## O que ainda não foi verificado

- Transcrição e render completos com um vídeo real nesta configuração de nuvem: o ambiente foi preparado e os testes (`tests/`) passam, mas a primeira edição completa deve ser conferida pelo usuário.
- Download de vídeos do Drive: depende dos hosts liberados e do tamanho do arquivo.

## Testes

```bash
.venv/bin/pip install pytest && .venv/bin/python -m pytest -q tests
```
