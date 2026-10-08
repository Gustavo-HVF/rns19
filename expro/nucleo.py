"""Núcleo do EXPRO: regras do DERF "Projeto NR-19: Explosivos".

Não depende de hardware. Localizadores, áudio e trava da detonação entram por
adaptadores, então o mesmo núcleo roda com dados fictícios ou sensores reais.
"""

from __future__ import annotations

import functools
import hashlib
import hmac
import math
import threading
import time
from dataclasses import dataclass, field, fields
from enum import Enum
from typing import Callable, Iterable, Optional, Protocol

# ---------------------------------------------------------------------------
# Usuários e perfis (Atores 1 e 2, RN-02)
# ---------------------------------------------------------------------------


class Perfil(str, Enum):
    TECNICO = "tecnico"  # Ator 1 — Técnico de Segurança
    OPERARIO = "operario"  # Ator 2 — Operário / Blaster


ROTULO_PERFIL = {Perfil.TECNICO: "Técnico de Segurança", Perfil.OPERARIO: "Operário / Blaster"}


@dataclass(frozen=True)
class Usuario:
    login: str
    nome: str
    perfil: Perfil
    pin_hash: str

    @staticmethod
    def gerar_hash(login: str, pin: str) -> str:
        return hashlib.sha256(f"expro|{login}|{pin}".encode("utf-8")).hexdigest()

    @classmethod
    def criar(cls, login: str, nome: str, perfil: Perfil | str, pin: str) -> Usuario:
        return cls(login, nome, Perfil(perfil), cls.gerar_hash(login, pin))

    def confere_pin(self, pin: str) -> bool:
        return hmac.compare_digest(self.pin_hash, self.gerar_hash(self.login, pin))

    @property
    def eh_tecnico(self) -> bool:
        return self.perfil is Perfil.TECNICO


def usuarios_de_config(lista: Iterable[dict]) -> list[Usuario]:
    """Aceita {"login", "nome", "perfil", "pin"} ou {"...", "pin_sha256"}."""
    usuarios = []
    for item in lista:
        if "pin_sha256" in item:
            usuarios.append(Usuario(item["login"], item["nome"], Perfil(item["perfil"]), item["pin_sha256"]))
        else:
            usuarios.append(Usuario.criar(item["login"], item["nome"], item["perfil"], str(item["pin"])))
    return usuarios


# ---------------------------------------------------------------------------
# Alertas sonoros (RF-03 — matriz de níveis)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Alerta:
    nivel: int
    titulo: str
    mensagem: str
    duracao_s: Optional[float]  # None = contínuo, até interrupção manual

    @property
    def continuo(self) -> bool:
        return self.duracao_s is None


def criar_alertas(duracao_nivel3_s: float = 15, duracao_nivel2_s: float = 30) -> dict[int, Alerta]:
    return {
        3: Alerta(3, "POSICIONAMENTO",
                  "Posicionamento de explosivos concluído. Favor evacuar a área de risco.", duracao_nivel3_s),
        2: Alerta(2, "DETONAÇÃO IMINENTE",
                  "Detonação iminente! Evacuação imediata obrigatória.", duracao_nivel2_s),
        1: Alerta(1, "EMERGÊNCIA / INSTABILIDADE",
                  "Alerta de emergência! Explosivos instáveis na área.", None),
    }


# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------


@dataclass
class Configuracao:
    explosivo_xy: tuple[float, float] = (0.0, 0.0)
    # Raio de risco por tipo de terreno, escolhido manualmente (ESC-04). Valores fictícios.
    raios_terreno_m: dict[str, float] = field(
        default_factory=lambda: {"solo": 150.0, "rocha_branda": 200.0, "rocha_dura": 250.0})
    terreno: str = "rocha_dura"
    duracao_nivel3_s: float = 15
    duracao_nivel2_s: float = 30
    intervalo_entre_avisos_s: float = 30  # cooldown (Ator 3 — temporizador)
    contagem_regressiva_s: float = 30
    janela_disparo_s: float = 60  # tempo em que a trava fica liberada aguardando o disparo
    timeout_sinal_s: float = 10  # capacete sem sinal há mais que isso = "sem sinal"
    bloquear_sem_sinal: bool = True  # fail-safe: capacete sem sinal conta como presente
    capacetes_cadastrados: tuple[str, ...] = ()

    @classmethod
    def de_dict(cls, dados: dict) -> Configuracao:
        nomes = {f.name for f in fields(cls)}
        desconhecidos = set(dados) - nomes
        if desconhecidos:
            raise ValueError(f"Parâmetros desconhecidos em [sistema]: {', '.join(sorted(desconhecidos))}")
        dados = dict(dados)
        if "explosivo_xy" in dados:
            dados["explosivo_xy"] = tuple(float(v) for v in dados["explosivo_xy"])
        if "raios_terreno_m" in dados:
            dados["raios_terreno_m"] = {k: float(v) for k, v in dados["raios_terreno_m"].items()}
        if "capacetes_cadastrados" in dados:
            dados["capacetes_cadastrados"] = tuple(dados["capacetes_cadastrados"])
        cfg = cls(**dados)
        cfg.validar()
        return cfg

    def validar(self) -> None:
        if self.terreno not in self.raios_terreno_m:
            raise ValueError(f"Terreno '{self.terreno}' não está em raios_terreno_m.")
        if any(r <= 0 for r in self.raios_terreno_m.values()):
            raise ValueError("Todos os raios de risco devem ser positivos.")
        for nome in ("duracao_nivel3_s", "duracao_nivel2_s", "contagem_regressiva_s",
                     "janela_disparo_s", "timeout_sinal_s"):
            if getattr(self, nome) <= 0:
                raise ValueError(f"{nome} deve ser positivo.")
        if self.intervalo_entre_avisos_s < 0:
            raise ValueError("intervalo_entre_avisos_s não pode ser negativo.")


# ---------------------------------------------------------------------------
# Interfaces dos adaptadores (o que o hardware precisa oferecer)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Leitura:
    """Posição de um capacete, em metros (x = leste, y = norte) no referencial do canteiro."""
    id: str
    x: float
    y: float
    instante: float
    nome: str = ""


class FonteLocalizacao(Protocol):
    def ler(self, agora: float) -> Iterable[Leitura]: ...


class SaidaAudio(Protocol):
    def tocar(self, alerta: Alerta) -> None: ...
    def parar(self) -> None: ...


class TravaDetonacao(Protocol):
    def liberar(self) -> None: ...
    def bloquear(self) -> None: ...


# ---------------------------------------------------------------------------
# Varredura da área (ESC-03)
# ---------------------------------------------------------------------------


class Situacao(str, Enum):
    DENTRO = "dentro do raio"
    FORA = "fora do raio"
    SEM_SINAL = "sem sinal"


@dataclass(frozen=True)
class Pessoa:
    id: str
    nome: str
    x: Optional[float]
    y: Optional[float]
    distancia_m: Optional[float]
    situacao: Situacao
    idade_leitura_s: Optional[float]


@dataclass(frozen=True)
class Varredura:
    raio_m: float
    pessoas: tuple[Pessoa, ...]

    @property
    def dentro(self) -> list[Pessoa]:
        return [p for p in self.pessoas if p.situacao is Situacao.DENTRO]

    @property
    def sem_sinal(self) -> list[Pessoa]:
        return [p for p in self.pessoas if p.situacao is Situacao.SEM_SINAL]


# ---------------------------------------------------------------------------
# Estados, eventos e resultados
# ---------------------------------------------------------------------------


class Estado(str, Enum):
    PREPARACAO = "PREPARAÇÃO"
    TESTE_AUDIO = "TESTE DE ÁUDIO"
    POSICIONAMENTO = "POSICIONAMENTO / EVACUAÇÃO"
    CONTAGEM = "CONTAGEM REGRESSIVA"
    DETONACAO_LIBERADA = "DETONAÇÃO LIBERADA"
    AGUARDANDO_REENTRADA = "AGUARDANDO REENTRADA"
    EMERGENCIA = "EMERGÊNCIA"


@dataclass(frozen=True)
class Evento:
    instante: float  # segundos desde o início do sistema
    tipo: str  # "info" | "aviso" | "bloqueio" | "emergencia" | "sucesso"
    texto: str

    def __str__(self) -> str:
        return f"[{self.instante:7.1f} s] {self.tipo.upper():<10} {self.texto}"


@dataclass(frozen=True)
class Resultado:
    ok: bool
    mensagem: str

    def __bool__(self) -> bool:
        return self.ok


@dataclass(frozen=True)
class Status:
    estado: Estado
    terreno: str
    raio_m: float
    pessoas_no_raio: int
    sem_sinal: int
    monitorados: int
    alerta: Optional[Alerta]
    alerta_restante_s: Optional[float]
    intervalo_restante_s: float
    contagem_restante_s: Optional[float]
    janela_restante_s: Optional[float]
    detonacao_liberada: bool


def _sincronizado(metodo):
    """Sensores, botões e interface podem chamar o sistema de threads diferentes."""
    @functools.wraps(metodo)
    def envoltorio(self, *args, **kwargs):
        with self._lock:
            return metodo(self, *args, **kwargs)
    return envoltorio


# ---------------------------------------------------------------------------
# Sistema EXPRO
# ---------------------------------------------------------------------------


class SistemaExpro:
    def __init__(self, config: Configuracao, localizador: FonteLocalizacao, audio: SaidaAudio,
                 trava: TravaDetonacao, usuarios: Iterable[Usuario] = (),
                 relogio: Callable[[], float] = time.monotonic):
        config.validar()
        self.config = config
        self.localizador = localizador
        self.audio = audio
        self.trava = trava
        self.usuarios = {u.login: u for u in usuarios}
        self.relogio = relogio
        self.alertas = criar_alertas(config.duracao_nivel3_s, config.duracao_nivel2_s)

        self.estado = Estado.PREPARACAO
        self.eventos: list[Evento] = []
        self.ouvintes: list[Callable[[Evento], None]] = []
        self.leituras: dict[str, Leitura] = {}
        self.alerta_ativo: Optional[Alerta] = None
        self.detonacao_liberada = False

        self._lock = threading.RLock()
        self._inicio = relogio()
        self._fim_alerta: Optional[float] = None
        self._fim_intervalo = -math.inf
        self._fim_contagem: Optional[float] = None
        self._fim_janela: Optional[float] = None
        self._fila_teste: list[int] = []
        self._duracao_teste = 0.0
        self._estado_antes_emergencia = Estado.PREPARACAO
        self._baixados: set[str] = set()
        self._resumo_area: Optional[tuple[tuple[str, ...], tuple[str, ...]]] = None
        self._falha_leitura = False
        self.varredura = Varredura(self.raio_m, ())

        self._bloquear_trava()  # fail-safe: sempre inicia com a detonação bloqueada
        self._registrar("info", f"Sistema iniciado. Terreno: {self.config.terreno} "
                                f"(raio {self.raio_m:g} m). Detonação bloqueada.")

    # ------------------------------------------------------------ consulta
    @property
    def raio_m(self) -> float:
        return self.config.raios_terreno_m[self.config.terreno]

    def bloqueantes(self) -> list[Pessoa]:
        """Pessoas que impedem a detonação (RN-01)."""
        v = self.varredura
        return v.dentro + (v.sem_sinal if self.config.bloquear_sem_sinal else [])

    @_sincronizado
    def status(self) -> Status:
        agora = self.relogio()

        def restante(fim: Optional[float]) -> Optional[float]:
            return None if fim is None else max(0.0, fim - agora)

        v = self.varredura
        return Status(self.estado, self.config.terreno, self.raio_m, len(v.dentro), len(v.sem_sinal),
                      len(v.pessoas), self.alerta_ativo, restante(self._fim_alerta),
                      max(0.0, self._fim_intervalo - agora), restante(self._fim_contagem),
                      restante(self._fim_janela), self.detonacao_liberada)

    # ------------------------------------------------- monitoramento contínuo
    @_sincronizado
    def atualizar(self) -> Varredura:
        """Chamado periodicamente (ex.: a cada 0,5 s): lê sensores e aplica as regras."""
        agora = self.relogio()
        try:
            for leitura in self.localizador.ler(agora):
                self.leituras[leitura.id] = leitura
                self._baixados.discard(leitura.id)
            if self._falha_leitura:
                self._falha_leitura = False
                self._registrar("info", "Leitura dos localizadores restabelecida.")
        except Exception as erro:  # sensor com defeito não pode derrubar o sistema
            if not self._falha_leitura:
                self._falha_leitura = True
                self._registrar("aviso", f"Falha na leitura dos localizadores: {erro}")
        self.varredura = self._varrer(agora)
        self._notificar_area()
        self._controlar_audio(agora)
        self._controlar_sequencia(agora)
        return self.varredura

    def _varrer(self, agora: float) -> Varredura:
        ex, ey = self.config.explosivo_xy
        raio = self.raio_m
        ids = (set(self.leituras) | set(self.config.capacetes_cadastrados)) - self._baixados
        pessoas = []
        for id_ in sorted(ids):
            leitura = self.leituras.get(id_)
            if leitura is None:  # cadastrado, mas nunca enviou posição
                pessoas.append(Pessoa(id_, "", None, None, None, Situacao.SEM_SINAL, None))
                continue
            distancia = math.hypot(leitura.x - ex, leitura.y - ey)
            idade = agora - leitura.instante
            if idade > self.config.timeout_sinal_s:
                situacao = Situacao.SEM_SINAL
            elif distancia <= raio:
                situacao = Situacao.DENTRO
            else:
                situacao = Situacao.FORA
            pessoas.append(Pessoa(id_, leitura.nome, leitura.x, leitura.y, distancia, situacao, idade))
        return Varredura(raio, tuple(pessoas))

    def _notificar_area(self) -> None:
        dentro = tuple(p.id for p in self.varredura.dentro)
        sem_sinal = tuple(p.id for p in self.varredura.sem_sinal)
        anterior = self._resumo_area
        if anterior == (dentro, sem_sinal):
            return
        self._resumo_area = (dentro, sem_sinal)
        if anterior is None or anterior[0] != dentro:
            if dentro:
                self._registrar("aviso", f"{len(dentro)} pessoa(s) no raio de risco: {', '.join(dentro)}.")
            elif sem_sinal and self.config.bloquear_sem_sinal:
                self._registrar("aviso", "Nenhuma pessoa localizada dentro do raio, mas há "
                                         f"{len(sem_sinal)} capacete(s) sem sinal.")
            else:
                self._registrar("sucesso", "Nenhuma pessoa detectada no raio de risco.")
        antes_sem_sinal = set(anterior[1]) if anterior else set()
        for id_ in sorted(set(sem_sinal) - antes_sem_sinal):
            consequencia = ("tratado como presente na área (fail-safe)" if self.config.bloquear_sem_sinal
                            else "ignorado (bloquear_sem_sinal = false)")
            self._registrar("aviso", f"{id_}: localizador sem sinal — {consequencia}.")
        for id_ in sorted(antes_sem_sinal - set(sem_sinal)):
            if id_ not in self._baixados:
                self._registrar("info", f"{id_}: sinal do localizador restabelecido.")

    def _controlar_audio(self, agora: float) -> None:
        if self.alerta_ativo is None or self._fim_alerta is None or agora < self._fim_alerta:
            return
        if self.estado is Estado.TESTE_AUDIO:
            self._audio_parar()
            self.alerta_ativo = self._fim_alerta = None
            if self._fila_teste:
                self._tocar_alerta(self._fila_teste.pop(0), agora, self._duracao_teste, teste=True)
            else:
                self.estado = Estado.PREPARACAO
                self._registrar("sucesso", "Teste de áudio concluído: Níveis 3, 2 e 1 reproduzidos.")
        else:
            self._parar_alerta(agora, "concluído")

    def _controlar_sequencia(self, agora: float) -> None:
        if self.estado in (Estado.CONTAGEM, Estado.DETONACAO_LIBERADA):
            bloqueantes = self.bloqueantes()
            if bloqueantes:  # RN-01 vale durante toda a contagem e a janela de disparo
                self._bloquear_trava()
                if self.estado is Estado.CONTAGEM:
                    self._parar_alerta(agora, "interrompido")
                self._fim_contagem = self._fim_janela = None
                self.estado = Estado.POSICIONAMENTO
                ids = ", ".join(p.id for p in bloqueantes)
                self._registrar("bloqueio", f"RN-01: presença detectada no raio ({ids}). "
                                            "Contagem cancelada e detonação BLOQUEADA.")
                return
        if self.estado is Estado.CONTAGEM and agora >= self._fim_contagem:
            self._fim_contagem = None
            self._fim_janela = agora + self.config.janela_disparo_s
            self.estado = Estado.DETONACAO_LIBERADA
            self._liberar_trava()
            self._registrar("sucesso", "Contagem concluída com a área livre. Detonação LIBERADA "
                                       f"por {self.config.janela_disparo_s:g} s.")
        elif self.estado is Estado.DETONACAO_LIBERADA and agora >= self._fim_janela:
            self._bloquear_trava()
            self._fim_janela = None
            self.estado = Estado.POSICIONAMENTO
            self._registrar("aviso", "Janela de disparo encerrada sem confirmação. Detonação bloqueada novamente.")

    # ------------------------------------------------------------- ações
    @_sincronizado
    def autenticar(self, login: str, pin: str) -> Optional[Usuario]:
        usuario = self.usuarios.get(login)
        if usuario is not None and usuario.confere_pin(pin):
            self._registrar("info", f"Login: {usuario.nome} ({ROTULO_PERFIL[usuario.perfil]}).")
            return usuario
        self._registrar("aviso", f"Falha de autenticação para '{login}'.")
        return None

    @_sincronizado
    def selecionar_terreno(self, usuario: Optional[Usuario], terreno: str) -> Resultado:
        """ESC-04: o terreno é escolhido manualmente pelo operador; define o raio de risco."""
        self.atualizar()
        if usuario is None:
            return self._negar("Faça login para alterar o terreno.")
        if self.estado is not Estado.PREPARACAO:
            return self._negar("O terreno só pode ser alterado na etapa de PREPARAÇÃO.")
        if terreno not in self.config.raios_terreno_m:
            return self._negar(f"Terreno desconhecido: {terreno}.")
        self.config.terreno = terreno
        self._registrar("info", f"{usuario.nome} selecionou o terreno '{terreno}' (raio {self.raio_m:g} m).")
        self.atualizar()
        return Resultado(True, f"Terreno: {terreno} — raio de risco {self.raio_m:g} m.")

    @_sincronizado
    def testar_audio(self, usuario: Optional[Usuario], duracao_por_nivel_s: float = 3) -> Resultado:
        """Critério de aceitação do RF-03: modo de teste cobrindo os Níveis 3, 2 e 1."""
        self.atualizar()
        agora = self.relogio()
        if usuario is None:
            return self._negar("Faça login para testar o áudio.")
        if self.estado is not Estado.PREPARACAO:
            return self._negar("O teste de áudio só pode ser feito na etapa de PREPARAÇÃO.")
        espera = self._motivo_espera(agora)
        if espera:
            return self._negar(f"Teste de áudio indisponível: {espera}.")
        self.estado = Estado.TESTE_AUDIO
        self._duracao_teste = duracao_por_nivel_s
        self._fila_teste = [2, 1]
        self._registrar("info", f"{usuario.nome} iniciou o teste de áudio (Níveis 3, 2 e 1).")
        self._tocar_alerta(3, agora, duracao_por_nivel_s, teste=True)
        return Resultado(True, "Teste de áudio iniciado.")

    @_sincronizado
    def acionar_nivel3(self, usuario: Optional[Usuario]) -> Resultado:
        """RF-02: verificação da área + aviso Nível 3 (posicionamento concluído)."""
        self.atualizar()
        agora = self.relogio()
        if usuario is None:
            return self._negar("Faça login para acionar o aviso Nível 3.")
        if self.estado not in (Estado.PREPARACAO, Estado.POSICIONAMENTO):
            return self._negar(f"Aviso Nível 3 indisponível no estado {self.estado.value}.")
        espera = self._motivo_espera(agora)
        if espera:
            return self._negar(f"Aviso Nível 3 indisponível: {espera}.")
        dentro = len(self.varredura.dentro)
        self.estado = Estado.POSICIONAMENTO
        self._registrar("info", f"{usuario.nome} verificou a área: {dentro} pessoa(s) no raio de {self.raio_m:g} m.")
        self._tocar_alerta(3, agora)
        return Resultado(True, f"Aviso Nível 3 acionado. {dentro} pessoa(s) no raio de risco.")

    @_sincronizado
    def autorizar_detonacao(self, usuario: Optional[Usuario]) -> Resultado:
        """RF-01: Técnico autoriza a detonação e aciona o Nível 2 (RN-01 e RN-02)."""
        self.atualizar()
        agora = self.relogio()
        if usuario is None or not usuario.eh_tecnico:
            quem = usuario.nome if usuario else "Usuário não autenticado"
            return self._negar(f"RN-02: {quem} não tem permissão. Só o Técnico de Segurança autenticado "
                               "libera a detonação e o aviso Nível 2.", "bloqueio")
        if self.estado is Estado.PREPARACAO:
            return self._negar("Acione antes o aviso Nível 3 (posicionamento e evacuação).")
        if self.estado is not Estado.POSICIONAMENTO:
            return self._negar(f"Autorização indisponível no estado {self.estado.value}.")
        bloqueantes = self.bloqueantes()
        if bloqueantes:
            ids = ", ".join(p.id for p in bloqueantes)
            return self._negar(f"RN-01: detonação BLOQUEADA — {len(bloqueantes)} pessoa(s) no raio de risco "
                               f"({ids}).", "bloqueio")
        espera = self._motivo_espera(agora)
        if espera:
            return self._negar(f"Autorização indisponível: {espera}.")
        self.estado = Estado.CONTAGEM
        self._fim_contagem = agora + self.config.contagem_regressiva_s
        self._registrar("info", f"Detonação autorizada por {usuario.nome}. "
                                f"Contagem regressiva de {self.config.contagem_regressiva_s:g} s.")
        self._tocar_alerta(2, agora)
        return Resultado(True, f"Detonação autorizada. Contagem de {self.config.contagem_regressiva_s:g} s iniciada.")

    @_sincronizado
    def registrar_detonacao(self, usuario: Optional[Usuario]) -> Resultado:
        """Confirma que o disparo ocorreu; a área fica interditada até a validação (RN-04)."""
        self.atualizar()
        if usuario is None:
            return self._negar("Faça login para registrar a detonação.")
        if self.estado is not Estado.DETONACAO_LIBERADA:
            return self._negar("A detonação não está liberada.")
        self._bloquear_trava()
        self._fim_janela = None
        self.estado = Estado.AGUARDANDO_REENTRADA
        self._registrar("info", f"Detonação realizada (registrada por {usuario.nome}). Área interditada "
                                "até a validação presencial do Técnico de Segurança.")
        return Resultado(True, "Detonação registrada. Aguardando validação de reentrada.")

    @_sincronizado
    def validar_reentrada(self, usuario: Optional[Usuario]) -> Resultado:
        """RN-04: só o Técnico de Segurança, após vistoria no local, libera a reentrada."""
        self.atualizar()
        if usuario is None or not usuario.eh_tecnico:
            return self._negar("RN-04: a reentrada só pode ser validada pelo Técnico de Segurança, "
                               "após vistoria presencial.", "bloqueio")
        if self.estado is not Estado.AGUARDANDO_REENTRADA:
            return self._negar("Não há detonação aguardando validação de reentrada.")
        self.estado = Estado.PREPARACAO
        self._registrar("sucesso", f"RN-04: reentrada validada presencialmente por {usuario.nome}.")
        return Resultado(True, "Reentrada validada. Sistema em PREPARAÇÃO.")

    @_sincronizado
    def acionar_emergencia(self, origem: str = "painel") -> Resultado:
        """RN-03: qualquer pessoa pode acionar; Nível 1 contínuo e interrupção da contagem."""
        agora = self.relogio()
        if self.estado is Estado.EMERGENCIA:
            return Resultado(True, "Emergência já está ativa.")
        self._estado_antes_emergencia = self.estado
        self._bloquear_trava()
        self._fim_contagem = self._fim_janela = None
        self._fila_teste = []
        self.estado = Estado.EMERGENCIA
        self._registrar("emergencia", f"RN-03: botão de emergência acionado ({origem}). "
                                      "Sequência interrompida e detonação bloqueada.")
        self._tocar_alerta(1, agora)  # ignora o intervalo entre avisos
        return Resultado(True, "EMERGÊNCIA acionada: alerta Nível 1 contínuo.")

    @_sincronizado
    def encerrar_emergencia(self, usuario: Optional[Usuario]) -> Resultado:
        """Interrupção manual do Nível 1 (perfil elevado)."""
        agora = self.relogio()
        if usuario is None or not usuario.eh_tecnico:
            return self._negar("Só o Técnico de Segurança pode encerrar a emergência.", "bloqueio")
        if self.estado is not Estado.EMERGENCIA:
            return self._negar("Não há emergência ativa.")
        self._parar_alerta(agora, "interrompido manualmente")
        voltar_para_reentrada = self._estado_antes_emergencia is Estado.AGUARDANDO_REENTRADA
        self.estado = Estado.AGUARDANDO_REENTRADA if voltar_para_reentrada else Estado.PREPARACAO
        self._registrar("info", f"Emergência encerrada por {usuario.nome}. Estado: {self.estado.value}.")
        return Resultado(True, f"Emergência encerrada. Estado: {self.estado.value}.")

    @_sincronizado
    def dar_baixa_capacete(self, usuario: Optional[Usuario], id_capacete: str) -> Resultado:
        """Retira do monitoramento um capacete devolvido (ex.: fim de turno)."""
        if usuario is None or not usuario.eh_tecnico:
            return self._negar("Só o Técnico de Segurança pode dar baixa em capacetes.", "bloqueio")
        self._baixados.add(id_capacete)
        self.leituras.pop(id_capacete, None)
        self._registrar("info", f"{usuario.nome} deu baixa no capacete {id_capacete}.")
        self.atualizar()
        return Resultado(True, f"Capacete {id_capacete} retirado do monitoramento.")

    # ------------------------------------------------------------ internos
    def _motivo_espera(self, agora: float) -> Optional[str]:
        if self.alerta_ativo is not None:
            if self._fim_alerta is None:
                return f"áudio Nível {self.alerta_ativo.nivel} em reprodução"
            return (f"aguarde o fim do áudio Nível {self.alerta_ativo.nivel} "
                    f"({math.ceil(self._fim_alerta - agora)} s)")
        if agora < self._fim_intervalo:
            return f"intervalo entre avisos ({math.ceil(self._fim_intervalo - agora)} s restantes)"
        return None

    def _tocar_alerta(self, nivel: int, agora: float, duracao: Optional[float] = None, teste: bool = False) -> None:
        alerta = self.alertas[nivel]
        if self.alerta_ativo is not None:
            self._audio_parar()
        duracao = alerta.duracao_s if duracao is None else duracao
        self.alerta_ativo = alerta
        self._fim_alerta = None if duracao is None else agora + duracao
        try:
            self.audio.tocar(alerta)
        except Exception as erro:
            self._registrar("aviso", f"Falha na saída de áudio: {erro}")
        quanto = "contínuo" if duracao is None else f"{duracao:g} s"
        prefixo = "TESTE — " if teste else ""
        self._registrar("emergencia" if nivel == 1 and not teste else "aviso",
                        f"{prefixo}Áudio Nível {nivel} ({alerta.titulo}, {quanto}): \"{alerta.mensagem}\"")

    def _parar_alerta(self, agora: float, motivo: str) -> None:
        if self.alerta_ativo is None:
            return
        nivel = self.alerta_ativo.nivel
        self._audio_parar()
        self.alerta_ativo = self._fim_alerta = None
        self._fim_intervalo = agora + self.config.intervalo_entre_avisos_s
        self._registrar("info", f"Áudio Nível {nivel} {motivo}. Intervalo de "
                                f"{self.config.intervalo_entre_avisos_s:g} s até o próximo aviso.")

    def _audio_parar(self) -> None:
        try:
            self.audio.parar()
        except Exception as erro:
            self._registrar("aviso", f"Falha ao parar o áudio: {erro}")

    def _liberar_trava(self) -> None:
        self.trava.liberar()
        self.detonacao_liberada = True

    def _bloquear_trava(self) -> None:
        self.detonacao_liberada = False
        try:
            self.trava.bloquear()
        except Exception as erro:
            self._registrar("emergencia", f"FALHA AO BLOQUEAR A TRAVA DE DETONAÇÃO: {erro}")

    def _negar(self, texto: str, tipo: str = "aviso") -> Resultado:
        self._registrar(tipo, texto)
        return Resultado(False, texto)

    def _registrar(self, tipo: str, texto: str) -> None:
        evento = Evento(self.relogio() - self._inicio, tipo, texto)
        self.eventos.append(evento)
        del self.eventos[:-500]
        for ouvinte in list(self.ouvintes):
            try:
                ouvinte(evento)
            except Exception:
                pass  # erro na interface não interrompe as regras de segurança
