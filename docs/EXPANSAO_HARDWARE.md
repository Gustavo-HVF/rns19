# Expansão com hardware: localizadores nos capacetes e sistemas de áudio

O código já está dividido para isso: o **núcleo** (`expro/nucleo.py`) contém só as regras do DERF e
conversa com o mundo por três "tomadas" (interfaces). Trocar os dados fictícios por hardware real é
trocar o que está ligado em cada tomada, mudando o arquivo de configuração, sem mexer nas regras.

| Tomada | Interface | Fictício (hoje) | Real (expansão) |
|---|---|---|---|
| Localização | `ler(agora) -> [Leitura]` | `LocalizadorSimulado` | `LocalizadorMQTT` (capacetes) |
| Áudio | `tocar(alerta)` / `parar()` | `AudioConsole` | `AudioLocal` (caixa de som), `AudioMQTT` (capacetes, alto-falantes IP) |
| Trava | `liberar()` / `bloquear()` | `TravaSimulada` | `TravaRele` (relé no GPIO do Raspberry Pi) |

```
  CAPACETES                          CENTRAL (Raspberry Pi)                 SAÍDAS
 ┌─────────────────────┐  posição   ┌───────────────────────────┐        ┌──────────────────────┐
 │ ESP32 + GPS ou UWB  │ ─────────▶ │ Mosquitto (broker MQTT)   │ ─────▶ │ caixa de som/sirenes │
 │ buzzer, vibração,   │            │ python -m expro           │ ─────▶ │ rádio base (PTT)     │
 │ LED                 │ ◀───────── │ relé da trava (GPIO 17)   │ ─────▶ │ trava do disparo     │
 └─────────────────────┘   alerta   │ botão de emergência (27)  │        └──────────────────────┘
       Wi-Fi ou LoRa                └───────────────────────────┘
```

Tudo passa por **MQTT**, um protocolo leve de mensagens. Qualquer hardware que consiga publicar uma
mensagem MQTT (ESP32, gateway LoRa, Node-RED, celular) se integra sem mudar o EXPRO.

| Tópico | Sentido | Conteúdo |
|---|---|---|
| `expro/capacetes/<ID>/posicao` | capacete → central | `{"x": 12.5, "y": -40}` (metros) ou `{"lat": -16.68, "lon": -49.26}` |
| `expro/alerta` | central → saídas | `{"nivel": 1, 2 ou 3, "mensagem": "...", "duracao_s": 30}`; `{"nivel": 0}` = silêncio |
| `expro/emergencia` | botões → central | qualquer mensagem aciona o RN-03 |

---

## 1. Localizadores nos capacetes

### Qual tecnologia usar

| Ambiente | Tecnologia | Precisão típica | Observações |
|---|---|---|---|
| Céu aberto (pedreira, mina a céu aberto, obra) | **GPS/GNSS** (módulos NEO-6M, NEO-M8N) | 2 a 5 m | Barato e simples. Precisa ver o céu. |
| Céu aberto, alta precisão | **GPS RTK** (ex.: ZED-F9P + estação base) | centímetros | Mais caro; útil para raios pequenos. |
| Túneis e minas subterrâneas (sem GPS) | **UWB** (chips DW1000/DW3000, módulos DWM1001/DWM3001) + âncoras fixas nas galerias | 10 a 30 cm | Exige instalar âncoras com posição conhecida. |
| Subterrâneo, solução simples | **BLE beacons** ou **RFID** em pontos de passagem | por trecho | Diz em qual trecho a pessoa está, não a posição exata. |

Para levar a posição até a central:

- **Wi-Fi**: o mais fácil para o protótipo da feira (ESP32 + roteador).
- **LoRa / LoRaWAN (915 MHz, plano AU915 no Brasil)**: alcance de quilômetros e baixo consumo, ideal
  para pedreiras e minas a céu aberto. A placa **LilyGO T-Beam** já junta ESP32 + LoRa + GPS + suporte
  de bateria. Com um gateway LoRaWAN e o **ChirpStack** (servidor LoRaWAN de código aberto), as
  mensagens chegam via MQTT; um fluxo no **Node-RED** pode repassá-las para `expro/capacetes/<ID>/posicao`.
  Atenção: no LoRaWAN classe A o capacete só recebe mensagens logo depois de enviar; para receber os
  alertas na hora, use dispositivos **classe C**.

O esboço de firmware está em [`firmware/capacete_esp32/capacete_esp32.ino`](../firmware/capacete_esp32/capacete_esp32.ino)
(ESP32 + GPS + Wi-Fi/MQTT, com bipe, vibração e LED por nível de alerta). Ele foi verificado só quanto à
compilação das bibliotecas; teste no hardware antes de usar.

### Dicas importantes

- **Margem de erro**: some o erro do localizador ao raio de risco (ex.: GPS comum, +5 m).
- **Frequência de envio**: 1 a 2 s (Wi-Fi/UWB) ou 5 a 10 s (LoRa). Ajuste `timeout_sinal_s` para cerca de
  3 vezes esse intervalo.
- **Fail-safe já pronto**: capacete sem sinal conta como pessoa na área e bloqueia a detonação. Cadastre os
  capacetes do turno em `capacetes_cadastrados`; no fim do turno, o Técnico dá baixa (`baixa CAP-01`).
- **Quem está sem capacete não aparece.** Combine com controle de acesso na entrada da área (catraca/RFID),
  câmera com detecção de pessoas ou varredura com drone antes do fogo.
- **Não fure o capacete**: isso compromete o Certificado de Aprovação (CA) do EPI. Prenda o módulo com
  presilha no suporte da lanterna/jugular ou leve-o no colete.
- **Rádio perto de detonadores elétricos**: transmissores de rádio (inclusive os dos capacetes) podem induzir
  corrente em detonadores elétricos. Consulte o fabricante dos explosivos sobre distâncias mínimas de
  transmissores e prefira sistemas de iniciação não elétricos ou eletrônicos imunes a RF.
- **Energia**: bateria 18650 com módulo carregador (ou power bank); envie o nível da bateria junto da posição.
- **Robustez**: caixa vedada (IP65 ou melhor) contra poeira e chuva.

---

## 2. Sistemas de áudio

Os três níveis podem sair por vários meios ao mesmo tempo (`audio = ["console", "local", "mqtt"]`).

**a) Central de som / sirenes já existentes no canteiro**
Ligue a saída de áudio (P2) do Raspberry Pi ou do notebook na entrada auxiliar (AUX/LINE) do amplificador
das cornetas. Use `audio = ["local"]` e grave as mensagens em `audios/nivel3.wav`, `nivel2.wav` e `nivel1.wav`
(sem esses arquivos, o sistema toca uma sirene diferente para cada nível).

**b) Rádios comunicadores (VHF/UHF/DMR), muito usados em mineração e obras**
Um rádio base ligado à central transmite o alerta para todos os rádios do canal: áudio do Pi → entrada
de microfone do rádio (cabo de interface) e um relé ou optoacoplador fecha o PTT enquanto o alerta toca.
Use o canal licenciado (Anatel) que a empresa já tem. Muitos rádios cortam transmissões longas (*time-out
timer*); para o Nível 1, transmita em ciclos. Exemplo de adaptador:

```python
from gpiozero import OutputDevice
from expro.adaptadores.audio_local import AudioLocal

class AudioRadio(AudioLocal):
    """Rádio base: fecha o PTT pelo relé enquanto o alerta toca.

    Grave os arquivos com ~0,5 s de silêncio no início: o rádio leva um instante para transmitir.
    """

    def __init__(self, pino_ptt=22, pasta="audios"):
        super().__init__(pasta)
        self.ptt = OutputDevice(pino_ptt, initial_value=False)

    def tocar(self, alerta):
        super().tocar(alerta)  # encerra o áudio anterior (chamando parar) e começa o novo
        self.ptt.on()

    def parar(self):
        super().parar()
        self.ptt.off()
```

**c) Sonorização IP (alto-falantes de rede)**
Um pequeno serviço assina `expro/alerta` e toca o arquivo do nível nos alto-falantes IP (via SIP/multicast
ou pela API do fabricante).

**d) No próprio capacete**
Buzzer + motor de vibração + LED (já no firmware). Para voz, um módulo **DFPlayer Mini** com alto-falante
pequeno toca as mensagens gravadas num cartão microSD. Em locais ruidosos o trabalhador usa protetor
auricular, por isso **vibração e luz são essenciais**; existem abafadores com rádio integrado e fones de
condução óssea.

**Mensagens de voz**: gravar com voz humana clara costuma ser mais compreensível; também dá para gerar com
TTS (o Colab usa gTTS; offline, o Piper TTS roda no Raspberry Pi). Antes de cada turno, rode o comando
`teste` (modo de teste do RF-03, Níveis 3, 2 e 1) e confira se o som chega a todo o raio.

---

## 3. Trava da detonação e botão de emergência

- **Relé no GPIO 17**: contato normalmente aberto em série com o circuito de habilitação (chave) do
  equipamento de disparo. Relé desligado = bloqueado. Se a central travar ou ficar sem energia, a
  detonação continua impedida.
- **Na feira**: o relé deve acender uma lâmpada ou LED "DETONAÇÃO LIBERADA". Nunca use explosivos ou
  bombinhas na demonstração.
- **No uso real**: a ligação com o equipamento de disparo deve ser projetada com o fornecedor dos
  explosivos e profissional habilitado. Explosivos são produtos controlados pelo Exército. O EXPRO é uma
  camada extra de proteção e não substitui o blaster, o plano de fogo nem os procedimentos da NR-19.
- **Botão de emergência** (GPIO 27): botão tipo cogumelo com contato **normalmente fechado**. Apertar o
  botão ou romper o fio dispara o Nível 1. Botões nos capacetes podem publicar em `expro/emergencia`.

---

## 4. Montando a central (Raspberry Pi)

```bash
sudo apt install mosquitto mosquitto-clients
git clone https://github.com/Gustavo-HVF/rns19.git && cd rns19
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[mqtt,raspberry]"
cp config/exemplo_hardware_real.toml config/meu_canteiro.toml   # edite pinos, IP, raios e usuários
python -m expro hash-pin                                         # gera o pin_sha256 de cada usuário
python -m expro --config config/meu_canteiro.toml
```

O Mosquitto 2.x só aceita conexões locais por padrão. Para os capacetes se conectarem, crie
`/etc/mosquitto/conf.d/expro.conf` com `listener 1883` e, no protótipo, `allow_anonymous true`
(em uso real, configure usuário e senha).

Testando sem nenhum capacete, de outro terminal:

```bash
mosquitto_sub -t expro/alerta -v                                       # "ouve" os alertas
mosquitto_pub -t expro/capacetes/CAP-01/posicao -m '{"x": 30, "y": 10}' # alguém dentro do raio
mosquitto_pub -t expro/emergencia -m 1                                 # botão de emergência
```

---

## 5. Lista de materiais (protótipo)

| Item | Quantidade | Uso |
|---|---|---|
| Raspberry Pi 4 ou 5 (ou um notebook) | 1 | central EXPRO + broker MQTT |
| Módulo relé 5 V optoacoplado | 1 | trava (acende a lâmpada "liberada" na feira) |
| Botão de emergência tipo cogumelo, contato NF | 1 | RN-03 |
| Caixa de som com entrada P2 | 1 | alertas sonoros |
| ESP32 DevKit ou LilyGO T-Beam | 1 por capacete | localizador |
| Módulo GPS NEO-6M / NEO-M8N (dispensável com T-Beam) | 1 por capacete | posição |
| Buzzer, motor de vibração + transistor, LED | 1 por capacete | sinalização no capacete |
| Bateria 18650 + carregador (ou power bank) | 1 por capacete | energia |
| Roteador Wi-Fi (feira) ou gateway LoRaWAN (campo) | 1 | comunicação |

## 6. Roteiro de evolução sugerido

1. **Feira**: painel com dados fictícios + um capacete ESP32 real que bipa e vibra quando a central toca
   um alerta, e o relé acendendo a lâmpada "DETONAÇÃO LIBERADA".
2. **Pátio da escola**: GPS em 2 ou 3 capacetes, raio pequeno (ex.: 20 m), testes de bloqueio e de
   capacete sem sinal.
3. **Campo, com empresa parceira**: LoRaWAN ou UWB, integração com o som e os rádios existentes, testes de
   cobertura e validação com o Técnico de Segurança.
