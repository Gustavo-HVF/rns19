"""Painel interativo do EXPRO para Jupyter / Google Colab (ipywidgets), com dados fictícios."""

from __future__ import annotations

import base64
import html
import io
import math
import threading
import time
from typing import Callable, Optional

import ipywidgets as w
from IPython.display import HTML, display

from .nucleo import ROTULO_PERFIL, Alerta, Estado, Resultado, SistemaExpro, Situacao, Usuario, criar_alertas
from .simulacao import montar_sistema_simulado
from .sons import gerar_wav

COR_NIVEL = {3: "#1565c0", 2: "#e07b00", 1: "#c62828"}
COR_ESTADO = {
    Estado.PREPARACAO: "#455a64", Estado.TESTE_AUDIO: "#6a1b9a", Estado.POSICIONAMENTO: "#1565c0",
    Estado.CONTAGEM: "#e07b00", Estado.DETONACAO_LIBERADA: "#2e7d32",
    Estado.AGUARDANDO_REENTRADA: "#6d4c41", Estado.EMERGENCIA: "#c62828",
}
COR_EVENTO = {"info": "#455a64", "aviso": "#a15c00", "bloqueio": "#c62828",
              "emergencia": "#c62828", "sucesso": "#2e7d32"}
VERMELHO, VERDE, CINZA = "#c62828", "#2e7d32", "#9e9e9e"


class AudioNavegador:
    """Toca os alertas no navegador: sirene do nível em loop, intercalada com voz (gTTS) se disponível."""

    def __init__(self, saida: w.Output, usar_voz: bool = False):
        self.saida = saida
        self._sirene = {n: base64.b64encode(gerar_wav(n)).decode() for n in (1, 2, 3)}
        self._voz: dict[int, str] = self._gerar_vozes() if usar_voz else {}
        self._contador = 0

    @staticmethod
    def _gerar_vozes() -> dict[int, str]:
        try:
            from gtts import gTTS
            vozes = {}
            for alerta in criar_alertas().values():
                buffer = io.BytesIO()
                gTTS(alerta.mensagem, lang="pt", tld="com.br").write_to_fp(buffer)
                vozes[alerta.nivel] = base64.b64encode(buffer.getvalue()).decode()
            return vozes
        except Exception:  # sem internet ou sem gTTS: fica só a sirene
            return {}

    def tocar(self, alerta: Alerta) -> None:
        self._contador += 1
        sirene = f"data:audio/wav;base64,{self._sirene[alerta.nivel]}"
        voz = self._voz.get(alerta.nivel)
        if voz:
            v, s = f"expro-voz-{self._contador}", f"expro-sirene-{self._contador}"
            codigo = (f'<audio id="{v}" autoplay src="data:audio/mpeg;base64,{voz}" '
                      f'onended="document.getElementById(\'{s}\').play()"></audio>'
                      f'<audio id="{s}" src="{sirene}" '
                      f'onended="document.getElementById(\'{v}\').play()"></audio>')
        else:
            codigo = f'<audio autoplay loop src="{sirene}"></audio>'
        self.saida.outputs = ()
        self.saida.append_display_data(HTML(codigo))

    def parar(self) -> None:
        self.saida.outputs = ()


# ---------------------------------------------------------------------------
# Desenho (HTML/SVG)
# ---------------------------------------------------------------------------


def _estrela(cx: float, cy: float, externo: float, interno: float, pontas: int = 8) -> str:
    pontos = []
    for i in range(pontas * 2):
        r = externo if i % 2 == 0 else interno
        a = math.pi * i / pontas - math.pi / 2
        pontos.append(f"{cx + r * math.cos(a):.1f},{cy + r * math.sin(a):.1f}")
    return " ".join(pontos)


def svg_mapa(sistema: SistemaExpro, tamanho: int = 430) -> str:
    v = sistema.varredura
    cx, cy = sistema.config.explosivo_xy
    raio = v.raio_m
    alcance = raio * 1.3
    for p in v.pessoas:
        if p.x is not None:
            alcance = max(alcance, abs(p.x - cx) + 30, abs(p.y - cy) + 30)
    meio = tamanho / 2
    esc = (meio - 12) / alcance

    def px(x: float, y: float) -> tuple[float, float]:
        return meio + (x - cx) * esc, meio - (y - cy) * esc

    cor = VERMELHO if sistema.bloqueantes() else VERDE
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {tamanho} {tamanho + 34}" '
         f'width="{tamanho}" height="{tamanho + 34}" style="background:#f3efe6;border-radius:12px;'
         f'font-family:Inter,Arial,sans-serif">']
    passo = 100 if alcance <= 700 else 250
    for r in range(passo, int(alcance) + 1, passo):
        s.append(f'<circle cx="{meio}" cy="{meio}" r="{r * esc:.1f}" fill="none" stroke="#d5ccb9" '
                 'stroke-dasharray="3 5"/>')
        s.append(f'<text x="{meio + 4}" y="{meio - r * esc + 12:.1f}" font-size="10" fill="#9a8f78">{r} m</text>')
    s.append(f'<circle cx="{meio}" cy="{meio}" r="{raio * esc:.1f}" fill="{cor}" fill-opacity="0.13" '
             f'stroke="{cor}" stroke-width="2.5"/>')
    s.append(f'<text x="{meio}" y="{meio + raio * esc - 8:.1f}" font-size="12" font-weight="700" '
             f'text-anchor="middle" fill="{cor}">raio de risco {raio:g} m</text>')
    s.append(f'<polygon points="{_estrela(meio, meio, 13, 6)}" fill="#ff8f00" stroke="#4e342e" stroke-width="1.5"/>')
    for p in v.pessoas:
        if p.x is None:
            continue
        x, y = px(p.x, p.y)
        preenchimento = {Situacao.DENTRO: VERMELHO, Situacao.FORA: VERDE}.get(p.situacao, CINZA)
        traco = ' stroke-dasharray="3 2"' if p.situacao is Situacao.SEM_SINAL else ""
        s.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="8" fill="{preenchimento}" stroke="#fff" '
                 f'stroke-width="2"{traco}/>')
        s.append(f'<text x="{x:.1f}" y="{y - 12:.1f}" font-size="11" font-weight="700" text-anchor="middle" '
                 f'fill="#263238">{html.escape(p.id)}</text>')
    legenda = [(VERMELHO, "no raio"), (VERDE, "fora do raio"), (CINZA, "sem sinal"), ("#ff8f00", "explosivo")]
    for i, (c, texto) in enumerate(legenda):
        lx = 14 + i * (tamanho - 20) / 4
        s.append(f'<circle cx="{lx + 6}" cy="{tamanho + 17}" r="6" fill="{c}"/>'
                 f'<text x="{lx + 16}" y="{tamanho + 21}" font-size="11" fill="#37474f">{texto}</text>')
    s.append("</svg>")
    return "".join(s)


def _caixa(conteudo: str, fundo: str, cor: str = "#fff") -> str:
    return (f'<div style="background:{fundo};color:{cor};padding:10px 12px;border-radius:10px;'
            f'margin-bottom:8px">{conteudo}</div>')


def html_status(sistema: SistemaExpro, usuario: Optional[Usuario]) -> str:
    st = sistema.status()
    partes = [_caixa(f'<div style="font-size:11px;opacity:.85">ESTADO</div>'
                     f'<div style="font-size:19px;font-weight:800">{st.estado.value}</div>',
                     COR_ESTADO[st.estado])]

    cor_pessoas = VERMELHO if st.pessoas_no_raio else VERDE
    sem_sinal = (f'<div style="color:{VERMELHO};font-weight:700">+ {st.sem_sinal} capacete(s) sem sinal</div>'
                 if st.sem_sinal else "")
    partes.append(_caixa(
        f'<div style="font-size:11px;color:#546e7a">PESSOAS NO RAIO ({st.terreno.replace("_", " ")}, '
        f'{st.raio_m:g} m)</div><div style="font-size:40px;font-weight:800;color:{cor_pessoas};'
        f'line-height:1.1">{st.pessoas_no_raio}</div>{sem_sinal}'
        f'<div style="font-size:11px;color:#78909c">{st.monitorados} capacete(s) monitorado(s)</div>',
        "#eceff1", "#263238"))

    if st.detonacao_liberada:
        trava = f"🔓 DETONAÇÃO LIBERADA · {math.ceil(st.janela_restante_s or 0)} s"
        partes.append(_caixa(f'<b style="font-size:16px">{trava}</b>', VERDE))
    else:
        partes.append(_caixa('<b style="font-size:16px">🔒 DETONAÇÃO BLOQUEADA</b>', "#263238"))

    if st.contagem_restante_s is not None:
        partes.append(_caixa(f'<div style="font-size:11px">CONTAGEM REGRESSIVA</div>'
                             f'<div style="font-size:34px;font-weight:800">{math.ceil(st.contagem_restante_s)} s</div>',
                             COR_NIVEL[2]))

    if st.alerta is not None:
        quanto = "contínuo" if st.alerta_restante_s is None else f"{math.ceil(st.alerta_restante_s)} s"
        partes.append(_caixa(f'<b>🔊 NÍVEL {st.alerta.nivel} — {st.alerta.titulo}</b> · {quanto}'
                             f'<div style="font-style:italic;margin-top:4px">"{html.escape(st.alerta.mensagem)}"</div>',
                             COR_NIVEL[st.alerta.nivel]))
    else:
        espera = (f" · próximo aviso em {math.ceil(st.intervalo_restante_s)} s"
                  if st.intervalo_restante_s > 0 else "")
        partes.append(_caixa(f"🔈 Sem alerta sonoro{espera}", "#eceff1", "#455a64"))

    quem = (f"{html.escape(usuario.nome)} ({ROTULO_PERFIL[usuario.perfil]})" if usuario else "ninguém")
    partes.append(f'<div style="font-size:12px;color:#546e7a">Usuário conectado: <b>{quem}</b></div>')
    return f'<div style="font-family:Inter,Arial,sans-serif;width:340px">{"".join(partes)}</div>'


def html_registro(sistema: SistemaExpro, linhas: int = 12) -> str:
    itens = []
    for e in reversed(sistema.eventos[-linhas:]):
        itens.append(f'<div style="border-left:4px solid {COR_EVENTO.get(e.tipo, "#455a64")};padding:2px 8px;'
                     f'margin:3px 0;background:#fafafa"><span style="color:#90a4ae">{e.instante:6.1f} s</span> '
                     f'{html.escape(e.texto)}</div>')
    return (f'<div style="font-family:Inter,Arial,sans-serif;font-size:12.5px;color:#263238">'
            f'<b>Registro de eventos</b>{"".join(itens)}</div>')


# ---------------------------------------------------------------------------
# Painel
# ---------------------------------------------------------------------------


class PainelExpro:
    _ativo: Optional[PainelExpro] = None

    def __init__(self, config: dict):
        if PainelExpro._ativo is not None:  # rodar a célula de novo substitui o painel anterior
            PainelExpro._ativo.desligar()
        PainelExpro._ativo = self

        sim = config.get("simulacao", {})
        self.acelerar = max(1.0, float(sim.get("acelerar_tempo", 1)))
        t0 = time.monotonic()
        self.saida_audio = w.Output()
        self.audio = AudioNavegador(self.saida_audio, bool(sim.get("usar_voz", False)))
        self.sistema, self.loc = montar_sistema_simulado(
            config, lambda: (time.monotonic() - t0) * self.acelerar, self.audio)
        self.usuario: Optional[Usuario] = None
        self._lock = threading.RLock()
        self._parar = threading.Event()
        self._montar_widgets()
        self._executar(None)

    # ------------------------------------------------------------ widgets
    def _botao(self, texto: str, estilo: str, acao: Callable[[], Optional[Resultado]],
               icone: str = "") -> w.Button:
        b = w.Button(description=texto, button_style=estilo, icon=icone, layout=w.Layout(width="auto"))
        b.on_click(lambda _: self._executar(acao))
        return b

    def _montar_widgets(self) -> None:
        s = self.sistema
        self.mapa = w.HTML()
        self.status = w.HTML()
        self.registro = w.HTML()
        self.mensagem = w.HTML()

        self.sel_usuario = w.Dropdown(
            options=[(f"{u.nome} — {ROTULO_PERFIL[u.perfil]}", u.login) for u in s.usuarios.values()],
            layout=w.Layout(width="320px"))
        self.pin = w.Password(placeholder="PIN", layout=w.Layout(width="90px"))
        self.sel_terreno = w.Dropdown(options=list(s.config.raios_terreno_m), value=s.config.terreno,
                                      layout=w.Layout(width="150px"))
        self.sel_pessoa = w.Dropdown(options=[(f"{t.id} ({t.nome})", t.id) for t in self.loc.trabalhadores.values()],
                                     layout=w.Layout(width="190px"))
        self.evacuacao_auto = w.Checkbox(value=True, indent=False,
                                         description="pessoas evacuam sozinhas ao ouvir o Nível 3")
        self.relogio = w.Play(interval=500, min=0, max=10 ** 9, step=1, layout=w.Layout(width="auto"))
        self.relogio.observe(lambda _: self._executar(None), names="value")

        titulo = lambda t: w.HTML(f'<b style="font-family:Inter,Arial,sans-serif;color:#37474f">{t}</b>')
        acesso = w.HBox([self.sel_usuario, self.pin, self._botao("Entrar", "", self._entrar, "sign-in"),
                         self._botao("Sair", "", self._sair, "sign-out")], layout=w.Layout(flex_flow="row wrap"))
        operacao = w.HBox([
            self._botao("Nível 3 · verificar área", "info", self._nivel3, "bullhorn"),
            self._botao("Nível 2 · autorizar detonação", "warning", lambda: s.autorizar_detonacao(self.usuario), "key"),
            self._botao("Registrar detonação", "", lambda: s.registrar_detonacao(self.usuario), "bolt"),
            self._botao("Validar reentrada", "success", lambda: s.validar_reentrada(self.usuario), "check"),
        ], layout=w.Layout(flex_flow="row wrap"))
        seguranca = w.HBox([
            self._botao("EMERGÊNCIA · Nível 1", "danger", lambda: s.acionar_emergencia("botão do painel"),
                        "exclamation-triangle"),
            self._botao("Encerrar emergência", "", lambda: s.encerrar_emergencia(self.usuario), "stop"),
            self._botao("Testar áudio 3·2·1", "", lambda: s.testar_audio(self.usuario), "volume-up"),
            self.sel_terreno,
            self._botao("Aplicar terreno", "", lambda: s.selecionar_terreno(self.usuario, self.sel_terreno.value)),
        ], layout=w.Layout(flex_flow="row wrap"))
        simulacao = w.HBox([
            self.sel_pessoa,
            self._botao("Entrar no raio", "", lambda: self._mover(True), "arrow-right"),
            self._botao("Sair do raio", "", lambda: self._mover(False), "arrow-left"),
            self._botao("Liga/desliga sinal", "", self._alternar_sinal, "signal"),
            self._botao("Evacuar todos", "", self._evacuar, "users"),
        ], layout=w.Layout(flex_flow="row wrap"))

        self.interface = w.VBox([
            w.HTML('<div style="font-family:Inter,Arial,sans-serif;background:#263238;color:#ffc107;'
                   'padding:10px 14px;border-radius:10px;font-weight:800;font-size:18px">PROJETO EXPRO '
                   '<span style="color:#fff;font-weight:500;font-size:13px">· EXplosion PROtection · '
                   'ER Dynamics Group · demonstração com dados fictícios</span></div>'),
            w.HBox([self.mapa, self.status], layout=w.Layout(flex_flow="row wrap", grid_gap="14px")),
            self.mensagem,
            titulo("Acesso"), acesso,
            titulo("Operação"), operacao, seguranca,
            titulo("Simulação dos capacetes (dados fictícios)"), simulacao, self.evacuacao_auto,
            w.HBox([titulo("Relógio:"), self.relogio,
                    w.HTML('<span style="font-size:12px;color:#78909c">atualiza sozinho; se o painel '
                           'parecer parado, clique ▶</span>')]),
            self.registro,
            self.saida_audio,
        ])

    # ------------------------------------------------------------ ações
    def _entrar(self) -> Resultado:
        usuario = self.sistema.autenticar(self.sel_usuario.value, self.pin.value)
        self.pin.value = ""
        if usuario is None:
            return Resultado(False, "PIN incorreto.")
        self.usuario = usuario
        return Resultado(True, f"Bem-vindo(a), {usuario.nome}.")

    def _sair(self) -> Resultado:
        self.usuario = None
        return Resultado(True, "Sessão encerrada.")

    def _nivel3(self) -> Resultado:
        resultado = self.sistema.acionar_nivel3(self.usuario)
        if resultado.ok and self.evacuacao_auto.value:
            self.loc.evacuar(self.sistema.config.explosivo_xy, self.sistema.raio_m)
        return resultado

    def _mover(self, entrar: bool) -> Resultado:
        id_ = self.sel_pessoa.value
        centro, raio = self.sistema.config.explosivo_xy, self.sistema.raio_m
        if entrar:
            self.loc.entrar_no_raio(id_, centro, raio)
        else:
            self.loc.sair_do_raio(id_, centro, raio)
        return Resultado(True, f"{id_} caminhando para {'dentro' if entrar else 'fora'} do raio.")

    def _alternar_sinal(self) -> Resultado:
        t = self.loc.trabalhadores[self.sel_pessoa.value]
        self.loc.definir_sinal(t.id, not t.sinal)
        return Resultado(True, f"Localizador de {t.id} {'ligado' if t.sinal else 'desligado (simula bateria/sinal perdido)'}.")

    def _evacuar(self) -> Resultado:
        self.loc.evacuar(self.sistema.config.explosivo_xy, self.sistema.raio_m)
        return Resultado(True, "Todos caminhando para fora do raio.")

    # ------------------------------------------------------------ ciclo
    def _executar(self, acao: Optional[Callable[[], Optional[Resultado]]]) -> None:
        with self._lock:
            if acao is not None:
                try:
                    resultado = acao()
                except Exception as erro:
                    resultado = Resultado(False, f"Erro: {erro}")
                if resultado is not None:
                    cor = VERDE if resultado.ok else VERMELHO
                    self.mensagem.value = (f'<div style="font-family:Inter,Arial,sans-serif;padding:8px 12px;'
                                           f'border-radius:8px;background:{cor};color:#fff;font-weight:600">'
                                           f'{html.escape(resultado.mensagem)}</div>')
            self.sistema.atualizar()
            self.mapa.value = svg_mapa(self.sistema)
            self.status.value = html_status(self.sistema, self.usuario)
            self.registro.value = html_registro(self.sistema)

    def _laco(self) -> None:
        while not self._parar.wait(0.5):
            try:
                self._executar(None)
            except Exception:
                pass

    def mostrar(self) -> None:
        display(self.interface)
        threading.Thread(target=self._laco, daemon=True).start()

    def desligar(self) -> None:
        self._parar.set()
        self.audio.parar()
