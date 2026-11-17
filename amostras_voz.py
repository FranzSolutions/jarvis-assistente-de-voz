"""Vozes que o Jarvis pode usar, com amostras para ouvir antes de escolher.

Uso: python amostras_voz.py        (gera e toca todas)
     python amostras_voz.py 3      (toca só a 3)
O painel usa VOZES, garantir() e tocar() daqui.
"""
import asyncio
import ctypes
import sys
from pathlib import Path

import edge_tts

PASTA = Path(__file__).resolve().parent / "amostras"
FRASE = "Voz número {n}. Bom dia. Os sistemas estão prontos, e o relatório de ontem já está disponível."

# (nome no painel, voz, velocidade, tom)
VOZES = [
    ("Brasileira grave", "pt-BR-AntonioNeural", "+0%", "-6Hz"),
    ("Portugal, formal", "pt-PT-DuarteNeural", "+0%", "-4Hz"),
    ("Internacional · Andrew", "en-US-AndrewMultilingualNeural", "+0%", "-4Hz"),
    ("Internacional · Brian", "en-US-BrianMultilingualNeural", "+0%", "-6Hz"),
    ("Internacional · William", "en-AU-WilliamMultilingualNeural", "+0%", "-6Hz"),
    ("Brasileira normal", "pt-BR-AntonioNeural", "+8%", "+0Hz"),
]


def arquivo(n):
    return PASTA / f"voz{n}.mp3"


def garantir(n):
    """Gera a amostra n (1..) se ainda não existir; devolve o arquivo."""
    arq = arquivo(n)
    if not arq.exists():
        PASTA.mkdir(exist_ok=True)
        _, voz, vel, tom = VOZES[n - 1]
        asyncio.run(edge_tts.Communicate(FRASE.format(n=n), voz, rate=vel, pitch=tom).save(str(arq)))
    return arq


def tocar(arq, alias="amostra"):
    mci = ctypes.windll.winmm.mciSendStringW
    mci(f"close {alias}", None, 0, 0)  # se outra amostra ainda estiver tocando
    mci(f'open "{arq}" type mpegvideo alias {alias}', None, 0, 0)
    mci(f"play {alias} wait", None, 0, 0)
    mci(f"close {alias}", None, 0, 0)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    so = int(sys.argv[1]) if len(sys.argv) > 1 else None
    for n, (nome, voz, vel, tom) in enumerate(VOZES, 1):
        if so in (None, n):
            print(f"{n}: {nome} ({voz}, tom {tom})")
            tocar(garantir(n))
