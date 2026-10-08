"""Critérios de aceitação do DERF (RF-01..03, RN-01..04) com dados fictícios."""

import pytest

from expro.nucleo import Configuracao, Estado, Usuario
from expro.simulacao import AudioConsole, LocalizadorSimulado, RelogioManual, TravaSimulada
from expro.nucleo import SistemaExpro

TECNICO = Usuario.criar("tecnico", "Ana", "tecnico", "1234")
BLASTER = Usuario.criar("blaster", "Carlos", "operario", "0000")


class Cenario:
    def __init__(self, trabalhadores=None, **config):
        self.relogio = RelogioManual()
        self.loc = LocalizadorSimulado(trabalhadores if trabalhadores is not None else
                                       [{"id": "CAP-01", "x": 50, "y": 0}, {"id": "CAP-02", "x": 400, "y": 0}],
                                       velocidade_m_s=100)
        self.audio = AudioConsole()
        self.trava = TravaSimulada()
        self.sistema = SistemaExpro(Configuracao(**config), self.loc, self.audio, self.trava,
                                    [TECNICO, BLASTER], self.relogio)
        self.sistema.atualizar()

    def esperar(self, segundos, passo=0.5):
        fim = self.relogio.t + segundos
        while self.relogio.t < fim - 1e-9:
            self.relogio.t = min(fim, self.relogio.t + passo)
            self.sistema.atualizar()

    def evacuar(self):
        self.loc.evacuar(self.sistema.config.explosivo_xy, self.sistema.raio_m)
        self.esperar(5)

    def preparar_para_autorizar(self):
        assert self.sistema.acionar_nivel3(BLASTER)
        self.evacuar()
        self.esperar(self.sistema.config.duracao_nivel3_s + self.sistema.config.intervalo_entre_avisos_s)


@pytest.fixture
def c():
    return Cenario()


def test_inicia_bloqueado_e_conta_pessoas_no_raio(c):
    s = c.sistema.status()
    assert s.estado is Estado.PREPARACAO
    assert not c.trava.liberada and not s.detonacao_liberada
    assert s.pessoas_no_raio == 1  # ESC-03: CAP-01 a 50 m; CAP-02 está fora (400 m)


def test_rn02_somente_tecnico_autoriza(c):
    c.preparar_para_autorizar()
    r = c.sistema.autorizar_detonacao(BLASTER)
    assert not r and "RN-02" in r.mensagem
    assert not c.sistema.autorizar_detonacao(None)
    assert c.sistema.autorizar_detonacao(TECNICO)


def test_rn01_bloqueia_autorizacao_com_pessoa_no_raio(c):
    assert c.sistema.acionar_nivel3(BLASTER)
    c.esperar(c.sistema.config.duracao_nivel3_s + c.sistema.config.intervalo_entre_avisos_s)
    r = c.sistema.autorizar_detonacao(TECNICO)  # ninguém evacuou
    assert not r and "RN-01" in r.mensagem
    assert c.sistema.estado is Estado.POSICIONAMENTO and not c.trava.liberada


def test_rf01_fluxo_completo_libera_somente_com_area_livre(c):
    c.preparar_para_autorizar()
    assert c.sistema.autorizar_detonacao(TECNICO)
    assert c.audio.tocando.nivel == 2
    c.esperar(c.sistema.config.contagem_regressiva_s - 1)
    assert not c.trava.liberada
    c.esperar(1.5)
    assert c.sistema.estado is Estado.DETONACAO_LIBERADA and c.trava.liberada
    assert c.sistema.registrar_detonacao(BLASTER)
    assert c.sistema.estado is Estado.AGUARDANDO_REENTRADA and not c.trava.liberada


def test_rn01_pessoa_entrando_durante_contagem_cancela(c):
    c.preparar_para_autorizar()
    assert c.sistema.autorizar_detonacao(TECNICO)
    c.loc.trabalhadores["CAP-02"].x = 10  # alguém entra no raio
    c.esperar(0.5)
    assert c.sistema.estado is Estado.POSICIONAMENTO
    assert not c.trava.liberada and c.audio.tocando is None
    assert any("RN-01" in e.texto for e in c.sistema.eventos)
    c.esperar(60)
    assert not c.trava.liberada


def test_rn01_pessoa_entrando_na_janela_de_disparo_bloqueia(c):
    c.preparar_para_autorizar()
    c.sistema.autorizar_detonacao(TECNICO)
    c.esperar(c.sistema.config.contagem_regressiva_s + 0.5)
    assert c.trava.liberada
    c.loc.trabalhadores["CAP-02"].x = 10
    c.esperar(0.5)
    assert not c.trava.liberada and c.sistema.estado is Estado.POSICIONAMENTO


def test_janela_de_disparo_expira(c):
    c.preparar_para_autorizar()
    c.sistema.autorizar_detonacao(TECNICO)
    c.esperar(c.sistema.config.contagem_regressiva_s + c.sistema.config.janela_disparo_s + 1)
    assert not c.trava.liberada and c.sistema.estado is Estado.POSICIONAMENTO


def test_rf02_nivel3_exige_login_e_toca_15s(c):
    assert not c.sistema.acionar_nivel3(None)
    assert c.sistema.acionar_nivel3(BLASTER)
    assert c.audio.tocando.nivel == 3
    c.esperar(14.5)
    assert c.audio.tocando is not None
    c.esperar(0.5)
    assert c.audio.tocando is None


def test_intervalo_de_30s_entre_avisos(c):
    assert c.sistema.acionar_nivel3(BLASTER)
    c.esperar(15)
    r = c.sistema.acionar_nivel3(BLASTER)
    assert not r and "intervalo" in r.mensagem
    c.esperar(29.5)
    assert not c.sistema.acionar_nivel3(BLASTER)
    c.esperar(0.5)
    assert c.sistema.acionar_nivel3(BLASTER)


def test_nivel2_dura_30s(c):
    c.preparar_para_autorizar()
    c.sistema.autorizar_detonacao(TECNICO)
    c.esperar(29.5)
    assert c.audio.tocando and c.audio.tocando.nivel == 2
    c.esperar(0.5)
    assert c.audio.tocando is None


def test_rn03_emergencia_interrompe_contagem_e_ignora_intervalo(c):
    c.preparar_para_autorizar()
    c.sistema.autorizar_detonacao(TECNICO)
    c.esperar(5)
    assert c.sistema.acionar_emergencia("teste")
    assert c.sistema.estado is Estado.EMERGENCIA
    assert c.audio.tocando.nivel == 1 and not c.trava.liberada
    c.esperar(600)  # contínuo até interrupção manual
    assert c.audio.tocando.nivel == 1 and not c.trava.liberada
    assert not c.sistema.encerrar_emergencia(BLASTER)
    assert c.sistema.encerrar_emergencia(TECNICO)
    assert c.audio.tocando is None and c.sistema.estado is Estado.PREPARACAO


def test_emergencia_nao_depende_de_login_nem_de_sensor():
    class LocalizadorQuebrado:
        def ler(self, agora):
            raise OSError("gateway desconectado")

    c = Cenario()
    c.sistema.localizador = LocalizadorQuebrado()
    assert c.sistema.acionar_emergencia("botão físico")
    assert c.audio.tocando.nivel == 1


def test_emergencia_apos_detonacao_volta_para_reentrada(c):
    c.preparar_para_autorizar()
    c.sistema.autorizar_detonacao(TECNICO)
    c.esperar(c.sistema.config.contagem_regressiva_s + 0.5)
    c.sistema.registrar_detonacao(BLASTER)
    c.sistema.acionar_emergencia()
    c.sistema.encerrar_emergencia(TECNICO)
    assert c.sistema.estado is Estado.AGUARDANDO_REENTRADA


def test_rn04_reentrada_somente_tecnico(c):
    c.preparar_para_autorizar()
    c.sistema.autorizar_detonacao(TECNICO)
    c.esperar(c.sistema.config.contagem_regressiva_s + 0.5)
    c.sistema.registrar_detonacao(BLASTER)
    assert not c.sistema.acionar_nivel3(BLASTER)  # área interditada
    r = c.sistema.validar_reentrada(BLASTER)
    assert not r and "RN-04" in r.mensagem
    assert c.sistema.validar_reentrada(TECNICO)
    assert c.sistema.estado is Estado.PREPARACAO


def test_rf03_modo_de_teste_cobre_niveis_3_2_1(c):
    assert c.sistema.testar_audio(BLASTER, duracao_por_nivel_s=3)
    assert c.sistema.estado is Estado.TESTE_AUDIO
    c.esperar(10)
    assert c.audio.historico == [3, 2, 1]
    assert c.audio.tocando is None and c.sistema.estado is Estado.PREPARACAO
    assert not c.trava.liberada


def test_failsafe_capacete_sem_sinal_bloqueia(c):
    c.sistema.acionar_nivel3(BLASTER)
    c.evacuar()
    c.loc.definir_sinal("CAP-02", False)
    c.esperar(c.sistema.config.duracao_nivel3_s + c.sistema.config.intervalo_entre_avisos_s)
    assert c.sistema.status().sem_sinal == 1
    r = c.sistema.autorizar_detonacao(TECNICO)
    assert not r and "CAP-02" in r.mensagem


def test_sem_sinal_pode_ser_ignorado_por_configuracao():
    c = Cenario(bloquear_sem_sinal=False)
    c.sistema.acionar_nivel3(BLASTER)
    c.evacuar()
    c.loc.definir_sinal("CAP-02", False)
    c.esperar(45)
    assert c.sistema.autorizar_detonacao(TECNICO)


def test_capacete_cadastrado_que_nunca_enviou_posicao_bloqueia():
    c = Cenario(trabalhadores=[], capacetes_cadastrados=("CAP-09",))
    c.preparar_para_autorizar()
    assert not c.sistema.autorizar_detonacao(TECNICO)
    assert c.sistema.dar_baixa_capacete(TECNICO, "CAP-09")
    assert c.sistema.autorizar_detonacao(TECNICO)


def test_falha_no_localizador_vira_sem_sinal_e_bloqueia(c):
    c.preparar_para_autorizar()

    class LocalizadorQuebrado:
        def ler(self, agora):
            raise OSError("gateway desconectado")

    c.sistema.localizador = LocalizadorQuebrado()
    c.esperar(c.sistema.config.timeout_sinal_s + 1)
    assert not c.sistema.autorizar_detonacao(TECNICO)
    assert any("Falha na leitura" in e.texto for e in c.sistema.eventos)


def test_terreno_define_raio_e_so_muda_na_preparacao(c):
    assert c.sistema.selecionar_terreno(BLASTER, "solo")
    assert c.sistema.raio_m == 150
    assert not c.sistema.selecionar_terreno(None, "rocha_dura")
    assert not c.sistema.selecionar_terreno(BLASTER, "lava")
    c.sistema.acionar_nivel3(BLASTER)
    assert not c.sistema.selecionar_terreno(BLASTER, "rocha_dura")


def test_autenticacao_por_pin():
    c = Cenario()
    assert c.sistema.autenticar("tecnico", "1234") == TECNICO
    assert c.sistema.autenticar("tecnico", "9999") is None
    assert c.sistema.autenticar("ninguem", "1234") is None


def test_falha_no_audio_nao_impede_bloqueio():
    class AudioQuebrado:
        def tocar(self, alerta):
            raise OSError("amplificador desligado")

        def parar(self):
            raise OSError("amplificador desligado")

    c = Cenario()
    c.sistema.audio = AudioQuebrado()
    assert c.sistema.acionar_emergencia()
    assert not c.trava.liberada
    assert any("Falha na saída de áudio" in e.texto for e in c.sistema.eventos)


def test_configuracao_invalida():
    with pytest.raises(ValueError):
        Configuracao.de_dict({"terreno": "marte"})
    with pytest.raises(ValueError):
        Configuracao.de_dict({"parametro_inexistente": 1})
