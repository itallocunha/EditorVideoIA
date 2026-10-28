"""Plano NARRADO NEON de demonstracao (narracao = takes do video 4)."""
WORK = "work_exemplo"            # pasta de trabalho
OUT = "saida/exemplo.mp4"
NARRACAO = {k: f"takes/take_{k}.wav" for k in (1, 2, 3, 4)}   # seus takes, em ordem
WORDS_JSON = "takes/words_medium.json"   # transcricao com tempo por palavra (faster-whisper)
CORRIGIR = {(1, 0): "Manuel", (1, 2): "Manoel."}
CENAS = [
    dict(tipo="comparacao", titulo="Manuel ou|*Manoel?*", secao="01 /04 · NOMES",
         a=dict(rotulo="CERTIDÃO A", titulo="MANUEL", sub="nascimento", ok=True),
         b=dict(rotulo="CERTIDÃO B", titulo="MANOEL", sub="casamento", ok=False)),
    dict(em=(1, 3), tipo="icone", icone="alerta", titulo="Uma letra pode|*gerar exigência*", transicao="vidro", rotulo="no seu processo"),
    dict(em=(2, 0), tipo="etiqueta", texto="BOBEIRA?", titulo="Parece|*bobeira*"),
    dict(em=(2, 3), tipo="icone", icone="lupa", titulo="Na hora de|*verificar*", secao="02 /04 · ANÁLISE", rotulo="os documentos"),
    dict(em=(2, 9), tipo="rede", centro="Conserv.", icone="balanca", titulo="A conservatória|*compara tudo*",
         nos=["Nomes", "Datas", "Filiação", "Local", "Certidões", "Registos"]),
    dict(em=(3, 0), tipo="lista", rotulo="DIFERENÇAS", rotulo_card="TIPO", secao="03 /04",
         itens=[dict(titulo="Passa batido", icone="check", sub="sem problema", selo="OK", em=(3, 0)),
                dict(titulo="Gera exigência", icone="alerta", sub="processo parado", selo="ATENÇÃO", em=(3, 6))]),
    dict(em=(3, 13), tipo="explosao", carimbo="QUAL É QUAL?", icone="lupa", titulo="*Qual é qual?*"),
    dict(em=(4, 0), tipo="icone", icone="doc", titulo="Depende do|*documento*", secao="04 /04 · CORREÇÃO", transicao="vidro"),
    dict(em=(4, 4), tipo="toggles", painel="CORREÇÃO", titulo="Correção de|*várias maneiras*", itens=["Caminho 1", "Caminho 2", "Caminho 3"]),
    dict(em=(4, 13), tipo="frase", titulo="", texto="O que importa|*é a ordem*"),
]
