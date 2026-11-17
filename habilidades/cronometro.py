"""Cronômetro: agenda avisos falados depois de X horas/minutos/segundos e diz quanto falta para cada um."""
import ajudante
from datetime import datetime

NOME = "cronometro"
LIMITE_SEGUNDOS = 24 * 3600

FERRAMENTA = {
    "name": "cronometro",
    "description": (
        "Cronômetro/timer. Use acao='criar' quando a pessoa disser algo como 'me avisa em X minutos (ou segundos) para tal coisa' "
        "ou 'põe um timer de 1 minuto e 30 segundos'; converta o tempo falado em horas, minutos e segundos "
        "(ex.: '1 minuto e meio' = minutos 1, segundos 30) e passe o motivo. Quando o tempo acabar, o Jarvis fala o aviso em voz alta. "
        "Vários cronômetros podem rodar ao mesmo tempo. Use acao='listar' quando a pessoa perguntar quanto falta ou quais timers estão rodando. "
        "Esta habilidade não consegue cancelar um aviso já agendado; se pedirem para cancelar, explique isso. "
        "Os avisos só tocam enquanto o Jarvis estiver aberto."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "acao": {
                "type": "string",
                "enum": ["criar", "listar"],
                "description": "'criar' para um novo cronômetro, 'listar' para ver quanto falta.",
            },
            "horas": {"type": "number", "description": "Horas do cronômetro (opcional)."},
            "minutos": {"type": "number", "description": "Minutos do cronômetro (opcional)."},
            "segundos": {"type": "number", "description": "Segundos do cronômetro (opcional)."},
            "motivo": {
                "type": "string",
                "description": "Para que é o aviso, ex.: 'tirar o bolo do forno', 'ligar pro cliente'.",
            },
        },
        "required": ["acao"],
    },
}

EXEMPLO = {"acao": "criar", "minutos": 1, "segundos": 30, "motivo": "teste do cronômetro"}


def plural(numero, singular, plural_txt):
    return f"{numero} {singular if numero == 1 else plural_txt}"


def formatar_duracao(total):
    total = int(round(total))
    if total <= 0:
        return "menos de 1 segundo"
    horas, resto = divmod(total, 3600)
    minutos, segundos = divmod(resto, 60)
    partes = []
    if horas:
        partes.append(plural(horas, "hora", "horas"))
    if minutos:
        partes.append(plural(minutos, "minuto", "minutos"))
    if segundos:
        partes.append(plural(segundos, "segundo", "segundos"))
    if len(partes) == 1:
        return partes[0]
    return ", ".join(partes[:-1]) + " e " + partes[-1]


def para_numero(valor, nome):
    if valor is None or valor == "":
        return 0.0
    try:
        numero = float(str(valor).replace(",", ".").strip())
    except (TypeError, ValueError):
        raise ValueError(f"Não entendi o valor de {nome}: {valor}.")
    if numero < 0:
        raise ValueError(f"O valor de {nome} não pode ser negativo.")
    return numero


def carregar_ativos(agora):
    try:
        lista = ajudante.ler(NOME, "timers", []) or []
    except Exception:
        lista = []
    ativos = []
    for item in lista:
        try:
            fim = datetime.fromisoformat(item["fim"])
            if fim > agora:
                ativos.append({"motivo": str(item.get("motivo", "")), "fim": item["fim"]})
        except Exception:
            continue
    return ativos


def salvar(ativos):
    try:
        ajudante.guardar(NOME, "timers", ativos)
    except Exception:
        pass


def criar(args):
    try:
        horas = para_numero(args.get("horas"), "horas")
        minutos = para_numero(args.get("minutos"), "minutos")
        segundos = para_numero(args.get("segundos"), "segundos")
    except ValueError as erro:
        return str(erro)

    total = int(round(horas * 3600 + minutos * 60 + segundos))
    if total <= 0:
        return "Preciso de um tempo maior que zero. Diga, por exemplo: me avisa em 5 minutos."
    if total > LIMITE_SEGUNDOS:
        return "Esse tempo é longo demais para o cronômetro; o máximo é 24 horas."

    motivo = str(args.get("motivo") or "").strip().rstrip(".")
    if motivo:
        texto = f"Deu o tempo: {motivo}."
    else:
        texto = "Deu o tempo do cronômetro!"

    try:
        ajudante.agendar(total, texto)
    except Exception as erro:
        return f"Não consegui agendar o aviso: {erro}"

    agora = ajudante.agora()
    ativos = carregar_ativos(agora)
    fim = datetime.fromtimestamp(agora.timestamp() + total, agora.tzinfo) if agora.tzinfo else datetime.fromtimestamp(agora.timestamp() + total)
    ativos.append({"motivo": motivo, "fim": fim.isoformat()})
    salvar(ativos)

    duracao = formatar_duracao(total)
    hora_fim = fim.strftime("%H:%M:%S")
    if motivo:
        return f"Beleza, te aviso em {duracao} para {motivo} (às {hora_fim})."
    return f"Beleza, te aviso em {duracao} (às {hora_fim})."


def listar():
    agora = ajudante.agora()
    ativos = carregar_ativos(agora)
    salvar(ativos)
    if not ativos:
        return "Não tem nenhum cronômetro rodando agora."
    ativos.sort(key=lambda item: item["fim"])
    linhas = []
    for item in ativos:
        try:
            fim = datetime.fromisoformat(item["fim"])
            falta = (fim - agora).total_seconds()
        except Exception:
            continue
        motivo = item.get("motivo") or "cronômetro sem motivo"
        linhas.append(f"faltam {formatar_duracao(falta)} para {motivo}")
    if not linhas:
        return "Não tem nenhum cronômetro rodando agora."
    if len(linhas) == 1:
        return "Tem 1 cronômetro rodando: " + linhas[0] + "."
    return f"Tem {len(linhas)} cronômetros rodando: " + "; ".join(linhas) + "."


def executar(**args) -> str:
    acao = str(args.get("acao") or "criar").strip().lower()
    try:
        if acao == "listar":
            return listar()
        if acao == "criar":
            return criar(args)
        return "Não entendi o que fazer com o cronômetro. Posso criar um aviso ou dizer quanto falta."
    except Exception as erro:
        return f"Deu um problema no cronômetro: {erro}"
