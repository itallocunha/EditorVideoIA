"""Plano PULSO de demonstracao (takes do video 4)."""
STYLE = "pulso"
WORK = "work_exemplo"            # pasta de trabalho
OUT = "saida/exemplo.mp4"
TAKES = {k: f"takes/take_{k}.mp4" for k in (1, 2, 3, 4)}   # seus takes, em ordem
WORDS_JSON = "takes/words_medium.json"   # transcricao com tempo por palavra (faster-whisper)
WORD_FIX = {(1, 0): "Manuel", (1, 2): "Manoel."}
SEGMENTS = [
    (1, 0, 2,   ("push", 1.30, 1.45), ("top", [[["Man[u]el"], ["ou", "Man[o]el?"]]])),
    (1, 3, 10,  ("static", 1.0),      ("single",)),
    (2, 0, 1,   ("bw", 1.35),         ("single",)),
    (2, 2, 8,   ("static", 1.0),      ("single",)),
    (2, 9, 17,  ("static", 1.3),      ("single",)),
    (3, 0, 5,   ("static", 1.3),      ("single",)),
    (3, 6, 12,  ("static", 1.0),      ("single",)),
    (3, 13, 15, ("push", 1.0, 1.25),  ("kinetic", [[["*Qual*", "é", "*qual?*"]]])),
    (4, 0, 3,   ("static", 1.0),      ("single",)),
    (4, 4, 12,  ("bw", 1.3),          ("single",)),
    (4, 13, 18, ("push", 1.0, 1.2),   ("single",)),
]
ARC_TITLES = [(1, 3, "uma letra", 1)]
PILLS = [(2, 6, "≋", "Verificar"), (3, 11, "!", "Exigência"), (4, 6, "✂", "Correção")]
CARD_SCENES = [(2, 12, 2.3, "a conservatória compara", [("✓", "Nomes"), ("✓", "Datas"), ("✓", "Certidões")])]
SCRIBBLE_TITLES = [(4, 1, "Depende", "do documento", 8)]
FLASH_BEFORE_SEGMENT = [5]
OUTRO = [(4, None, 9.45, ("static", 1.0)), (4, 8.45, 9.45, ("static", 1.0))]
OUTRO_FADE = 0.5
ENDING = (4, 18, "O que importa é a", "ordem.")
