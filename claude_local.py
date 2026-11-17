"""O cérebro do Jarvis pela assinatura do Claude (arquivo protegido).

Em vez da chave da API (que gasta crédito), o Jarvis conversa pelo Claude Code instalado na pasta
claude-code\\ e logado na conta do claude.ai da pessoa (login guardado em claude-assinatura\\).
As ferramentas do Jarvis entram como um servidor MCP dentro do próprio processo; das ferramentas do
Claude Code só ficam a busca e a leitura de páginas da internet.
"""
import asyncio
import os
import threading
from pathlib import Path

import claude_agent_sdk as sdk

PASTA = Path(__file__).resolve().parent
# o SDK só aceita o programa nativo (claude.exe); usa o que vem junto com ele, ou o da instalação em claude-code\
CLI = next((p for p in (Path(sdk.__file__).parent / "_bundled" / "claude.exe",
                        PASTA / "claude-code" / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe")
            if p.exists()), PASTA / "claude-code" / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe")
LOGIN = PASTA / "claude-assinatura"
WEB = ["WebSearch", "WebFetch"]

# a assinatura não pode misturar com a chave da API: se ANTHROPIC_API_KEY existir, o Claude Code cobra da API
for _v in [k for k in os.environ if k.startswith("ANTHROPIC_")]:
    os.environ.pop(_v, None)


def ambiente():
    return {"CLAUDE_CONFIG_DIR": str(LOGIN), "DISABLE_AUTOUPDATER": "1", "CLAUDE_CODE_DISABLE_TERMINAL_TITLE": "1"}


def pronto():
    """None se dá para usar; senão o motivo."""
    if not CLI.exists():
        return f"Claude Code não instalado em {CLI.parent}"
    if not any(LOGIN.glob("*.json")) and not (LOGIN / ".credentials.json").exists():
        return "falta entrar com a conta do Claude (claude auth login)"
    return None


# ---------------------------------------------------------------- laço assíncrono próprio

_laco = asyncio.new_event_loop()
threading.Thread(target=_laco.run_forever, daemon=True, name="claude-assinatura").start()


def rodar(coro, timeout=None):
    """Roda uma corrotina no laço do cérebro e espera o resultado (chamado de qualquer thread)."""
    return asyncio.run_coroutine_threadsafe(coro, _laco).result(timeout)


def opcoes(sistema, modelo=None, esforco=None, servidores=None, permitidas=(), web=False, max_turns=None,
           esquema=None, ao_usar=None):
    """ao_usar(nome_da_ferramenta) é chamado antes de cada ferramenta (ex.: marcar que entrou conteúdo de site)."""
    ferramentas = list(WEB) if web else []
    hooks = None
    if ao_usar:
        async def gancho(entrada, _id, _contexto):
            ao_usar(entrada.get("tool_name", ""))
            return {}
        hooks = {"PreToolUse": [sdk.HookMatcher(matcher=None, hooks=[gancho])]}
    return sdk.ClaudeAgentOptions(
        cli_path=str(CLI),
        env=ambiente(),
        system_prompt=sistema,
        tools=ferramentas,
        mcp_servers=servidores or {},
        allowed_tools=list(permitidas) + ferramentas,
        permission_mode="dontAsk",  # o que não está liberado é negado, sem ficar esperando "permitir"
        setting_sources=[],          # não carrega configurações nem plugins do PC
        model=modelo,
        effort=esforco,
        max_turns=max_turns,
        output_format={"type": "json_schema", "schema": esquema} if esquema else None,
        hooks=hooks,
        cwd=str(PASTA),
    )


async def _uma_vez(prompt, opc):
    texto, resultado = [], None
    async for msg in sdk.query(prompt=prompt, options=opc):
        if isinstance(msg, sdk.AssistantMessage):
            texto += [b.text for b in msg.content if isinstance(b, sdk.TextBlock)]
        elif isinstance(msg, sdk.ResultMessage):
            resultado = msg
    return texto, resultado


def perguntar_uma_vez(prompt, sistema="", modelo=None, esforco=None, esquema=None, web=False, servidores=None,
                      permitidas=(), max_turns=None, timeout=900):
    """Uma pergunta avulsa (memória, oficina, consultoria, resumo). Devolve (texto_final, json_estruturado, resultado)."""
    opc = opcoes(sistema, modelo, esforco, servidores, permitidas, web, max_turns, esquema)
    texto, r = rodar(_uma_vez(prompt, opc), timeout)
    if r is None:
        raise RuntimeError("o Claude não respondeu")
    if r.is_error:
        raise RuntimeError(f"o Claude devolveu erro: {r.result or r.subtype or r.errors}")
    final = (r.result or "").strip() or (texto[-1].strip() if texto else "")
    return final, r.structured_output, r


class Sessao:
    """Conversa contínua do Jarvis: o Claude Code fica aberto entre um pedido e outro (responde mais rápido).
    `montar()` devolve as opções (prompt, ferramentas); a conversa recomeça quando `nova=True`."""

    def __init__(self, montar):
        self.montar = montar
        self.cliente = None

    async def _fechar(self):
        if self.cliente:
            try:
                await self.cliente.disconnect()
            except Exception:
                pass
            self.cliente = None

    async def _perguntar(self, texto, nova):
        if nova or self.cliente is None:
            await self._fechar()
            self.cliente = sdk.ClaudeSDKClient(self.montar())
            await self.cliente.connect()
        await self.cliente.query(texto)
        partes, resultado = [], None
        async for msg in self.cliente.receive_response():
            if isinstance(msg, sdk.AssistantMessage):
                partes += [b.text for b in msg.content if isinstance(b, sdk.TextBlock)]
            elif isinstance(msg, sdk.ResultMessage):
                resultado = msg
        return partes, resultado

    def perguntar(self, texto, nova=False, timeout=600):
        try:
            return rodar(self._perguntar(texto, nova), timeout)
        except Exception:
            rodar(self._fechar(), 30)  # na próxima, conecta de novo do zero
            raise

    def fechar(self):
        rodar(self._fechar(), 30)


def ferramenta_mcp(definicao, executar):
    """Transforma uma ferramenta do Jarvis (dict no formato da API + função) numa ferramenta MCP do SDK."""
    @sdk.tool(definicao["name"], definicao.get("description", ""), definicao.get("input_schema") or {"type": "object", "properties": {}})
    async def chamada(args):
        try:
            saida = await asyncio.to_thread(executar, **(args or {}))
        except Exception as e:  # o erro volta para o Claude explicar ou tentar outro jeito
            return {"content": [{"type": "text", "text": f"Erro: {e}"}], "is_error": True}
        if isinstance(saida, list):  # imagem (print da tela)
            return {"content": [{"type": "image", "data": b["source"]["data"], "mimeType": b["source"]["media_type"]}
                                for b in saida if b.get("type") == "image"]}
        return {"content": [{"type": "text", "text": str(saida)}]}
    return chamada


def servidor(nome, ferramentas):
    """ferramentas: lista de (definicao, funcao). Devolve ({nome: servidor}, [nomes liberados])."""
    mcp = sdk.create_sdk_mcp_server(nome, tools=[ferramenta_mcp(d, f) for d, f in ferramentas])
    return {nome: mcp}, [f"mcp__{nome}__{d['name']}" for d, _ in ferramentas]
