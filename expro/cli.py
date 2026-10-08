"""Terminal de controle do EXPRO.

    python -m expro                       # terminal interativo (cenário fictício)
    python -m expro --config config/meu_canteiro.toml
    python -m expro demo                  # roteiro automático
    python -m expro hash-pin              # gera pin_sha256 para o arquivo de configuração
"""

from __future__ import annotations

import argparse
import cmd
import getpass
import threading
import time
from pathlib import Path
from typing import Optional

from .config import carregar_config, montar_sistema
from .nucleo import ROTULO_PERFIL, SistemaExpro, Usuario
from .simulacao import LocalizadorSimulado, demonstracao

CONFIG_PADRAO = Path(__file__).resolve().parent.parent / "config" / "cenario_ficticio.toml"


class Terminal(cmd.Cmd):
    intro = "PROJETO EXPRO — terminal de controle. Digite 'ajuda' para ver os comandos.\n"
    prompt = "expro> "

    def __init__(self, sistema: SistemaExpro, simulador: Optional[LocalizadorSimulado] = None):
        super().__init__()
        self.sistema = sistema
        self.simulador = simulador
        self.usuario: Optional[Usuario] = None

    def _mostrar(self, resultado) -> None:
        print(("OK: " if resultado.ok else "NEGADO: ") + resultado.mensagem)

    def emptyline(self) -> bool:
        return False

    def default(self, linha: str) -> bool:
        print(f"Comando desconhecido: {linha}. Digite 'ajuda'.")
        return False

    def do_ajuda(self, _arg: str) -> None:
        """Lista os comandos."""
        self.do_help("")

    def do_login(self, arg: str) -> None:
        """login <usuario> — entra no sistema (o PIN é pedido em seguida)."""
        login = arg.strip() or input("Usuário: ").strip()
        usuario = self.sistema.autenticar(login, getpass.getpass("PIN: "))
        if usuario:
            self.usuario = usuario
            print(f"Conectado: {usuario.nome} ({ROTULO_PERFIL[usuario.perfil]}).")
        else:
            print("Usuário ou PIN incorreto.")

    def do_logout(self, _arg: str) -> None:
        """logout — encerra a sessão."""
        self.usuario = None
        print("Sessão encerrada.")

    def do_status(self, _arg: str) -> None:
        """status — estado do sistema e pessoas no raio."""
        self.sistema.atualizar()
        s = self.sistema.status()
        print(f"Estado: {s.estado.value} | terreno {s.terreno} (raio {s.raio_m:g} m) | "
              f"trava: {'LIBERADA' if s.detonacao_liberada else 'BLOQUEADA'}")
        print(f"Pessoas no raio: {s.pessoas_no_raio} | sem sinal: {s.sem_sinal} | monitorados: {s.monitorados}")
        if s.alerta:
            quanto = "contínuo" if s.alerta_restante_s is None else f"{s.alerta_restante_s:.0f} s"
            print(f"Áudio: Nível {s.alerta.nivel} ({quanto})")
        elif s.intervalo_restante_s > 0:
            print(f"Próximo aviso liberado em {s.intervalo_restante_s:.0f} s")
        if s.contagem_restante_s is not None:
            print(f"Contagem regressiva: {s.contagem_restante_s:.0f} s")
        for p in self.sistema.varredura.pessoas:
            distancia = "—" if p.distancia_m is None else f"{p.distancia_m:6.0f} m"
            print(f"   {p.id:<10} {p.nome:<14} {distancia}  {p.situacao.value}")

    def do_terreno(self, arg: str) -> None:
        """terreno <nome> — seleciona o terreno (define o raio). Ex.: terreno rocha_dura"""
        if not arg.strip():
            print("Terrenos: " + ", ".join(f"{k} ({v:g} m)" for k, v in self.sistema.config.raios_terreno_m.items()))
            return
        self._mostrar(self.sistema.selecionar_terreno(self.usuario, arg.strip()))

    def do_teste(self, _arg: str) -> None:
        """teste — modo de teste de áudio (Níveis 3, 2 e 1)."""
        self._mostrar(self.sistema.testar_audio(self.usuario))

    def do_nivel3(self, _arg: str) -> None:
        """nivel3 — verificar área e acionar aviso Nível 3 (Operário/Blaster ou Técnico)."""
        resultado = self.sistema.acionar_nivel3(self.usuario)
        self._mostrar(resultado)
        if resultado.ok and self.simulador:
            self.simulador.evacuar(self.sistema.config.explosivo_xy, self.sistema.raio_m)

    def do_autorizar(self, _arg: str) -> None:
        """autorizar — Técnico autoriza a detonação (Nível 2 + contagem regressiva)."""
        self._mostrar(self.sistema.autorizar_detonacao(self.usuario))

    def do_detonado(self, _arg: str) -> None:
        """detonado — registra que o disparo ocorreu."""
        self._mostrar(self.sistema.registrar_detonacao(self.usuario))

    def do_reentrada(self, _arg: str) -> None:
        """reentrada — Técnico valida a reentrada após vistoria presencial (RN-04)."""
        self._mostrar(self.sistema.validar_reentrada(self.usuario))

    def do_emergencia(self, _arg: str) -> None:
        """emergencia — botão de emergência: Nível 1 contínuo (RN-03)."""
        self._mostrar(self.sistema.acionar_emergencia("terminal"))

    def do_parar(self, _arg: str) -> None:
        """parar — Técnico encerra a emergência."""
        self._mostrar(self.sistema.encerrar_emergencia(self.usuario))

    def do_baixa(self, arg: str) -> None:
        """baixa <ID> — Técnico retira um capacete devolvido do monitoramento."""
        self._mostrar(self.sistema.dar_baixa_capacete(self.usuario, arg.strip()))

    def do_sim(self, arg: str) -> None:
        """sim entrar|sair|sinal <ID> | sim evacuar — move as pessoas fictícias (só no modo simulado)."""
        if self.simulador is None:
            print("Disponível apenas com hardware.localizacao = \"simulado\".")
            return
        partes = arg.split()
        centro, raio = self.sistema.config.explosivo_xy, self.sistema.raio_m
        try:
            if partes == ["evacuar"]:
                self.simulador.evacuar(centro, raio)
            elif len(partes) == 2 and partes[0] == "entrar":
                self.simulador.entrar_no_raio(partes[1], centro, raio)
            elif len(partes) == 2 and partes[0] == "sair":
                self.simulador.sair_do_raio(partes[1], centro, raio)
            elif len(partes) == 2 and partes[0] == "sinal":
                t = self.simulador.trabalhadores[partes[1]]
                self.simulador.definir_sinal(t.id, not t.sinal)
                print(f"Localizador {t.id}: {'ligado' if t.sinal else 'desligado'}")
            else:
                print("Uso: sim entrar <ID> | sim sair <ID> | sim sinal <ID> | sim evacuar")
        except KeyError:
            print("Capacete desconhecido. IDs: " + ", ".join(self.simulador.trabalhadores))

    def do_sair(self, _arg: str) -> bool:
        """sair — fecha o programa (a trava permanece bloqueada)."""
        return True

    do_EOF = do_sair


def _monitorar(sistema: SistemaExpro, parar: threading.Event, intervalo_s: float = 0.5) -> None:
    while not parar.wait(intervalo_s):
        sistema.atualizar()


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(prog="expro", description="PROJETO EXPRO — EXplosion PROtection")
    parser.add_argument("comando", nargs="?", default="terminal", choices=["terminal", "demo", "hash-pin"])
    parser.add_argument("--config", default=str(CONFIG_PADRAO), help="arquivo .toml de configuração")
    parser.add_argument("--acelerar", type=float, default=1.0,
                        help="acelera o relógio (apenas para demonstrações com dados fictícios)")
    args = parser.parse_args(argv)

    if args.comando == "hash-pin":
        login = input("Login: ").strip()
        print(f'pin_sha256 = "{Usuario.gerar_hash(login, getpass.getpass("PIN: "))}"')
        return

    config = carregar_config(args.config)
    if args.comando == "demo":
        demonstracao(config)
        return

    t0 = time.monotonic()
    sistema, componentes = montar_sistema(config, lambda: (time.monotonic() - t0) * max(1.0, args.acelerar))
    sistema.ouvintes.append(lambda evento: print(f"\n{evento}"))
    parar = threading.Event()
    threading.Thread(target=_monitorar, args=(sistema, parar), daemon=True).start()
    try:
        Terminal(sistema, componentes.get("simulador")).cmdloop()
    except KeyboardInterrupt:
        pass
    finally:
        parar.set()
        sistema.trava.bloquear()
        sistema.audio.parar()
        if "mqtt" in componentes:
            componentes["mqtt"].fechar()
