"""O que uma habilidade do Jarvis pode fazer (arquivo protegido).

As habilidades não abrem arquivos nem a rede sozinhas (a checagem em regras.py barra);
tudo passa por aqui, já dentro das regras: internet só leitura, sem sites de mensagens,
dados guardados só na pasta da própria habilidade.
"""
import json
import re
import threading
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

PASTA_DADOS = Path(__file__).resolve().parent / "habilidades" / "dados"
# serviços de mensagem/postagem: nem leitura, para nenhuma habilidade "mandar" algo por GET
BLOQUEADOS = re.compile(
    r"(telegram|whatsapp|twilio|discord(app)?\.com/api|hooks\.slack|slack\.com/api|graph\.facebook|instagram|"
    r"api\.twitter|api\.x\.com|sendgrid|mailgun|mandrill|smtp|zapier|ifttt|webhook|n8n|make\.com|pipedream)", re.I)

_jarvis = None  # o Jarvis em execução; ligado por conectar()


def conectar(jarvis_obj):
    global _jarvis
    _jarvis = jarvis_obj


def agora():
    return datetime.now()


def falar(texto):
    """Fala em voz alta e mostra no painel."""
    if _jarvis:
        _jarvis.falar_avulso(str(texto))


def avisar(texto):
    """Só mostra no painel (sem voz)."""
    import jarvis
    jarvis.avisar("acao", str(texto))


def agendar(segundos, texto):
    """Fala `texto` daqui a `segundos` (vale enquanto o Jarvis estiver aberto)."""
    t = threading.Timer(float(segundos), falar, args=(texto,))
    t.daemon = True
    t.start()
    return f"agendado para daqui a {int(segundos)} s"


def buscar(url, parametros=None, json_esperado=True):
    """GET numa URL pública (só leitura). Devolve o JSON (dict/list) ou o texto."""
    if not re.match(r"^https?://", url, re.I):
        raise ValueError("só endereços http/https")
    if BLOQUEADOS.search(url):
        raise PermissionError("serviço de mensagens/postagem bloqueado pelas regras")
    if parametros:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(parametros)
    req = urllib.request.Request(url, headers={"User-Agent": "Jarvis/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        bruto = r.read(2_000_000).decode("utf-8", errors="replace")
    return json.loads(bruto) if json_esperado else bruto


def abrir_site(endereco):
    import jarvis
    return jarvis.abrir_site(endereco)


def abrir_programa(nome):
    import jarvis
    return jarvis.abrir_programa(nome)


def pesquisar_na_web(termo):
    import jarvis
    return jarvis.pesquisar_na_web(termo)


def listar_arquivos(pasta=""):
    """Arquivos da pasta de trabalho (texto, um por linha)."""
    import jarvis
    return jarvis.listar_documentos(pasta)


def ler_arquivo(caminho):
    """Texto de um arquivo dentro da pasta de trabalho."""
    import jarvis
    return jarvis.ler_documento(caminho)


def escrever_arquivo(caminho, conteudo, acrescentar=False):
    """Cria/altera um .md, .txt, .csv, .json ou .html dentro da pasta de trabalho (nunca apaga)."""
    import jarvis
    return jarvis.escrever_documento(caminho, str(conteudo), "acrescentar" if acrescentar else "substituir")


def _arquivo_dados(habilidade):
    nome = re.sub(r"[^a-z0-9_]", "", str(habilidade).lower()) or "geral"
    PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    return PASTA_DADOS / f"{nome}.json"


def ler(habilidade, chave, padrao=None):
    """Lê um dado que a própria habilidade guardou."""
    try:
        return json.loads(_arquivo_dados(habilidade).read_text(encoding="utf-8")).get(chave, padrao)
    except (FileNotFoundError, json.JSONDecodeError):
        return padrao


def guardar(habilidade, chave, valor):
    """Guarda um dado (texto, número, lista ou dicionário) da habilidade."""
    arq = _arquivo_dados(habilidade)
    try:
        dados = json.loads(arq.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        dados = {}
    dados[chave] = valor
    arq.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
