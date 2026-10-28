# Editor de Vídeo IA

Você joga o vídeo bruto, as imagens e a música, escreve o que quer em um prompt e recebe o
vídeo editado: pausas cortadas, legendas dinâmicas palavra por palavra e imagens animadas.
Tudo roda no seu computador.

## Como usar

1. Dê dois cliques em `iniciar.bat`.
   - Na primeira vez ele cria o ambiente e instala tudo (alguns minutos).
   - O navegador abre em http://127.0.0.1:5055.
2. Arraste o vídeo, as imagens de apoio e a trilha (opcionais).
3. Escreva o pedido no campo de prompt e clique em **Editar vídeo**.
4. Acompanhe o progresso. Quando terminar, assista, baixe ou abra a pasta `saida`.

Requisito: Python 3.10 ou mais novo (python.org, marcando "Add python.exe to PATH").
O FFmpeg já vem junto na instalação. Na primeira transcrição o modelo do Whisper é baixado
(cerca de 500 MB para o `small`).

## Revisar as legendas antes de editar

O botão **Revisar legendas antes de editar** transcreve o vídeo e abre um editor na tela, com uma prévia leve do vídeo:

- Cada linha mostra início, fim e texto. Corrija o texto e os tempos quando a IA errar.
- ✂ corta aquele trecho do vídeo (sai do vídeo e das legendas). ✕ apaga só a legenda. ⎘ divide a linha onde está o cursor. ⇣ junta com a próxima.
- Escreva `*palavra*` entre asteriscos para dar ênfase: a palavra cresce e treme na legenda animada.
- "Gerar vídeo com estas legendas" usa o seu texto, sem transcrever de novo e sem subir o vídeo outra vez.

## Legendas animadas (motion)

As legendas agora são desenhadas pelo HyperFrames: cada palavra entra com mola, a palavra ativa muda de cor e cresce,
e o grupo entra e sai suave. Há o estilo **Caixa colorida**, com a palavra ativa dentro de uma caixa. Em Opções avançadas, "Tipo de legenda":

- **Animada com HyperFrames (padrão até 4 minutos):** a mais bonita, mas leva alguns minutos para renderizar.
- **Animada sempre:** igual, também para vídeos longos.
- **Simples e rápida:** usa o formato .ass do FFmpeg, bem mais rápida.

Se o Node.js 22 ou o navegador faltarem, o editor cai sozinho para a legenda simples.

## Analisar o vídeo antes de editar

O botão **Analisar vídeo (texto e prompt)** não edita nada. Ele:

1. Transcreve toda a fala com tempos e gera as legendas em texto e em `.srt`.
2. Tira de 6 a 16 quadros ao longo do vídeo.
3. Mede o ritmo (palavras por minuto, pausas) e lista as palavras mais usadas.
4. Monta um **prompt sugerido** para a edição. Dá para usar direto (botão "Usar este prompt na edição") ou ajustar.

Com a chave da API da Anthropic (Opções avançadas), a IA também olha os quadros e escreve o que acontece em cada cena,
o estilo visual, os momentos fortes e ideias de imagens de apoio, e o prompt sugerido fica bem mais detalhado.
Os quadros e a transcrição vão para a IA nesse caso. Tudo é salvo em `saida/<video>_analise_<data>/`
(`relatorio.md`, `transcricao.txt`, `legendas.srt` e `frames/`).

## O que o prompt entende

Escreva em português normal. Exemplos:

- "Corte as pausas de forma agressiva, legenda amarela estilo Hormozi, formato vertical para Reels"
- "Legenda verde no centro da tela, imagens em tela cheia, música baixa"
- "Ritmo calmo, legenda suave, imagens como cartões centralizados"
- "Sem legenda, só corte as pausas"
- "logo.png aos 12 segundos" (força o momento de uma imagem)

Sem chave de API, o editor interpreta palavras-chave (agressivo, calmo, vertical, cores,
tela cheia, cartão, música baixa, sem legenda, sem cortes...). As opções avançadas na tela têm
prioridade sobre o prompt.

## Detecção de pausas

O editor usa o [auto-editor](https://github.com/WyattBlue/auto-editor) (domínio público, 5,5 mil estrelas no GitHub)
para medir o volume do áudio e achar exatamente onde há voz e onde há silêncio. O Whisper diz o que foi falado,
e a combinação dos dois evita cortar sílabas e remove pausas que o Whisper marca errado. Na primeira execução
o auto-editor baixa o próprio programa (precisa de internet). Se ele não estiver disponível, o editor cai
automaticamente para o modo só Whisper. Dá para escolher o motor em Opções avançadas.

## Animação dos cartões (HyperFrames)

Logos, prints e PNGs entram como cartões animados desenhados pelo [HyperFrames](https://github.com/heygen-com/hyperframes)
(da HeyGen, Apache 2.0, 62 mil estrelas). Ele transforma HTML e GSAP em vídeo transparente, com animações mais ricas que o FFmpeg:
pop com mola, giro, queda com quique, deslize e uma respiração leve enquanto o cartão fica na tela.

- Precisa do **Node.js 22 ou mais novo** (nodejs.org). Sem ele o editor usa a animação simples do FFmpeg e avisa no log.
- Na primeira vez o editor instala o HyperFrames sozinho na pasta `hf_runtime` (precisa de internet).
- Usa o Chrome ou o Edge que já estão no seu computador. Se não achar, o HyperFrames baixa o próprio navegador.
- Dá para desligar em Opções avançadas, em "Animação dos cartões". A telemetria do HyperFrames fica desligada.

## Como as imagens são posicionadas

- Se o nome do arquivo tem uma palavra falada no vídeo (ex: `dinheiro.png`), a imagem entra
  quando essa palavra é dita.
- As demais são distribuídas ao longo do vídeo, no começo de frases.
- Fotos no formato do vídeo entram em **tela cheia** com zoom ou pan (efeito Ken Burns).
  Logos, prints e PNGs com transparência entram como **cartão** com cantos arredondados e
  sombra, com pop, slide ou fade.

## IA opcional (Claude)

Em Opções avançadas você pode colar uma chave da API da Anthropic (ou definir a variável
`ANTHROPIC_API_KEY`). Com ela, um modelo Claude interpreta seu pedido livremente e escolhe o
melhor momento de cada imagem lendo a transcrição. O texto transcrito é enviado à API nesse
caso. Sem a chave, nada sai do seu computador, exceto o download inicial do modelo Whisper.

## Dicas

- Para ficar mais rápido, escolha qualidade "Rápida" e o modelo `base` ou `small`.
- Placa NVIDIA: dentro da `.venv`, rode `pip install nvidia-cublas-cu12 nvidia-cudnn-cu12`
  e use o modelo `medium` ou `large-v3`. O editor usa a GPU automaticamente se ela estiver disponível.
- Fonte das legendas: coloque um `.ttf` na pasta `fonts` (veja `fonts/LEIAME.txt`).
- Vídeos longos (mais de 15 minutos) com muitos cortes demoram mais para renderizar.

## Estrutura

```
EditorVideoIA/
  iniciar.bat        abre o editor
  app.py             servidor local e API
  static/index.html  interface
  editor/            motor de edição
    transcribe.py    Whisper com tempo por palavra
    cuts.py          detecção de pausas e jump cuts
    autoedit.py      integração com o auto-editor
    analyze.py       análise do vídeo (texto, cenas e prompt)
    review.py        revisão e edição das legendas antes do render
    whisper_worker.py  Whisper em processo separado e vigiado
    hyperframes_fx.py  cartões animados com o HyperFrames
    subtitles.py     legendas .ass animadas
    planner.py       interpreta o prompt e posiciona imagens
    render.py        FFmpeg: cortes, overlays, legendas, trilha
    pipeline.py      orquestra tudo
  hf_runtime/        HyperFrames instalado automaticamente
  fonts/             fontes extras para legenda
  saida/             vídeos prontos
  workspace/         arquivos temporários de cada edição (pode apagar)
```

## Problemas comuns

- **Aviso de FFmpeg sem filtros**: instale a versão completa com `winget install Gyan.FFmpeg`
  e rode o `iniciar.bat` de novo.
- **Legenda com fonte errada**: coloque a fonte desejada na pasta `fonts`.
- **Erro durante a renderização**: a mensagem do FFmpeg aparece na tela. A pasta
  `workspace/jobs/<id>/work` guarda os arquivos intermediários para diagnóstico.


## Vários vídeos e limpeza inteligente da fala

- **Vários vídeos:** envie quantos clipes quiser. Eles são juntados na ordem da lista (use as setas para mudar) em um vídeo só, com o mesmo tamanho e áudio, e a edição roda sobre o vídeo juntado.
- **Pausas mais atentas:** o padrão agora é 0,3 s de pausa mínima. Micro-cortes são unidos, barulhos sem fala são descartados e cada corte vai para o ponto mais quieto, sem entrar na palavra vizinha.
- **Limpeza da fala (`editor/cleanup.py`):** tira tomadas erradas (a frase dita de novo, fica a última), recomeços no meio da frase, gagueira, palavra cortada, vícios (eh, ahn, hum) e comentários de gravação ("pera aí", "vou repetir").
- **Fora do assunto:** cole o roteiro no campo "Roteiro ou assunto". Trechos longos sem nenhuma palavra em comum com o roteiro e o pedido são cortados. Com a chave da Anthropic, a IA lê a transcrição e decide o que erra, repete ou não combina.
- **Revisar antes:** no modo "Revisar legendas" os trechos sugeridos já vêm marcados com ✂ e o motivo. Você decide o que sai. Na edição direta, a lista do que foi removido aparece na tela final.

## Correções de 18/10/2026

- **Vídeo deitado:** ao juntar clipes de celular, a marca de rotação era copiada para o arquivo novo e o vídeo girava duas vezes. Agora a marca é removida ao juntar, cortar e exportar.
- **Legendas animadas:** o HyperFrames renderiza com 1 worker (grava em fluxo). Antes ele pedia ~11 GB livres em disco e caía nas legendas simples.
- **Corte "zero pausa":** novo corte pela voz. O editor mede o nível da fala da própria gravação e corta silêncios, respiros e ruídos. Pausas acima de ~0,12 s saem (Corte de pausas: Agressivo). Sons sem palavra nenhuma (tentativas que o Whisper não transcreveu) também saem.
- **Erros e falas fora do roteiro:** com roteiro (campo Roteiro, ou falas entre aspas no pedido), frases que não estão no roteiro e tomadas repetidas do mesmo trecho são cortadas. O Whisper agora escreve "eh", "ahn" e recomeços para a limpeza conseguir achar.
- **Textos na tela:** uma seção "Textos na tela" no pedido ou roteiro (itens com o texto entre aspas) vira cartões animados. Cada cartão entra quando a fala correspondente começa. Sem essa seção, os destaques mostram a expressão falada.
- Legenda na posição "Parte de baixo" subiu para fora da área dos botões do Reels/TikTok.

## Motores de estilo (linha de comando)

Além do app, o repositório traz dois motores que editam a partir de um "plano" em Python
(takes + transcrição com tempo por palavra do faster-whisper):

| pasta | estilo | uso |
|---|---|---|
| `pulso/` | **Edição Pulso**: cortes zero pausa, legendas dinâmicas, títulos em arco, etiquetas, cenas gráficas, efeitos sonoros e encerramento animado | `python pulso/pulso.py pulso/plano_exemplo.py` |
| `narrado/` | **Narrado Neon**: vídeo narrado 100% animado (motion graphics), manchete palavra por palavra, 18 tipos de cena | `python narrado/narrado.py narrado/plano_exemplo.py` (`html` no fim gera só a página para conferir) |

- A animação é renderizada com HyperFrames + GSAP (o app prepara o runtime em `hf_runtime/` na primeira vez).
- Efeitos sonoros: se o [earshot](https://github.com/Leonxlnx/earshot) estiver instalado, `editor/sfx_bank.py` usa o banco dele; senão, usa efeitos sintetizados.
- `sons/buscar_sons.py` busca gravações reais com licença CC0 / CC BY na API do Openverse e gera os créditos.
- `skills/` traz as instruções (SKILL.md) dos estilos para usar com agentes de IA.

## Créditos de terceiros

- GSAP (`pulso/gsap.min.js`), licença padrão da GreenSock/Webflow.
- Fontes Archivo Black e JetBrains Mono (`narrado/fonts/`), SIL Open Font License, via Fontsource.
- Fontes Poppins e Lora (`pulso/fonts/`), SIL Open Font License, via Google Fonts (licenças em `pulso/fonts/OFL-*.txt`).
- earshot e real-sound (opcionais, não incluídos), MIT, por Leon Lin.
