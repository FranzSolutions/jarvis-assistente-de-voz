"""Painel do Jarvis: janela flutuante no canto direito.

Mostra uma esfera animada (aguardando / ouvindo / pensando / falando), a conversa,
e uma caixa para digitar. Clique na esfera para falar sem dizer "Jarvis";
clique de novo enquanto ele fala para interromper. O botão "–" recolhe o painel
numa bolinha; clicar nela abre de novo.
"""
import ctypes
import json
import math
import os
import queue
import threading
import time
import tkinter as tk

import amostras_voz
import jarvis

FUNDO = "#0a1020"
FUNDO2 = "#101a2e"
LINHA = "#1c2a45"
TEXTO = "#e8f0ff"
APAGADO = "#6b7fa3"
CORES = {
    "iniciando": "#4a5d80",
    "aguardando": "#2f86e0",
    "ouvindo": "#3fe0ff",
    "pensando": "#9d8cff",
    "falando": "#3fe0ff",
    "mudo": "#4a5568",
}
DICAS = {
    "iniciando": "Ligando…",
    "aguardando": "Diga “Jarvis” ou clique na esfera",
    "ouvindo": "Ouvindo…",
    "pensando": "Pensando…",
    "falando": "Falando… (clique para parar)",
    "mudo": "Microfone desligado — digite abaixo",
}
LARGURA, ALTURA = 360, 600
BOLINHA = 120


def misturar(c1, c2, k):
    """Cor entre c1 e c2 (k=0 → c1, k=1 → c2)."""
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * k):02x}" for x, y in zip(a, b))


class Painel:
    def __init__(self, fabrica_jarvis):
        self.j = None
        self.fila = queue.Queue()
        self.estado = "iniciando"
        self.energia = 0.0
        self.recolhido = False
        self.arrasto = None

        r = self.root = tk.Tk()
        r.title("Jarvis")
        r.overrideredirect(True)
        r.attributes("-topmost", True)
        r.attributes("-alpha", 0.985)
        r.configure(bg=FUNDO)
        self.sw, self.sh = r.winfo_screenwidth(), r.winfo_screenheight()
        self.pos = [self.sw - LARGURA - 18, max(20, self.sh - ALTURA - 70)]
        r.geometry(f"{LARGURA}x{ALTURA}+{self.pos[0]}+{self.pos[1]}")

        # topo: nome + recolher + fechar
        self.topo = tk.Frame(r, bg=FUNDO, height=34)
        self.topo.pack(fill="x")
        tk.Label(self.topo, text="J A R V I S", bg=FUNDO, fg=APAGADO, font=("Segoe UI Semibold", 9)).pack(side="left", padx=14, pady=8)
        self._botao(self.topo, "✕", self.fechar).pack(side="right", padx=(0, 10))
        self._botao(self.topo, "–", self.recolher).pack(side="right", padx=4)
        self._botao(self.topo, "⚙", self.alternar_ajustes, fonte=("Segoe UI Symbol", 11)).pack(side="right", padx=4)
        for w in (self.topo,) + tuple(self.topo.winfo_children()[:1]):
            w.bind("<ButtonPress-1>", self._pega)
            w.bind("<B1-Motion>", self._move)

        # esfera
        self.tela = tk.Canvas(r, width=LARGURA, height=210, bg=FUNDO, highlightthickness=0)
        self.tela.pack()
        self.tela.bind("<ButtonPress-1>", self._pega)
        self.tela.bind("<B1-Motion>", self._move)
        self.tela.bind("<ButtonRelease-1>", self._solta_esfera)
        self.dica = tk.Label(r, text=DICAS["iniciando"], bg=FUNDO, fg=APAGADO, font=("Segoe UI", 9))
        self.dica.pack(pady=(0, 8))

        # rodapé (montado antes da conversa para nunca ser espremido; preenchido mais abaixo)
        self.rodape = tk.Frame(r, bg=FUNDO)
        self.rodape.pack(side="bottom", fill="x", padx=12, pady=12)

        # conversa
        self.corpo = tk.Frame(r, bg=FUNDO2, highlightthickness=1, highlightbackground=LINHA)
        self.corpo.pack(fill="both", expand=True, padx=12)
        self.conversa = tk.Text(self.corpo, bg=FUNDO2, fg=TEXTO, relief="flat", wrap="word", padx=12, pady=10,
                                font=("Segoe UI", 10), cursor="arrow", spacing1=2, spacing3=6, height=10,
                                insertbackground=FUNDO2, selectbackground="#27406b")
        self.conversa.pack(fill="both", expand=True)
        self.conversa.tag_configure("voce", foreground="#8fb6ff")
        self.conversa.tag_configure("rotulo", foreground=APAGADO, font=("Cascadia Mono", 7))
        self.conversa.tag_configure("jarvis", foreground=TEXTO)
        self.conversa.tag_configure("acao", foreground="#55698f", font=("Segoe UI", 8))
        self.conversa.tag_configure("aprendi", foreground="#5fd4a0", font=("Segoe UI", 8))
        self.conversa.tag_configure("erro", foreground="#ff7a7a", font=("Segoe UI", 8))
        self.conversa.tag_configure("melhoria", foreground="#f2c14e", font=("Segoe UI", 8))
        self.conversa.tag_configure("consultoria", foreground="#b48cff", font=("Segoe UI", 8))
        self.conversa.configure(state="disabled")

        # ajustes (escolha de voz): ocupa o lugar da conversa quando aberto pelo ⚙
        self.ajustes = tk.Frame(r, bg=FUNDO2, highlightthickness=1, highlightbackground=LINHA)
        self.mostrando_ajustes = False
        self.linhas_voz = []
        tk.Label(self.ajustes, text="VOZ DO JARVIS", bg=FUNDO2, fg=APAGADO,
                 font=("Segoe UI Semibold", 8)).pack(anchor="w", padx=14, pady=(12, 6))
        for n, (nome, *_rest) in enumerate(amostras_voz.VOZES, 1):
            linha = tk.Frame(self.ajustes, bg=FUNDO2)
            linha.pack(fill="x", padx=8, pady=1)
            escolher = self._botao(linha, "", lambda n=n: self._escolher_voz(n), fonte=("Segoe UI", 10))
            escolher.pack(side="left", padx=6, pady=3)
            self._botao(linha, "▶ ouvir", lambda n=n: self._ouvir_voz(n), cor="#2f86e0",
                        fonte=("Segoe UI", 9)).pack(side="right", padx=6)
            self.linhas_voz.append((escolher, nome))
        tk.Label(self.ajustes, text="Clique no nome para usar a voz (fica salva).", bg=FUNDO2, fg="#3d4d6b",
                 font=("Segoe UI", 8)).pack(anchor="w", padx=14, pady=(10, 0))
        self._botao(self.ajustes, "← voltar para a conversa", self.alternar_ajustes,
                    fonte=("Segoe UI", 9)).pack(anchor="w", padx=14, pady=(6, 12))
        self._marcar_voz()

        # rodapé: caixa de texto + liga/desliga microfone e voz
        caixa =tk.Frame(self.rodape, bg=FUNDO2, highlightthickness=1, highlightbackground=LINHA, highlightcolor="#2f86e0")
        caixa.pack(fill="x")
        tk.Label(caixa, text="›", bg=FUNDO2, fg="#3fe0ff", font=("Cascadia Mono", 12)).pack(side="left", padx=(10, 0))
        self.entrada = tk.Entry(caixa, bg=FUNDO2, fg=TEXTO, relief="flat", insertbackground="#3fe0ff", font=("Segoe UI", 10))
        self.entrada.pack(side="left", fill="x", expand=True, padx=(6, 10), ipady=8)
        self.entrada.bind("<Return>", self._enviar)
        self._botao(caixa, "➤", self._enviar, cor="#2f86e0").pack(side="right", padx=8)
        chaves = tk.Frame(self.rodape, bg=FUNDO)
        chaves.pack(fill="x", pady=(8, 0))
        self.b_mic = self._botao(chaves, "", self._troca_mic, fonte=("Segoe UI Semibold", 8))
        self.b_mic.pack(side="left")
        self.b_voz = self._botao(chaves, "", self._troca_voz, fonte=("Segoe UI Semibold", 8))
        self.b_voz.pack(side="left", padx=12)
        tk.Label(chaves, text="Enter envia", bg=FUNDO, fg="#3d4d6b", font=("Segoe UI", 8)).pack(side="right")
        self._chaves()

        self._cantos_redondos()
        jarvis.ouvintes.append(lambda tipo, valor: self.fila.put((tipo, valor)))
        threading.Thread(target=self._ligar, args=(fabrica_jarvis,), daemon=True).start()
        self._ler_fila()
        self._animar()

    # ------------------------------------------------ montagem

    def _botao(self, pai, texto, acao, cor=APAGADO, fonte=("Segoe UI", 11)):
        b = tk.Label(pai, text=texto, bg=pai["bg"], fg=cor, font=fonte, cursor="hand2")
        b.bind("<Button-1>", lambda e: acao())
        b.bind("<Enter>", lambda e: b.configure(fg=TEXTO))
        b.bind("<Leave>", lambda e: b.configure(fg=b.cor_base))
        b.cor_base = cor
        return b

    def _chaves(self):
        mic = self.j.mic_ligado if self.j else True
        voz = self.j.voz_ligada if self.j else True
        for b, nome, ligado in ((self.b_mic, "MICROFONE", mic), (self.b_voz, "VOZ", voz)):
            b.cor_base = "#3fe0ff" if ligado else "#4a5568"
            b.configure(text=f"● {nome}" if ligado else f"○ {nome}", fg=b.cor_base)

    def _cantos_redondos(self):
        try:
            r = self.root
            r.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(r.winfo_id())
            v = ctypes.c_int(2)  # DWMWCP_ROUND
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(v), ctypes.sizeof(v))
        except Exception:
            pass

    def _ligar(self, fabrica):
        try:
            self.j = fabrica()
        except Exception as e:
            self.fila.put(("erro", f"não consegui ligar: {e}"))
            return
        self.fila.put(("pronto", None))
        self.j.ciclo()

    # ------------------------------------------------ eventos do Jarvis

    def _ler_fila(self):
        try:
            while True:
                tipo, valor = self.fila.get_nowait()
                if tipo == "estado":
                    self.estado = valor
                    self.dica.configure(text=DICAS.get(valor, ""))
                elif tipo == "pronto":
                    self._chaves()
                elif tipo == "fim":
                    self.root.after(1500, self.fechar)
                elif tipo == "voce":
                    self._escrever(f"› VOCÊ  {time.strftime('%H:%M')}\n", "rotulo")
                    self._escrever(valor + "\n", "voce")
                elif tipo == "jarvis":
                    self._escrever(f"› JARVIS  {time.strftime('%H:%M')}\n", "rotulo")
                    self._escrever(valor + "\n", "jarvis")
                elif tipo in ("acao", "aprendi", "erro"):
                    prefixo = {"acao": "· ", "aprendi": "+ aprendi: ", "erro": "! "}[tipo]
                    self._escrever(prefixo + str(valor) + "\n", tipo)
                elif tipo == "melhoria":  # a oficina aplicou algo sozinha; dá para voltar com um clique
                    self._escrever(f"⚡ melhorei: {valor['texto']}  ", "melhoria")
                    link = f"desfazer_{valor['id']}"
                    self.conversa.tag_configure(link, foreground="#2f86e0", underline=True, font=("Segoe UI", 8))
                    self.conversa.tag_bind(link, "<Button-1>", lambda e, i=valor["id"]: self._desfazer(i))
                    self.conversa.tag_bind(link, "<Enter>", lambda e: self.conversa.configure(cursor="hand2"))
                    self.conversa.tag_bind(link, "<Leave>", lambda e: self.conversa.configure(cursor="arrow"))
                    self._escrever("desfazer\n", link)
                elif tipo in ("consultoria", "tarefa"):  # relatório salvo na pasta de trabalho; abre com um clique
                    rotulo = "📋 consultoria" if tipo == "consultoria" else "🛠 Claude Code"
                    self._escrever(f"{rotulo}: {valor['texto']}  ", "consultoria")
                    link = f"abrir_{len(self.conversa.get('1.0', 'end'))}"
                    self.conversa.tag_configure(link, foreground="#2f86e0", underline=True, font=("Segoe UI", 8))
                    self.conversa.tag_bind(link, "<Button-1>", lambda e, a=valor["arquivo"]: os.startfile(a))
                    self.conversa.tag_bind(link, "<Enter>", lambda e: self.conversa.configure(cursor="hand2"))
                    self.conversa.tag_bind(link, "<Leave>", lambda e: self.conversa.configure(cursor="arrow"))
                    self._escrever("abrir\n", link)
        except queue.Empty:
            pass
        self.root.after(50, self._ler_fila)

    def _escrever(self, texto, tag):
        c = self.conversa
        c.configure(state="normal")
        c.insert("end", texto, tag)
        c.configure(state="disabled")
        c.see("end")

    # ------------------------------------------------ ações da pessoa

    def _enviar(self, _=None):
        texto = self.entrada.get().strip()
        if not texto or not self.j:
            return
        self.entrada.delete(0, "end")
        if self.estado == "falando":
            self.j.parar_fala.set()
        self.j.digitado.put(texto)

    def _desfazer(self, ident):
        if self.j:
            threading.Thread(target=self.j.oficina.desfazer, args=(ident,), daemon=True).start()

    def _troca_mic(self):
        if self.j:
            self.j.mic_ligado = not self.j.mic_ligado
            self._chaves()

    def _troca_voz(self):
        if self.j:
            self.j.voz_ligada = not self.j.voz_ligada
            if not self.j.voz_ligada:
                self.j.parar_fala.set()
            self._chaves()

    def alternar_ajustes(self):
        self.mostrando_ajustes = not self.mostrando_ajustes
        if self.mostrando_ajustes:
            self.corpo.pack_forget()
            self.tela.configure(height=120)  # esfera menor para caber a lista
            self.ajustes.pack(fill="both", expand=True, padx=12)
        else:
            self.ajustes.pack_forget()
            self.tela.configure(height=210)
            self.corpo.pack(fill="both", expand=True, padx=12)

    def _voz_atual(self):
        cfg = jarvis.CFG
        for n, (_, voz, vel, tom) in enumerate(amostras_voz.VOZES, 1):
            if (voz, vel, tom) == (cfg.get("voz"), cfg.get("velocidade_voz", "+8%"), cfg.get("tom_voz", "+0Hz")):
                return n
        return None

    def _marcar_voz(self):
        atual = self._voz_atual()
        for n, (b, nome) in enumerate(self.linhas_voz, 1):
            b.cor_base = "#3fe0ff" if n == atual else TEXTO
            b.configure(text=f"{'●' if n == atual else '○'}  {n}. {nome}", fg=b.cor_base)

    def _ouvir_voz(self, n):
        def tocar():
            try:
                amostras_voz.tocar(amostras_voz.garantir(n))
            except Exception as e:
                self.fila.put(("erro", f"não consegui tocar a voz {n}: {e}"))
        threading.Thread(target=tocar, daemon=True).start()

    def _escolher_voz(self, n):
        _, voz, vel, tom = amostras_voz.VOZES[n - 1]
        cfg = json.loads(jarvis.ARQ_CONFIG.read_text(encoding="utf-8"))
        cfg.update({"voz": voz, "velocidade_voz": vel, "tom_voz": tom})
        jarvis.ARQ_CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        jarvis.CFG.update({"voz": voz, "velocidade_voz": vel, "tom_voz": tom})
        self._marcar_voz()
        self._ouvir_voz(n)

    def _clique_esfera(self):
        if self.recolhido:
            self.expandir()
        elif self.j and self.estado == "falando":
            self.j.parar_fala.set()
        elif self.j and self.estado == "aguardando":
            self.j.ouvir_agora.set()

    def _pega(self, e):
        self.arrasto = (e.x_root, e.y_root, self.pos[0], self.pos[1], False)

    def _move(self, e):
        if not self.arrasto:
            return
        x0, y0, px, py, _ = self.arrasto
        dx, dy = e.x_root - x0, e.y_root - y0
        if abs(dx) + abs(dy) > 4:
            self.arrasto = (x0, y0, px, py, True)
            self.pos = [px + dx, py + dy]
            self.root.geometry(f"+{self.pos[0]}+{self.pos[1]}")

    def _solta_esfera(self, e):
        moveu = self.arrasto and self.arrasto[4]
        self.arrasto = None
        if not moveu:
            self._clique_esfera()

    def recolher(self):
        self.recolhido = True
        self.mostrando_ajustes = False
        for w in (self.topo, self.dica, self.corpo, self.ajustes, self.rodape):
            w.pack_forget()
        self.tela.configure(width=BOLINHA, height=BOLINHA)
        self.pos = [self.pos[0] + LARGURA - BOLINHA, self.pos[1] + ALTURA - BOLINHA]
        self.root.geometry(f"{BOLINHA}x{BOLINHA}+{self.pos[0]}+{self.pos[1]}")

    def expandir(self):
        self.recolhido = False
        self.tela.pack_forget()
        self.tela.configure(width=LARGURA, height=210)
        self.topo.pack(fill="x")
        self.tela.pack()
        self.dica.pack(pady=(0, 8))
        self.rodape.pack(side="bottom", fill="x", padx=12, pady=12)
        self.corpo.pack(fill="both", expand=True, padx=12)
        self.pos = [min(self.pos[0] - LARGURA + BOLINHA, self.sw - LARGURA), max(0, self.pos[1] - ALTURA + BOLINHA)]
        self.root.geometry(f"{LARGURA}x{ALTURA}+{self.pos[0]}+{self.pos[1]}")

    def fechar(self):
        if self.j:
            self.j.rodando = False
            self.j.parar_fala.set()
        self.root.destroy()
        os._exit(0)  # o microfone roda numa thread própria; sai de vez

    # ------------------------------------------------ animação

    def _animar(self):
        t = time.time()
        est = self.estado
        cor = CORES.get(est, CORES["aguardando"])
        onda = jarvis.AUDIO.get("onda")
        if est == "falando" and onda:
            alvo = min(1.0, 3.2 * math.sqrt(sum(v * v for v in onda) / len(onda)))
        elif est == "falando":
            alvo = 0.35 + 0.45 * abs(math.sin(t * 8.5) * math.sin(t * 3.1 + 1))
        elif est == "ouvindo":
            alvo = min(1.0, jarvis.AUDIO["nivel"] / 1500)
        elif est == "aguardando":
            alvo = min(0.5, jarvis.AUDIO["nivel"] / 3000) + 0.08 * (1 + math.sin(t * 1.6))
        elif est == "pensando":
            alvo = 0.25 + 0.1 * math.sin(t * 4)
        else:
            alvo = 0.05
        self.energia += (alvo - self.energia) * 0.3
        self._desenhar(t, cor, est, onda if est == "falando" else None)
        self.root.after(33, self._animar)

    def _pontos_onda(self, t, w, cy, s, est, onda):
        """Pontos da onda que atravessa a esfera: a fala real quando tem, senão uma onda viva pelo volume."""
        n, borda = 72, 14
        largura = w - 2 * borda
        pts = []
        for k in range(n):
            x = borda + largura * k / (n - 1)
            funil = math.sin(math.pi * k / (n - 1)) ** 1.5  # some nas pontas
            if onda:
                v = onda[int(k * (len(onda) - 1) / (n - 1))] * 2.4
            else:
                amp = {"ouvindo": 0.15 + self.energia, "pensando": 0.18, "aguardando": 0.06 + self.energia * 0.4}.get(est, 0.03)
                fase = k / n * math.tau
                v = amp * (0.55 * math.sin(fase * 3 + t * 6) + 0.3 * math.sin(fase * 7 - t * 9) + 0.15 * math.sin(fase * 13 + t * 4))
            pts += [x, cy + max(-1.0, min(1.0, v)) * 62 * s * funil]
        return pts

    def _desenhar(self, t, cor, est, onda=None):
        c = self.tela
        c.delete("all")
        if self.recolhido:
            w, h, s = BOLINHA, BOLINHA, 0.42
        elif self.mostrando_ajustes:
            w, h, s = LARGURA, 120, 0.5
        else:
            w, h, s = LARGURA, 210, 1.0
        cx, cy, e = w / 2, h / 2, self.energia
        raio = 50 * s
        mono = ("Cascadia Mono", 7)

        if not self.recolhido:
            # grade de pontos ao fundo
            for gx in range(12, w, 18):
                for gy in range(10, h, 18):
                    c.create_rectangle(gx, gy, gx + 1, gy + 1, fill="#16223a", outline="")
            # cantos de mira
            for (x, y, dx, dy) in ((6, 6, 1, 1), (w - 6, 6, -1, 1), (6, h - 6, 1, -1), (w - 6, h - 6, -1, -1)):
                c.create_line(x, y, x + 14 * dx, y, fill=misturar(cor, FUNDO, 0.45))
                c.create_line(x, y, x, y + 14 * dy, fill=misturar(cor, FUNDO, 0.45))
            if not self.mostrando_ajustes:
                rotulo = {"aguardando": "STANDBY", "ouvindo": "LISTEN", "pensando": "PROCESS", "falando": "VOICE OUT",
                          "mudo": "MIC OFF", "iniciando": "BOOT"}.get(est, est.upper())
                c.create_text(16, 18, text="SYS ● ONLINE", anchor="w", fill=misturar(cor, FUNDO, 0.35), font=mono)
                c.create_text(w - 16, 18, text=time.strftime("%H:%M:%S"), anchor="e", fill=misturar(cor, FUNDO, 0.35), font=mono)
                c.create_text(16, h - 16, text=f"MODE · {rotulo}", anchor="w", fill=misturar(cor, FUNDO, 0.2), font=mono)
                c.create_text(w - 16, h - 16, text=f"LVL {int(e * 100):02d}%", anchor="e", fill=misturar(cor, FUNDO, 0.35), font=mono)

        # brilho em volta (camadas que somem no fundo)
        for i in range(7, 0, -1):
            rr = raio * (1 + 0.1 * i) + e * 16 * s
            c.create_oval(cx - rr, cy - rr, cx + rr, cy + rr, fill=misturar(cor, FUNDO, 0.62 + i * 0.05), outline="")

        # onda sonora atravessando a esfera (por cima do brilho, por baixo do núcleo): três traços para dar brilho
        if not self.recolhido:
            pts = self._pontos_onda(t, w, cy, s, est, onda)
            for largura, k in ((7, 0.78), (3.5, 0.45), (1.4, 0.0)):
                c.create_line(*pts, fill=misturar(cor, FUNDO, k), width=largura * max(s, 0.6), smooth=True, capstyle="round")

        # arcos girando
        rr = raio * 1.62
        giro = (t * (240 if est == "pensando" else 35)) % 360
        for k in range(3):
            c.create_arc(cx - rr, cy - rr, cx + rr, cy + rr, start=giro + k * 120, extent=62 + 20 * e,
                         style="arc", outline=misturar(cor, FUNDO, 0.15), width=max(1, 2.2 * s))
        rr2 = raio * 1.9
        for k in range(2):
            c.create_arc(cx - rr2, cy - rr2, cx + rr2, cy + rr2, start=-giro * 0.6 + k * 180, extent=28,
                         style="arc", outline=misturar(cor, FUNDO, 0.5), width=max(1, 1.2 * s))

        # marcas na borda que acendem com a energia
        if not self.recolhido and not self.mostrando_ajustes:
            for k in range(48):
                a = math.radians(k * 7.5 + t * 6)
                acesa = (k / 48) < e * 1.4
                r1, r2 = raio * 2.08, raio * (2.18 if k % 4 else 2.3)
                c.create_line(cx + r1 * math.cos(a), cy + r1 * math.sin(a), cx + r2 * math.cos(a), cy + r2 * math.sin(a),
                              fill=misturar(cor, FUNDO, 0.25 if acesa else 0.78), width=1)

        # núcleo
        c.create_oval(cx - raio, cy - raio, cx + raio, cy + raio, fill=misturar(cor, FUNDO, 0.55),
                      outline=cor, width=max(1, 2 * s))
        ri = raio * (0.38 + 0.42 * e)
        c.create_oval(cx - ri, cy - ri, cx + ri, cy + ri, fill=misturar(cor, "#ffffff", 0.35), outline="")
        rc = ri * 0.45
        c.create_oval(cx - rc, cy - rc, cx + rc, cy + rc, fill="#ffffff", outline="")


def abrir(fabrica_jarvis):
    Painel(fabrica_jarvis).root.mainloop()
