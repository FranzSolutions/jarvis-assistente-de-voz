"""Tarefeiro do Jarvis (arquivo protegido): passa pautas maiores para o Claude Code resolver no PC.

Roda o Claude Code de linha de comando sozinho, em segundo plano, com a chave do Jarvis, no modo
automático (ações seguras passam; arriscadas são barradas e nada fica esperando "permitir") e com as
mesmas regras do Jarvis. O resultado completo fica em Tarefas, dentro da pasta de trabalho, e o Jarvis
fala o resumo.
"""
import json
import logging
import os
import queue
import re
import subprocess
import threading
from datetime import datetime
from pathlib import Path

import regras

log = logging.getLogger("jarvis")
PASTA = Path(__file__).resolve().parent
CONFIG_CLI = PASTA / "claude-code-config"  # configuração própria: usa a chave do Jarvis, não o login do PC

# {trabalho} e {codigo} são trocados pelas pastas de verdade em rodar()
INSTRUCOES = """Você foi chamado pelo Jarvis, o assistente de voz desta pessoa, para resolver uma pauta no computador dela (Windows). A pessoa não está olhando: resolva de ponta a ponta, sem fazer perguntas. Se faltar alguma informação, faça a escolha mais sensata e diga qual foi.
Pastas: {trabalho} é a pasta de trabalho, onde você pode criar e alterar arquivos (relatórios em {trabalho}\\Tarefas). O caderno dos projetos da pessoa está em {trabalho}\\Projetos.md.
""" + regras.REGRAS + """
Também não mexa no código do próprio Jarvis ({codigo}).
Responda em português do Brasil, direto. Na última linha, escreva: RESUMO PARA FALAR: <uma ou duas frases curtas, boas de ouvir em voz alta, com o resultado>."""


def pasta_trabalho(cfg):
    """A mesma pasta de trabalho do jarvis.py (config "pasta_trabalho"; padrão: trabalho\\ dentro do projeto)."""
    return Path(cfg.get("pasta_trabalho") or str(PASTA / "trabalho"))


def pela_assinatura(cfg):
    return cfg.get("cerebro", "assinatura") != "api"


def comando_cli(cfg):
    if cfg.get("claude_code_cmd"):
        return cfg["claude_code_cmd"]
    import claude_local
    return str(claude_local.CLI)


class Tarefeiro:
    def __init__(self, jarvis_obj, cfg):
        self.j = jarvis_obj
        self.cfg = cfg
        self.fila = queue.Queue()
        self.ocupado = False
        threading.Thread(target=self._trabalhar, daemon=True).start()

    def pedir(self, pauta):
        if not Path(comando_cli(self.cfg)).exists():
            return f"O Claude Code não está instalado em {comando_cli(self.cfg)}."
        espera = self.fila.qsize() + (1 if self.ocupado else 0)
        self.fila.put(pauta)
        return ("Passei a pauta para o Claude Code; ele trabalha em segundo plano e eu aviso quando terminar."
                + (f" Antes dela ainda tem {espera} na fila." if espera else ""))

    def _trabalhar(self):
        import jarvis
        while True:
            pauta = self.fila.get()
            self.ocupado = True
            jarvis.avisar("acao", f"Claude Code trabalhando: {pauta[:90]}")
            try:
                arquivo, resumo, ok = self.rodar(pauta)
                jarvis.avisar("tarefa", {"texto": resumo, "arquivo": str(arquivo)})
                self.j.falar_avulso(("Terminei a tarefa. " if ok else "A tarefa não deu certo. ") + resumo)
            except Exception as e:
                log.exception("tarefa do Claude Code falhou")
                jarvis.avisar("erro", f"a tarefa falhou: {e}")
                self.j.falar_avulso("A tarefa que passei para o Claude Code falhou. Deixei o erro no painel.")
            finally:
                self.ocupado = False

    def rodar(self, pauta):
        """Roda o Claude Code e salva o relatório. Devolve (arquivo, resumo para falar, deu_certo)."""
        CONFIG_CLI.mkdir(exist_ok=True)
        trabalho = pasta_trabalho(self.cfg)
        pasta = trabalho / "Tarefas"
        pasta.mkdir(parents=True, exist_ok=True)
        amb = {k: v for k, v in os.environ.items() if not k.startswith(("ANTHROPIC_", "CLAUDE"))}
        if pela_assinatura(self.cfg):  # login da assinatura do Claude: não gasta crédito da API
            import claude_local
            amb.update(claude_local.ambiente())
        else:
            amb["ANTHROPIC_API_KEY"] = self.cfg.get("anthropic_api_key") or ""
            amb["CLAUDE_CONFIG_DIR"] = str(CONFIG_CLI)
        inicio = datetime.now()
        try:
            r = subprocess.run(
                [comando_cli(self.cfg), "-p", pauta + "\n\n(Na última linha da resposta: RESUMO PARA FALAR: <uma ou duas frases>.)",
                 "--output-format", "json",
                 "--model", self.cfg.get("modelo_tarefas", "claude-opus-5-5"),
                 "--permission-mode", "auto", "--permission-prompts", "none",
                 "--max-budget-usd", str(self.cfg.get("orcamento_tarefa_usd", 2)),
                 "--append-system-prompt", INSTRUCOES.replace("{trabalho}", str(trabalho)).replace("{codigo}", str(PASTA))],
                cwd=pasta, env=amb, capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=int(self.cfg.get("minutos_tarefa", 30)) * 60, creationflags=subprocess.CREATE_NO_WINDOW)
            dados = json.loads(r.stdout)
        except subprocess.TimeoutExpired:
            dados = {"is_error": True, "result": f"passou de {self.cfg.get('minutos_tarefa', 30)} minutos e foi interrompida"}
        except json.JSONDecodeError:
            dados = {"is_error": True, "result": (r.stdout or r.stderr or "sem resposta")[-1500:]}
        texto = str(dados.get("result") or "").strip()
        ok = not dados.get("is_error") and dados.get("subtype") == "success"
        m = re.search(r"RESUMO PARA FALAR:\s*(.+)\s*$", texto, re.S)
        resumo = re.sub(r"[*_`#]", "", m[1]).strip() if m else self._resumir(texto)
        negadas = dados.get("permission_denials") or []
        custo = dados.get("total_cost_usd") or 0
        arquivo = pasta / f"{inicio:%Y-%m-%d-%H%M%S}.md"
        arquivo.write_text(
            f"# Tarefa de {inicio:%d/%m/%Y %H:%M}\n\n**Pauta:** {pauta}\n\n"
            f"**Situação:** {'concluída' if ok else 'não concluída'} · {dados.get('num_turns', '?')} passos · "
            + (f"pela assinatura (sem custo extra; equivaleria a US$ {custo:.2f} na API)" if pela_assinatura(self.cfg)
               else f"US$ {custo:.2f}")
            + f" · {(datetime.now() - inicio).seconds // 60} min\n\n"
            + (f"**Ações barradas pela segurança:** {json.dumps(negadas, ensure_ascii=False)[:1500]}\n\n" if negadas else "")
            + f"---\n\n{texto}\n", encoding="utf-8")
        log.info("tarefa do Claude Code: %s | ok=%s | US$ %.2f | %d barradas", arquivo.name, ok, custo, len(negadas))
        if negadas:
            resumo += " Algumas ações foram barradas pela segurança; detalhes no relatório."
        return arquivo, resumo, ok

    def _resumir(self, texto):
        """Quando o Claude Code não deixa o resumo pronto: uma ou duas frases faladas, feitas por um modelo rápido."""
        if not texto:
            return "terminou sem resposta"
        pedido = ("Resuma em uma ou duas frases curtas, para ler em voz alta, sem markdown nem listas, o resultado "
                  f"abaixo:\n\n{texto[:8000]}")
        try:
            if pela_assinatura(self.cfg):
                import claude_local
                return claude_local.perguntar_uma_vez(pedido, modelo="claude-haiku-5-5", esforco="low", timeout=120)[0]
            import anthropic
            cliente = anthropic.Anthropic(api_key=self.cfg.get("anthropic_api_key") or None)
            resp = cliente.messages.create(
                model="claude-haiku-5-5", max_tokens=400, output_config={"effort": "low"},
                messages=[{"role": "user", "content": pedido}])
            return next(b.text for b in resp.content if b.type == "text").strip()
        except Exception:
            log.exception("não consegui resumir a tarefa")
            limpo = re.sub(r"[*_`#|>-]", " ", texto)
            return " ".join(re.split(r"(?<=[.!?])\s+", " ".join(limpo.split()))[:2])
