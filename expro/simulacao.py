"""Dados fictícios: capacetes, alto-falantes e trava simulados + roteiro de demonstração."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Callable, Iterable, Optional

from .nucleo import Alerta, Configuracao, Estado, Leitura, SistemaExpro, Usuario, usuarios_de_config


@dataclass
class TrabalhadorSimulado:
    id: str
    nome: str
    x: float
    y: float
    sinal: bool = True
    destino: Optional[tuple[float, float]] = None


class LocalizadorSimulado:
    """Faz o papel dos localizadores nos capacetes, com posições fictícias editáveis."""

    def __init__(self, trabalhadores: Iterable[dict], velocidade_m_s: float = 8.0):
        self.trabalhadores = {
            t["id"]: TrabalhadorSimulado(t["id"], t.get("nome", t["id"]), float(t["x"]), float(t["y"]))
            for t in trabalhadores
        }
        self.velocidade_m_s = velocidade_m_s
        self._ultimo: Optional[float] = None

    def ler(self, agora: float) -> list[Leitura]:
        dt = 0.0 if self._ultimo is None else max(0.0, agora - self._ultimo)
        self._ultimo = agora
        leituras = []
        for t in self.trabalhadores.values():
            self._andar(t, dt)
            if t.sinal:
                leituras.append(Leitura(t.id, t.x, t.y, agora, t.nome))
        return leituras

    def _andar(self, t: TrabalhadorSimulado, dt: float) -> None:
        if t.destino is None or dt <= 0:
            return
        dx, dy = t.destino[0] - t.x, t.destino[1] - t.y
        distancia = math.hypot(dx, dy)
        passo = self.velocidade_m_s * dt
        if distancia <= passo:
            t.x, t.y = t.destino
            t.destino = None
        else:
            t.x += dx / distancia * passo
            t.y += dy / distancia * passo

    # Comandos usados pela demonstração para movimentar as pessoas
    def caminhar_para(self, id_: str, x: float, y: float) -> None:
        self.trabalhadores[id_].destino = (x, y)

    def _ponto_na_direcao(self, t: TrabalhadorSimulado, centro: tuple[float, float], distancia: float):
        angulo = math.atan2(t.y - centro[1], t.x - centro[0]) if (t.x, t.y) != centro else 0.0
        return centro[0] + distancia * math.cos(angulo), centro[1] + distancia * math.sin(angulo)

    def sair_do_raio(self, id_: str, centro: tuple[float, float], raio: float, folga: float = 40.0) -> None:
        t = self.trabalhadores[id_]
        if math.hypot(t.x - centro[0], t.y - centro[1]) < raio + folga:
            t.destino = self._ponto_na_direcao(t, centro, raio + folga)

    def entrar_no_raio(self, id_: str, centro: tuple[float, float], raio: float) -> None:
        t = self.trabalhadores[id_]
        t.destino = self._ponto_na_direcao(t, centro, raio * 0.6)

    def evacuar(self, centro: tuple[float, float], raio: float, folga: float = 40.0) -> None:
        for t in self.trabalhadores.values():
            if math.hypot(t.x - centro[0], t.y - centro[1]) <= raio:
                self.sair_do_raio(t.id, centro, raio, folga)

    def definir_sinal(self, id_: str, ligado: bool) -> None:
        self.trabalhadores[id_].sinal = ligado


class AudioConsole:
    """Alto-falantes fictícios: guarda (e opcionalmente imprime) o que seria tocado."""

    def __init__(self, imprimir: Optional[Callable[[str], None]] = None):
        self.imprimir = imprimir
        self.tocando: Optional[Alerta] = None
        self.historico: list[int] = []

    def tocar(self, alerta: Alerta) -> None:
        self.tocando = alerta
        self.historico.append(alerta.nivel)
        if self.imprimir:
            self.imprimir(f"   >> ALTO-FALANTES (Nível {alerta.nivel}): \"{alerta.mensagem}\"")

    def parar(self) -> None:
        if self.tocando and self.imprimir:
            self.imprimir(f"   >> ALTO-FALANTES: fim do Nível {self.tocando.nivel}")
        self.tocando = None


class TravaSimulada:
    """Trava fictícia do circuito de disparo."""

    def __init__(self):
        self.liberada = False

    def liberar(self) -> None:
        self.liberada = True

    def bloquear(self) -> None:
        self.liberada = False


class RelogioManual:
    """Relógio controlado pelo programa (simula o tempo sem esperar de verdade)."""

    def __init__(self, inicio: float = 0.0):
        self.t = inicio

    def __call__(self) -> float:
        return self.t


def montar_sistema_simulado(config: dict, relogio: Callable[[], float] = time.monotonic,
                            audio=None) -> tuple[SistemaExpro, LocalizadorSimulado]:
    cfg = Configuracao.de_dict(config.get("sistema", {}))
    velocidade = config.get("simulacao", {}).get("velocidade_evacuacao_m_s", 8.0)
    localizador = LocalizadorSimulado(config.get("trabalhadores_simulados", []), velocidade)
    usuarios = usuarios_de_config(config.get("usuarios", []))
    sistema = SistemaExpro(cfg, localizador, audio or AudioConsole(), TravaSimulada(), usuarios, relogio)
    return sistema, localizador


def demonstracao(config: dict, imprimir: Callable[[str], None] = print) -> SistemaExpro:
    """Roteiro automático com os dados fictícios: percorre RF-01..03 e RN-01..04."""
    relogio = RelogioManual()
    sistema, loc = montar_sistema_simulado(config, relogio, AudioConsole(imprimir))
    sistema.ouvintes.append(lambda evento: imprimir(str(evento)))
    tecnico = next(u for u in sistema.usuarios.values() if u.eh_tecnico)
    blaster = next(u for u in sistema.usuarios.values() if not u.eh_tecnico)
    centro = sistema.config.explosivo_xy
    cfg = sistema.config

    def esperar(segundos: float, passo: float = 0.5) -> None:
        fim = relogio.t + segundos
        while relogio.t < fim - 1e-9:
            relogio.t = min(fim, relogio.t + passo)
            sistema.atualizar()

    def etapa(titulo: str) -> None:
        s = sistema.status()
        imprimir(f"\n=== {titulo} ===\n    estado: {s.estado.value} | raio {s.raio_m:g} m | "
                 f"{s.pessoas_no_raio} pessoa(s) no raio | trava: "
                 f"{'LIBERADA' if s.detonacao_liberada else 'BLOQUEADA'}")

    def acao(usuario: Optional[Usuario], descricao: str, executar: Callable) -> None:
        imprimir(f"  > {usuario.nome if usuario else 'Alguém no canteiro'} tenta: {descricao}")
        imprimir(f"    resultado: {'OK' if executar().ok else 'NEGADO'}")

    sistema.atualizar()
    etapa("1. Explosivos posicionados: verificação da área")
    acao(blaster, "autorizar a detonação", lambda: sistema.autorizar_detonacao(blaster))  # RN-02
    acao(tecnico, "autorizar a detonação", lambda: sistema.autorizar_detonacao(tecnico))  # sem aviso Nível 3
    acao(blaster, "verificar a área e acionar o Nível 3", lambda: sistema.acionar_nivel3(blaster))  # RF-02
    loc.evacuar(centro, sistema.raio_m)

    etapa("2. Evacuação em andamento")
    esperar(5)
    acao(tecnico, "autorizar a detonação", lambda: sistema.autorizar_detonacao(tecnico))  # RN-01
    esperar(cfg.duracao_nivel3_s + cfg.intervalo_entre_avisos_s)

    etapa("3. Área livre: Técnico autoriza (Nível 2 + contagem)")
    acao(tecnico, "autorizar a detonação", lambda: sistema.autorizar_detonacao(tecnico))  # RF-01
    esperar(min(10, cfg.contagem_regressiva_s / 2))

    intruso = next(iter(loc.trabalhadores))
    etapa(f"4. {intruso} volta para o raio durante a contagem")
    loc.entrar_no_raio(intruso, centro, sistema.raio_m)
    for _ in range(int(60 / 0.5)):
        esperar(0.5)
        if sistema.estado is not Estado.CONTAGEM:
            break
    loc.sair_do_raio(intruso, centro, sistema.raio_m)
    esperar(cfg.intervalo_entre_avisos_s + 5)

    etapa("5. Nova autorização com a área livre")
    acao(tecnico, "autorizar a detonação", lambda: sistema.autorizar_detonacao(tecnico))
    esperar(cfg.contagem_regressiva_s + 1)
    acao(blaster, "registrar que a detonação ocorreu", lambda: sistema.registrar_detonacao(blaster))

    etapa("6. Pós-detonação: reentrada (RN-04)")
    acao(blaster, "liberar a reentrada", lambda: sistema.validar_reentrada(blaster))
    acao(tecnico, "liberar a reentrada após vistoria", lambda: sistema.validar_reentrada(tecnico))

    etapa("7. Botão de emergência (RN-03)")
    esperar(cfg.intervalo_entre_avisos_s)
    acao(blaster, "acionar o Nível 3", lambda: sistema.acionar_nivel3(blaster))
    esperar(3)
    acao(None, "apertar o botão de emergência", lambda: sistema.acionar_emergencia("botão físico"))
    esperar(20)
    acao(blaster, "encerrar a emergência", lambda: sistema.encerrar_emergencia(blaster))
    acao(tecnico, "encerrar a emergência", lambda: sistema.encerrar_emergencia(tecnico))

    etapa("Fim da demonstração")
    imprimir(f"    níveis de áudio reproduzidos, em ordem: {sistema.audio.historico}")
    return sistema
