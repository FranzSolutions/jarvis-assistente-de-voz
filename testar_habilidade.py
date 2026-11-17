"""Testa uma habilidade num processo separado, sem efeitos reais (arquivo protegido).

Uso: python -I testar_habilidade.py caminho\\da\\habilidade.py
Imprime uma linha JSON: {"ok": bool, "erro": str, "saida": str, "efeitos": [...]}.
"""
import importlib.util
import json
import sys
import traceback
import types
from pathlib import Path

PASTA = Path(__file__).resolve().parent
sys.path.insert(0, str(PASTA))
import ajudante as real  # noqa: E402
import regras  # noqa: E402

efeitos = []
memoria = {}
falso = types.ModuleType("ajudante")
falso.agora = real.agora
falso.buscar = real.buscar
falso.falar = lambda texto: efeitos.append(f"falaria: {texto}")
falso.avisar = lambda texto: efeitos.append(f"avisaria: {texto}")
falso.agendar = lambda segundos, texto: efeitos.append(f"agendaria em {segundos}s: {texto}") or f"agendado para daqui a {int(segundos)} s"
falso.abrir_site = lambda endereco: efeitos.append(f"abriria o site {endereco}") or f"Abri {endereco}."
falso.abrir_programa = lambda nome: efeitos.append(f"abriria o programa {nome}") or f"Abri {nome}."
falso.pesquisar_na_web = lambda termo: efeitos.append(f"pesquisaria {termo}") or f"Abri a pesquisa por '{termo}'."
falso.ler = lambda hab, chave, padrao=None: memoria.get((hab, chave), padrao)
falso.guardar = lambda hab, chave, valor: memoria.__setitem__((hab, chave), valor)
arquivos = {}  # o que a habilidade "escreveu" no teste (nada vai para o disco)
falso.listar_arquivos = real.listar_arquivos
falso.ler_arquivo = lambda caminho: arquivos.get(str(caminho)) or real.ler_arquivo(caminho)


def _escrever_falso(caminho, conteudo, acrescentar=False):
    efeitos.append(f"escreveria em <pasta de trabalho>\\{caminho} ({len(str(conteudo))} caracteres)")
    arquivos[str(caminho)] = (arquivos.get(str(caminho), "") if acrescentar else "") + str(conteudo)
    return f"Salvo em <pasta de trabalho>\\{caminho}."


falso.escrever_arquivo = _escrever_falso
sys.modules["ajudante"] = falso


def testar(caminho):
    codigo = Path(caminho).read_text(encoding="utf-8")
    problemas = regras.checar_codigo(codigo)
    if problemas:
        return {"ok": False, "erro": "checagem de segurança: " + "; ".join(problemas)}
    spec = importlib.util.spec_from_file_location("habilidade_em_teste", caminho)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    f = mod.FERRAMENTA
    if not (isinstance(f, dict) and isinstance(f.get("name"), str) and isinstance(f.get("description"), str)
            and isinstance(f.get("input_schema"), dict) and f["input_schema"].get("type") == "object"):
        return {"ok": False, "erro": "FERRAMENTA precisa de name, description e input_schema do tipo object"}
    exemplo = getattr(mod, "EXEMPLO", None)
    if exemplo is None:
        return {"ok": False, "erro": "falta EXEMPLO (argumentos para o teste)"}
    saida = mod.executar(**exemplo)
    if not isinstance(saida, str) or not saida.strip():
        return {"ok": False, "erro": f"executar devolveu {type(saida).__name__} vazio ou que não é texto"}
    return {"ok": True, "erro": "", "saida": saida[:1500], "efeitos": efeitos}


if __name__ == "__main__":
    try:
        resultado = testar(sys.argv[1])
    except Exception:
        resultado = {"ok": False, "erro": traceback.format_exc(limit=4)[-1500:]}
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(resultado, ensure_ascii=False))
