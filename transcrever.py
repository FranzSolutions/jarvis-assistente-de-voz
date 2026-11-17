"""Transcreve um arquivo de áudio com o faster-whisper (roda no PC, sem custo).

Uso: <python com faster-whisper> transcrever.py caminho\\do\\audio [tamanho_do_modelo] [pasta_dos_modelos]
     (o jarvis.py passa os dois últimos a partir do config: modelo_whisper e pasta_modelos_whisper)
Imprime uma linha JSON: {"texto", "duracao", "idioma", "trechos": [{"inicio", "fim", "texto"}]} ou {"erro"}.
Usa a placa de vídeo se der; senão, o processador.
"""
import json
import os
import site
import sys
from pathlib import Path

# onde o faster-whisper baixa/guarda os modelos (padrão: modelos-whisper\ dentro do projeto)
MODELOS = Path(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3] else Path(__file__).resolve().parent / "modelos-whisper"

# bibliotecas da placa de vídeo (pacotes nvidia-cublas/cudnn do pip): o Windows só as acha se estiverem no PATH
for _base in site.getsitepackages():
    for _bin in Path(_base).glob("nvidia/*/bin"):
        os.environ["PATH"] = str(_bin) + os.pathsep + os.environ["PATH"]
        os.add_dll_directory(str(_bin))

DISPOSITIVO = {"usado": "?"}


def carregar(tamanho):
    from faster_whisper import WhisperModel
    for dispositivo, tipo in (("cuda", "float16"), ("cpu", "int8")):
        try:
            modelo = WhisperModel(tamanho, device=dispositivo, compute_type=tipo, download_root=str(MODELOS))
            DISPOSITIVO["usado"] = "placa de vídeo" if dispositivo == "cuda" else "processador"
            return modelo
        except Exception:
            continue
    raise RuntimeError("não consegui carregar o Whisper")


def transcrever(arquivo, tamanho="small"):
    modelo = carregar(tamanho)
    try:
        partes, info = modelo.transcribe(str(arquivo), language="pt", vad_filter=True, beam_size=5)
        trechos = [{"inicio": round(p.start, 1), "fim": round(p.end, 1), "texto": p.text.strip()} for p in partes]
    except RuntimeError as e:  # a placa de vídeo falhou no meio (falta de biblioteca/memória): refaz no processador
        if "cuda" not in str(e).lower() and "cublas" not in str(e).lower() and "cudnn" not in str(e).lower():
            raise
        from faster_whisper import WhisperModel
        modelo = WhisperModel(tamanho, device="cpu", compute_type="int8", download_root=str(MODELOS))
        DISPOSITIVO["usado"] = "processador (a placa falhou)"
        partes, info = modelo.transcribe(str(arquivo), language="pt", vad_filter=True, beam_size=5)
        trechos = [{"inicio": round(p.start, 1), "fim": round(p.end, 1), "texto": p.text.strip()} for p in partes]
    return {"texto": " ".join(t["texto"] for t in trechos).strip(), "duracao": round(info.duration, 1),
            "idioma": info.language, "trechos": trechos, "dispositivo": DISPOSITIVO["usado"]}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        print(json.dumps(transcrever(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else "small"),
                         ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"erro": str(e)}, ensure_ascii=False))
