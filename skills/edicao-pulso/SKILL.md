---
name: "edicao-pulso"
description: "Use quando o Itallo pedir \"Edição Pulso\" (ou \"estilo Pulso\") para editar takes de Reels: cortes zero pausa, legendas dinâmicas, títulos em arco, etiquetas douradas, cenas gráficas, efeitos sonoros e encerramento animado."
---

# Edição Pulso

Template de edição de Reels verticais (1080x1920, 30 fps) inspirado num Reel de creator de tecnologia (@victoframe, out/2026): ritmo rápido, planos alternando, legenda palavra por palavra, títulos em arco sobre a cabeça, etiquetas douradas brilhantes, cenas gráficas em tela cheia e cor cinematográfica (teal/orange). Também tem a variante "simonato" (legenda grande com destaque rosa itálico, manchete no topo), usada nos vídeos de cidadania.

## Regras fixas do Itallo (valem sempre)
- Sem botão "Saiba mais" no final.
- Legenda da fala mais baixa: frase grande a 65% da altura, palavra solta a 69% (sobre o peito, nunca sobre a boca).
- Nunca terminar seco no meio da fala: sempre ter um final (animação de encerramento ou cena de respiro + fade).
- Se a pessoa fizer careta ou cara estranha no fim, cobrir com a animação de encerramento (ENDING) a partir da última palavra.
- Corrigir nomes que o Whisper errou (WORD_FIX) e conferir a ordem das palavras no gancho.
- Texto do usuário sem travessão (—).

## Linguagem visual (o que o estilo faz)
1. Cortes: corte seco a cada frase, pausas acima de ~0,12 s removidas, alternando plano aberto (zoom 1.0) e fechado (1.3); zoom lento (push) em ganchos e frases finais; plano em preto e branco com contraste em frases de impacto ("Parece bobeira").
2. Legenda padrão: uma palavra por vez, Poppins Bold branca ~60 px com brilho escuro, no peito.
3. Gancho: texto grande no topo (caption "top") ou título em arco amarelo sobre a cabeça (ARC_TITLES).
4. Etiquetas: pílula preta com borda dourada e brilho, ícone + palavra, atravessa a tela da direita para a esquerda (PILLS) quando a fala cita uma função ou conceito.
5. Cena gráfica: fundo papel claro em tela cheia com título e botões dourados entrando em sequência + cursor clicando (CARD_SCENES). Cobre o rosto; a voz continua.
6. Título com rabisco: linha branca grande + linha itálica vermelha + traço vermelho desenhado (SCRIBBLE_TITLES).
7. Clarão de luz quente como transição em virada de assunto (FLASH_BEFORE_SEGMENT).
8. Passos numerados no topo quando a fala lista etapas (STEPS).
9. Encerramento: painel escuro abrindo em círculo, frase final grande na cor de destaque, linha e círculos 1-2-3 (ENDING), fade para preto.
10. Efeitos sonoros sintetizados (sem banco externo): whoosh nas trocas de plano, pop nos destaques, click nas etiquetas, ding nos passos, subida + impacto no clarão, brilho no final. Volume baixo, embaixo da voz.
11. Cor: contraste e leve teal/orange com vinheta (STYLE="pulso"); destaque amarelo #ffd60a.

## Passo a passo
1. Receber os takes (anexos) e o roteiro, se houver. Converter cada take para wav 16 kHz mono.
2. Transcrever com tempo por palavra. O sandbox não baixa modelos; usar o Whisper do PC dele: enviar os wav para `<pasta do EditorVideoIA>\workspace\takes_<nome>\` (device_commit_files), pedir acesso a `<home>\.cache` se preciso e, no device_bash, rodar faster-whisper (modelo `models--Systran--faster-whisper-medium`, int8, language="pt", word_timestamps=True, initial_prompt com hesitações). Salvar `words_medium.json` no formato `{"1": [{"w":..,"s":..,"e":..}], ...}` e trazer de volta com device_stage_files.
3. Montar o motor: ler do Project os arquivos `claude/pulso/pulso.py`, `claude/pulso/plano_exemplo.py`, a pasta `claude/pulso/fonts/` (Poppins e Lora; fica ao lado do `pulso.py`) e `claude/pulso/editor/{cuts,transcribe,hyperframes_fx,media,config,sfx_bank}.py`. Colocar os do editor em `/home/claude/EditorVideoIA/editor/` (criar `__init__.py` vazio). O HyperFrames instala o runtime sozinho na primeira vez; no sandbox usar `HYPERFRAMES_BROWSER_PATH=/opt/pw-browsers/chromium-1194/chrome-linux/chrome`.
4. Escrever o plano (copiar `plano_exemplo.py`): TAKES, WORDS_JSON, WORK, OUT, SEGMENTS (take, palavra inicial, palavra final, enquadramento `("static", z)` / `("push", z0, z1)` / `("bw", z)`, legenda `("single",)` / `("kinetic", grupos)` / `("top", grupos)`; `*palavra*` = destaque, `[x]` = letra destacada), mais ARC_TITLES, PILLS, CARD_SCENES, SCRIBBLE_TITLES, STEPS, HEADLINES, FLASH_BEFORE_SEGMENT, OUTRO, ENDING. Cortar o que não está no roteiro e tomadas repetidas.
5. Conferir o layout antes de renderizar: `python3 pulso.py plano.py html` gera `layer.html`; tirar quadros com Playwright em alguns tempos e olhar.
6. Renderizar: `python3 pulso.py plano.py` (camada leva ~2-3 min). Conferir quadros do MP4 final (orientação em pé, legenda fora do rosto, nada cortado) e enviar com SendUserFile.
7. Dosar: no máximo 1 título em arco, 2-3 etiquetas, 1 cena gráfica e 1 clarão por vídeo de ~30 s, para não poluir.

## Limitações conhecidas
- Sem recorte de pessoa (fundo trocado, texto atrás do corpo, silhueta): não há ferramenta de remoção de fundo offline no sandbox.
- Fontes: Poppins (Bold e BoldItalic) e Lora Italic vêm junto em `pulso/fonts/`; aproximam as da referência.
- B-roll (gravação de tela, mãos no notebook) só entra se o Itallo mandar os arquivos.