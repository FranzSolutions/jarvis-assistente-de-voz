"""Oficina do Jarvis: ele cria e ajusta as próprias habilidades sem pedir aprovação (arquivo protegido).

Cada mudança: Claude escreve -> checagem de segurança (regras.py) -> teste num processo
separado (testar_habilidade.py) -> backup da versão anterior -> aplica e recarrega ->
avisa no painel com "desfazer". Só escreve em habilidades\\*.py e personalidade.md.
Se uma habilidade falhar ao carregar, volta sozinha para a versão anterior.
"""
import importlib.util
import json
import logging
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
from datetime import date, datetime
from pathlib import Path

import regras

PASTA = Path(__file__).resolve().parent
HAB = PASTA / "habilidades"
VERSOES = HAB / ".versoes"
REGISTRO = VERSOES / "registro.json"
PERSONALIDADE = PASTA / "personalidade.md"
log = logging.getLogger("jarvis")

API_AJUDANTE = """Módulo `ajudante` (a única forma de falar, usar a internet ou guardar dados):
- ajudante.agora() -> datetime de agora
- ajudante.falar(texto): fala em voz alta e mostra no painel
- ajudante.avisar(texto): só mostra no painel
- ajudante.agendar(segundos, texto) -> str: fala o texto depois de N segundos (enquanto o Jarvis estiver aberto)
- ajudante.buscar(url, parametros=None, json_esperado=True): GET numa URL pública (só leitura; serviços de mensagem são bloqueados). Ex.: APIs abertas sem chave, como https://api.open-meteo.com
- ajudante.abrir_site(endereco) / ajudante.abrir_programa(nome) / ajudante.pesquisar_na_web(termo) -> str
- ajudante.ler(habilidade, chave, padrao=None) / ajudante.guardar(habilidade, chave, valor): dados próprios da habilidade (JSON)
- ajudante.listar_arquivos(pasta="") / ajudante.ler_arquivo(caminho) -> str: arquivos da pasta de trabalho do Jarvis (caminho relativo, ex.: "Consultoria\\\\2026-11-01.md")
- ajudante.escrever_arquivo(caminho, conteudo, acrescentar=False) -> str: cria/altera .md, .txt, .csv, .json ou .html dentro da pasta de trabalho (nunca apaga; a versão anterior fica guardada)"""

FORMATO = '''Formato de uma habilidade (um arquivo .py em habilidades\\):
"""Uma linha dizendo o que a habilidade faz."""
import ajudante
from datetime import timedelta  # sempre "from módulo import nome"

FERRAMENTA = {
    "name": "nome_em_snake_case",
    "description": "Quando o Jarvis deve usar esta habilidade (ele decide por isto).",
    "input_schema": {"type": "object", "properties": {...}, "required": [...]},
}
EXEMPLO = {...}  # argumentos para um teste real; o teste não fala, não abre nada e não agenda

def executar(**args) -> str:
    ...  # devolve um texto curto em português com o resultado, que o Jarvis usa para responder'''

SISTEMA_OFICINA = f"""Você é a oficina do Jarvis, um assistente de voz em português no computador do usuário. Você escreve e ajusta as habilidades dele em Python, e pode reescrever o arquivo de personalidade (como ele fala). Suas mudanças são aplicadas sem aprovação humana, então capriche: código simples, robusto, com tratamento de erro e mensagens claras.

{FORMATO}

{API_AJUDANTE}

Limites que a checagem automática barra (o código é recusado se tiver):
- {regras.EXPLICACAO}
- open, exec, eval, compile, getattr, setattr, globals, input, __import__ ou qualquer nome/atributo começando com _
- global/nonlocal; mais de {regras.MAX_LINHAS} linhas

{regras.REGRAS}

Se o pedido fere essas regras ou não dá para fazer com o ajudante, use acao "nada" e explique em "fala" o que dá para fazer no lugar. Nunca tente contornar a checagem.

Respostas:
- acao: "criar" (habilidade nova), "alterar" (arquivo existente), "personalidade" (reescreve personalidade.md inteiro: instruções de estilo, até ~40 linhas, sem contradizer as regras) ou "nada".
- arquivo: nome do .py (ex.: clima.py) para criar/alterar; "personalidade.md" para personalidade; vazio em "nada".
- conteudo: o arquivo COMPLETO (código ou texto).
- resumo: uma frase curta para o painel ("criei a habilidade de clima").
- fala: uma frase curta que o Jarvis vai falar para a pessoa quando ficar pronto."""

ESQUEMA = {
    "type": "object",
    "properties": {
        "acao": {"type": "string", "enum": ["criar", "alterar", "personalidade", "nada"]},
        "arquivo": {"type": "string"},
        "conteudo": {"type": "string"},
        "resumo": {"type": "string"},
        "fala": {"type": "string"},
    },
    "required": ["acao", "arquivo", "conteudo", "resumo", "fala"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------- habilidades

def _ler_registro():
    try:
        return json.loads(REGISTRO.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _gravar_registro(reg):
    VERSOES.mkdir(parents=True, exist_ok=True)
    REGISTRO.write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")


def _voltar_versao(arquivo):
    """Restaura o último backup de `arquivo`; sem backup, tira o arquivo do caminho. Devolve o que fez."""
    for item in reversed(_ler_registro()):
        if item["arquivo"] == arquivo.name and item.get("backup") and not item.get("desfeito"):
            shutil.copyfile(VERSOES / item["backup"], arquivo)
            return f"voltei {arquivo.name} para a versão anterior"
    arquivo.rename(arquivo.with_suffix(f".quebrado-{datetime.now():%Y%m%d%H%M%S}"))
    return f"desliguei {arquivo.name}"


def carregar_habilidades(nomes_reservados=()):
    """{nome_da_ferramenta: {"ferramenta", "executar", "arquivo"}} das habilidades que passam na checagem."""
    HAB.mkdir(exist_ok=True)
    achadas = {}
    for arq in sorted(HAB.glob("*.py")):
        for tentativa in range(2):
            try:
                codigo = arq.read_text(encoding="utf-8")
                problemas = regras.checar_codigo(codigo)
                if problemas:
                    raise ValueError("checagem: " + "; ".join(problemas))
                spec = importlib.util.spec_from_file_location(f"hab_{arq.stem}", arq)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                nome = mod.FERRAMENTA["name"]
                if nome in nomes_reservados or nome in achadas:
                    raise ValueError(f"nome de ferramenta repetido: {nome}")
                achadas[nome] = {"ferramenta": dict(mod.FERRAMENTA), "executar": mod.executar, "arquivo": arq.name}
                break
            except Exception as e:
                log.error("habilidade %s não carregou: %s", arq.name, e)
                if tentativa == 0 and arq.exists():
                    log.warning(_voltar_versao(arq))
                    if not arq.exists():
                        break
    return achadas


# ---------------------------------------------------------------- oficina

class Oficina:
    def __init__(self, jarvis_obj, cliente, modelo, nomes_nativos):
        self.j = jarvis_obj
        self.cliente = cliente
        self.modelo = modelo
        self.nativos = nomes_nativos  # {nome: descrição} das ferramentas que já vêm no Jarvis
        self.fila = queue.Queue()
        self.consertos = {}  # (arquivo, dia) -> quantos consertos automáticos
        threading.Thread(target=self._trabalhar, daemon=True).start()

    # -------------------------------------------- entrada

    def _limite_do_dia(self):
        hoje = f"{date.today():%d/%m/%Y}"
        feitas = sum(1 for x in _ler_registro() if x["quando"].startswith(hoje))
        return feitas >= int(self.j_cfg().get("melhorias_por_dia", 15))

    def j_cfg(self):
        import jarvis
        return jarvis.CFG

    def pedir(self, pedido, fala_da_pessoa):
        if self._limite_do_dia():
            return "Já fiz o limite de melhorias de hoje. Amanhã eu faço essa."
        self.fila.put({"tipo": "pedido", "pedido": pedido, "fala": fala_da_pessoa})
        return "Pedido de melhoria na fila: vou escrever, testar e aplicar sozinho em um ou dois minutos, e aviso quando ficar pronto."

    def consertar(self, arquivo, erro):
        """Chamado quando uma habilidade dá erro de verdade: tenta corrigir sozinho (até 2x por dia por arquivo)."""
        chave = (arquivo, date.today())
        if self.consertos.get(chave, 0) >= 2 or self._limite_do_dia():
            return
        self.consertos[chave] = self.consertos.get(chave, 0) + 1
        self.fila.put({"tipo": "conserto", "arquivo": arquivo, "erro": erro})

    # -------------------------------------------- trabalho

    def _trabalhar(self):
        while True:
            tarefa = self.fila.get()
            try:
                self._fazer(tarefa)
            except Exception as e:
                log.exception("oficina falhou")
                self._anunciar(f"tentei me melhorar mas deu erro ({e})", None, falar=False)

    def _contexto(self):
        partes = ["Ferramentas que já vêm no Jarvis (não recrie): " +
                  "; ".join(f"{n}: {d}" for n, d in self.nativos.items())]
        habs = sorted(HAB.glob("*.py"))
        if habs:
            partes.append("Habilidades atuais:\n" + "\n\n".join(
                f"### {h.name}\n```python\n{h.read_text(encoding='utf-8')}\n```" for h in habs))
        else:
            partes.append("Ainda não há habilidades.")
        pers = PERSONALIDADE.read_text(encoding="utf-8") if PERSONALIDADE.exists() else "(vazio)"
        partes.append(f"personalidade.md atual:\n{pers}")
        return "\n\n".join(partes)

    def _fazer(self, tarefa):
        if tarefa["tipo"] == "pedido":
            pedido = (f"Fala da pessoa (é isto que vale): «{tarefa['fala']}»\n"
                      f"Como o Jarvis entendeu: «{tarefa['pedido']}»\n"
                      "Faça a mudança que atende o que a pessoa falou.")
        else:
            pedido = (f"A habilidade {tarefa['arquivo']} deu erro quando a pessoa usou:\n{tarefa['erro']}\n"
                      "Corrija (acao alterar), mantendo o que ela já fazia.")
        mensagens = [{"role": "user", "content": f"{self._contexto()}\n\n{pedido}"}]
        recusa_anterior = ""
        for tentativa in range(3):
            if self.cliente is None:  # pela assinatura do Claude
                import claude_local
                _, plano, _ = claude_local.perguntar_uma_vez(
                    mensagens[0]["content"] + recusa_anterior, sistema=SISTEMA_OFICINA, modelo=self.modelo,
                    esforco="high", esquema=ESQUEMA)
                if not plano:
                    raise RuntimeError("a oficina não devolveu o plano")
            else:
                resp = self.cliente.beta.messages.create(
                    model=self.modelo,
                    max_tokens=16000,
                    system=SISTEMA_OFICINA,
                    messages=mensagens,
                    output_config={"effort": "high", "format": {"type": "json_schema", "schema": ESQUEMA}},
                    betas=["server-side-fallback-2026-07-01"],
                    fallbacks="default",
                )
                if resp.stop_reason != "end_turn":
                    raise RuntimeError(f"a escrita parou ({resp.stop_reason})")
                plano = json.loads(next(b.text for b in resp.content if b.type == "text"))
            log.info("oficina: %s %s — %s", plano["acao"], plano["arquivo"], plano["resumo"])
            if plano["acao"] == "nada":
                self._anunciar(plano["resumo"], None, fala=plano["fala"])
                return
            erro = self._validar_e_aplicar(plano)
            if erro is None:
                return
            log.warning("oficina, tentativa %d recusada: %s", tentativa + 1, erro)
            if self.cliente is None:
                recusa_anterior = (f"\n\nSua tentativa anterior ({plano['arquivo']}) não passou: {erro}\n"
                                   f"Arquivo que você mandou:\n```\n{plano['conteudo']}\n```\nCorrija e mande o arquivo completo de novo.")
            else:
                mensagens += [{"role": "assistant", "content": resp.content},
                              {"role": "user", "content": f"Não passou: {erro}\nCorrija e mande o arquivo completo de novo."}]
        self._anunciar("não consegui fazer essa melhoria passar nos testes", None,
                       fala="Tentei aprender isso, mas não passou nos meus testes. Pode me explicar de outro jeito?")

    def _validar_e_aplicar(self, plano):
        """None se aplicou; senão o motivo da recusa (volta para o Claude corrigir)."""
        conteudo = plano["conteudo"]
        if plano["acao"] == "personalidade":
            if len(conteudo) > 4000:
                return "personalidade longa demais (máx. ~4000 caracteres)"
            self._aplicar(PERSONALIDADE, conteudo, plano)
            return None
        nome = plano["arquivo"].strip()
        if not re.fullmatch(r"[a-z][a-z0-9_]{2,40}\.py", nome) or nome in regras.PROTEGIDOS:
            return f"nome de arquivo inválido ou protegido: {nome!r} (use letras minúsculas, ex.: clima.py)"
        destino = HAB / nome
        if plano["acao"] == "criar" and destino.exists():
            return f"{nome} já existe; use acao alterar ou outro nome"
        if plano["acao"] == "alterar" and not destino.exists():
            return f"{nome} não existe; use acao criar"
        problemas = regras.checar_codigo(conteudo)
        if problemas:
            return "checagem de segurança: " + "; ".join(problemas)
        m = re.search(r'["\']name["\']\s*:\s*["\']([a-z0-9_]+)["\']', conteudo)
        outros = {n for n, h in self.j.habilidades.items() if h["arquivo"] != nome}
        if m and (m.group(1) in self.nativos or m.group(1) in outros):
            return f"o nome de ferramenta '{m.group(1)}' já existe; escolha outro"
        VERSOES.mkdir(parents=True, exist_ok=True)
        rascunho = VERSOES / f"rascunho_{nome}"
        rascunho.write_text(conteudo, encoding="utf-8")
        python = Path(sys.executable).with_name("python.exe")  # pythonw não devolve a saída
        try:
            r = subprocess.run([str(python), "-I", str(PASTA / "testar_habilidade.py"), str(rascunho)],
                               capture_output=True, text=True, encoding="utf-8", timeout=45,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            resultado = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {
                "ok": False, "erro": (r.stderr or "o teste não respondeu")[-1500:]}
        except subprocess.TimeoutExpired:
            resultado = {"ok": False, "erro": "o teste passou de 45 segundos (travou ou está lento demais)"}
        finally:
            rascunho.unlink(missing_ok=True)
        if not resultado["ok"]:
            return "teste falhou: " + resultado["erro"]
        log.info("oficina: teste ok -> %s | efeitos: %s", resultado.get("saida", "")[:200], resultado.get("efeitos"))
        self._aplicar(destino, conteudo, plano)
        return None

    def _aplicar(self, destino, conteudo, plano):
        VERSOES.mkdir(parents=True, exist_ok=True)
        backup = None
        if destino.exists():
            backup = f"{destino.stem}_{datetime.now():%Y%m%d_%H%M%S}{destino.suffix}"
            shutil.copyfile(destino, VERSOES / backup)
        destino.write_text(conteudo, encoding="utf-8")
        reg = _ler_registro()
        ident = f"{int(time.time())}"
        reg.append({"id": ident, "quando": f"{datetime.now():%d/%m/%Y %H:%M}", "arquivo": destino.name,
                    "backup": backup, "resumo": plano["resumo"], "desfeito": False})
        _gravar_registro(reg)
        self.j.recarregar_habilidades()
        self._anunciar(plano["resumo"], ident, fala=plano["fala"])

    def desfazer(self, ident):
        reg = _ler_registro()
        item = next((x for x in reg if x["id"] == ident), None)
        if not item or item["desfeito"]:
            return "Essa mudança já foi desfeita."
        destino = PERSONALIDADE if item["arquivo"] == PERSONALIDADE.name else HAB / item["arquivo"]
        if item["backup"]:
            shutil.copyfile(VERSOES / item["backup"], destino)
        else:  # era um arquivo novo criado pela oficina
            destino.unlink(missing_ok=True)
        item["desfeito"] = True
        _gravar_registro(reg)
        self.j.recarregar_habilidades()
        import jarvis
        jarvis.avisar("aprendi", f"desfeito: {item['resumo']}")
        return "Desfeito."

    def _anunciar(self, resumo, ident, fala=None, falar=True):
        import jarvis
        if ident:
            jarvis.avisar("melhoria", {"id": ident, "texto": resumo})
        else:
            jarvis.avisar("acao", f"oficina: {resumo}")
        if falar and fala:
            self.j.falar_avulso(fala)
