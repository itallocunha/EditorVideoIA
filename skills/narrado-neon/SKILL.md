---
name: "narrado-neon"
description: "Estilo NARRADO NEON do Itallo: video narrado 100% animado (motion graphics, sem rosto), fundo escuro rosa e creme, manchete palavra por palavra. Use ao ouvir \"narrado neon\"."
---

# NARRADO NEON (video narrado em motion graphics)

Esse estilo foi estudado a partir do reel de referencia instagram.com/reel/DezRLeUMwwn, um explicador vertical sobre Claude Code.
O video inteiro e animacao: a voz narra e a tela troca de cena a cada frase.

Regras de texto para o Itallo: escrever em portugues e nunca usar travessao (em dash).

## Linguagem visual (o que define o estilo)
- Formato 1080x1920, 30 fps.
- Corte seco entre cenas a cada 1 a 3 s, com um "whoosh" em cada corte. As vezes entra um flash branco curto ou uma transicao de vidro quebrando.
- Fundo quase preto (#0d090c), com um chao de grade rosa em perspectiva andando para a camera e uma linha de horizonte brilhante.
- Cenas de lista usam fundo rosa cheio (#f03a5f) com texto escuro. Cenas de site usam grade azul.
- Paleta: rosa #f03a5f (destaque), creme #f2e8d5 (texto e objetos) e preto. Nada mais.
- Manchete no topo em Archivo Black maiusculo:
  - a primeira linha e creme;
  - a linha de destaque e rosa e maior;
  - cada palavra entra (sobe e cresce) no instante em que e falada.
- Etiqueta de secao no canto superior esquerdo, em fonte mono: "01 /04 · TEMA".
- No centro fica uma ilustracao vetorial plana por frase. Ela entra com impacto (escala, rotacao ou carimbo) e depois segue com um leve zoom de camera.
- Efeitos sonoros curtos em todos os eventos: pop, click de digitacao, boom no carimbo, ding no contador.
- Uma trilha ambiente baixa toca por baixo da voz.

## Motor
Arquivos no Projeto "EDITOR PROFISSIONAL DE VIDEOS CRIATIVOS":
- `claude/narrado/narrado.py`: o motor;
- `claude/narrado/plano_exemplo.py`: um plano de exemplo;
- `claude/narrado/preview.js`: tira quadros da pagina antes de renderizar.

Dependencias:
- o repositorio EditorVideoIA, que fornece `editor/hyperframes_fx.py` (copia no Projeto em `claude/pulso/editor/hyperframes_fx.py`);
- ffmpeg, numpy e HyperFrames (node).

Fontes: uma pasta `fonts/` ao lado do motor com ArchivoBlack.woff2, JBMono400.woff2 e JBMono700.woff2. Se faltar alguma:
1. Rodar `npm pack @fontsource/archivo-black @fontsource/jetbrains-mono`.
2. Copiar `files/archivo-black-latin-400-normal.woff2`, `files/jetbrains-mono-latin-400-normal.woff2` e `files/jetbrains-mono-latin-700-normal.woff2`, renomeando para esses nomes.

Ambiente:
- No sandbox: `export HYPERFRAMES_BROWSER_PATH=/opt/pw-browsers/chromium-1194/chrome-linux/chrome`.
- A variavel `EDITOR_VIDEO_IA` aponta para o repositorio (padrao /home/claude/EditorVideoIA).

Uso:
- `python3 narrado.py plano.py` gera o MP4.
- `python3 narrado.py plano.py html` gera so a pagina, para conferir.
- `node preview.js <WORK>/layer.html <prefixo> t1 t2 ...` tira quadros nos tempos escolhidos.

## Fluxo de trabalho
1. Receber a narracao. Pode vir como takes de audio ou video (so a voz basta). Se vier so um roteiro sem audio, pedir a gravacao.
2. Transcrever com faster-whisper medium no PC dele, no mesmo fluxo do editor: tr.py gera `words_medium.json` no formato {"1":[{"w","s","e"}...]}.
3. Ajustar a transcricao no plano:
   - CORRIGIR para nomes errados;
   - TRECHOS para escolher os trechos bons;
   - IGNORAR para remover gaguejos.
   O motor corta sozinho as pausas acima de PAUSA_MAX (0,28 s).
4. Dividir a fala em cenas: uma cena por frase ou ideia, de 1,5 a 4 s cada.
   - Para cada cena, escolher a ilustracao que mostra a frase, em vez de so repetir o texto.
   - A manchete deve ser curta e usar as palavras faladas, porque o motor sincroniza palavra a palavra pelo texto falado. Palavras que nao foram faladas entram em sequencia.
5. Escrever o plano, gerar o `html`, tirar quadros com preview.js e olhar a folha de contato antes de renderizar.
6. Renderizar, conferir quadros do MP4 final e entregar com SendUserFile.

## Formato do plano
```python
WORK = ".../work"; OUT = ".../saida.mp4"
NARRACAO = {1: "take1.wav", 2: "take2.mp4"}      # ordem = ordem do video
WORDS_JSON = ".../words_medium.json"
CORRIGIR = {(1, 0): "Manuel"}                     # (take, indice_palavra): texto
TRECHOS = {2: (3, 40)}                            # opcional: faixa de palavras usada do take
IGNORAR = [(2, 7)]                                # opcional: palavras a cortar
# opcionais: COR_DESTAQUE, COR_CLARA, COR_FUNDO, PAUSA_MAX, CAUDA, MUSICA="arquivo.mp3", VOLUME_MUSICA, TRILHA_SINTETICA, VOLUME_EFEITOS
CENAS = [
  dict(tipo="icone", icone="cadeado", titulo="Tokens quase|*ilimitados*", secao="01 /03 · TEMA"),
  dict(em=(1, 8), tipo="contador", valor=959492879, titulo="..."),   # em = (take, palavra) onde a cena comeca
]
```
Chaves comuns de cada cena:
- `tipo`;
- `em`: a palavra onde a cena comeca (a primeira cena sempre comeca em 0);
- `titulo`: linhas separadas por `|`, trecho rosa entre `*`;
- `secao`;
- `fundo`: "escuro", "rosa", "azul" ou "preto";
- `transicao`: "flash" (padrao), "vidro" ou "corte".

## Tipos de cena
| tipo | o que mostra | parametros |
|---|---|---|
| icone | icone desenhado a traco num bloco brilhante, com raios de luz e particulas | icone, rotulo |
| contador | numero estilo odometro rolando ate o valor | valor, prefixo, sufixo, rotulo |
| etiqueta | lua creme, predios em barras e uma etiqueta caindo como carimbo | texto |
| lista | fundo rosa, um cartao por item trocando, com contador "1 /07" | itens=[{titulo, icone ou sigla, sub, selo, manchete, em}], rotulo, rotulo_card |
| grade | mosaico de blocos acendendo e um numero grande no centro | numero, rotulo |
| terminal | janela de terminal digitando comandos | linhas ("<" no inicio = saida), janela |
| web | navegador digitando a URL e montando a pagina | url, titulo, texto, botao (use fundo="azul") |
| rede | centro com nos ligados por linhas e pulsos de dados | centro, icone, nos |
| explosao | esfera de particulas explodindo e carimbo | carimbo, icone |
| toggles | painel de configuracoes com chaves ligando | painel, itens, ligar |
| trilhas | faixas com barras de progresso, selo de alerta e item trocando de faixa | itens, selo |
| robo | robo chip com bateria, nota com checklist e barra de progresso | nota_titulo, nota, rotulo, barra, progresso, legenda |
| comentario | comentario do Instagram digitando a palavra e botao Seguir (CTA) | palavra, usuario |
| noite | lua grande, cidade em silhueta, estrelas e gato no telhado | figura ("gato" ou "nenhum") |
| infinito | simbolo infinito desenhando, com fichas caindo num feixe de luz | fichas |
| batimento | linha de batimento cardiaco | rotulo |
| comparacao | dois cartoes com VS, um certo e um errado | a={rotulo,titulo,sub,ok}, b={...} |
| frase | frase tipografica grande no centro | texto (linhas com "|", destaque com "*") |

Icones disponiveis: cadeado, estrela, raio, check, alerta, doc, casa, pin, relogio, coracao, balanca, passaporte, chave, globo, lupa, moeda, aviao, calendario, pessoa, mensagem, familia, predio.

## Limites (dizer com honestidade)
- As ilustracoes sao vetoriais simples feitas em codigo. Personagens desenhados a mao, como os do reel de referencia, sao aproximados por silhuetas.
- Logos reais de marcas so entram se ele enviar os arquivos. Sem isso, usar sigla ou icone.
- Para criar uma cena nova:
  1. escrever uma funcao `sc_nome` no motor, seguindo o padrao (GSAP com tempo absoluto, nada aleatorio no navegador);
  2. registrar a funcao em SCENES.
- Regras gerais dele:
  - nada de botao "Saiba mais" no final;
  - o video nunca termina seco: o motor deixa uma CAUDA de 0,9 s com fade.