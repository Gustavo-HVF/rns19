// PROJETO EXPRO — firmware do capacete (ESP32) — ESBOÇO PARA PROTÓTIPO
//
// Envia a posição (GPS) para a central e sinaliza os alertas com bipe, vibração e LED.
// Placas sugeridas: ESP32 DevKit + módulo GPS (NEO-6M/NEO-M8N) ou LilyGO T-Beam (ESP32 + GPS + LoRa).
// Bibliotecas (Gerenciador de Bibliotecas da IDE Arduino): PubSubClient, TinyGPSPlus, ArduinoJson (v7).
//
// Tópicos MQTT (os mesmos de expro/adaptadores/mqtt.py):
//   publica  expro/capacetes/<ID>/posicao  {"lat": -16.68, "lon": -49.26, "bateria": 87}
//   assina   expro/alerta                  {"nivel": 1|2|3}  ou  {"nivel": 0} (silêncio)
//
// Esboço não testado em hardware: confira pinos e bibliotecas antes de usar.

#include <WiFi.h>
#include <PubSubClient.h>
#include <TinyGPSPlus.h>
#include <ArduinoJson.h>

// ---------------- configure aqui ----------------
const char* WIFI_SSID = "EXPRO";
const char* WIFI_SENHA = "troque-a-senha";
const char* MQTT_HOST = "192.168.0.10";  // IP do Raspberry Pi (central)
const uint16_t MQTT_PORTA = 1883;
const char* ID_CAPACETE = "CAP-01";

const int PINO_BUZZER = 25;
const int PINO_VIBRACAO = 26;  // motor de vibração via transistor
const int PINO_LED = 2;
const int PINO_GPS_RX = 16;    // RX do ESP32 <- TX do GPS
const int PINO_GPS_TX = 17;
const unsigned long INTERVALO_ENVIO_MS = 2000;
// ------------------------------------------------

TinyGPSPlus gps;
HardwareSerial serialGps(2);
WiFiClient wifi;
PubSubClient mqtt(wifi);

int nivelAtual = 0;
unsigned long ultimoEnvio = 0;
unsigned long ultimaTentativa = 0;
char topicoPosicao[64];

void aoReceberAlerta(char*, byte* payload, unsigned int tamanho) {
  JsonDocument doc;
  if (deserializeJson(doc, payload, tamanho)) return;
  nivelAtual = doc["nivel"] | 0;
}

void conectar() {
  if (WiFi.status() != WL_CONNECTED || mqtt.connected()) return;
  if (millis() - ultimaTentativa < 3000) return;  // não trava o loop tentando reconectar
  ultimaTentativa = millis();
  if (mqtt.connect(ID_CAPACETE)) {
    mqtt.subscribe("expro/alerta", 1);
  }
}

void enviarPosicao() {
  if (millis() - ultimoEnvio < INTERVALO_ENVIO_MS) return;
  if (!gps.location.isValid() || gps.location.age() > 3000) return;  // sem posição confiável: não envia
  ultimoEnvio = millis();
  JsonDocument doc;
  doc["lat"] = gps.location.lat();
  doc["lon"] = gps.location.lng();
  doc["bateria"] = 100;  // substitua pela leitura real do divisor de tensão da bateria
  char texto[128];
  size_t n = serializeJson(doc, texto);
  mqtt.publish(topicoPosicao, (const uint8_t*)texto, n, false);
}

// Padrões por nível: Nível 3 = bipe curto a cada 2 s; Nível 2 = bipes rápidos; Nível 1 = sirene contínua.
void sinalizar() {
  unsigned long t = millis();
  bool ligado = false;
  int frequencia = 0;
  switch (nivelAtual) {
    case 3: ligado = (t % 2000) < 200; frequencia = 880; break;
    case 2: ligado = (t % 500) < 250; frequencia = ((t / 500) % 2) ? 960 : 720; break;
    case 1: ligado = true; frequencia = 600 + (t % 1600 < 800 ? t % 800 : 800 - t % 800) / 50 * 50; break;
    default: break;
  }
  static int frequenciaAtual = -1;  // só reconfigura o buzzer quando o som muda
  int desejada = ligado ? frequencia : 0;
  if (desejada != frequenciaAtual) {
    if (desejada > 0) tone(PINO_BUZZER, desejada); else noTone(PINO_BUZZER);
    frequenciaAtual = desejada;
  }
  digitalWrite(PINO_VIBRACAO, ligado ? HIGH : LOW);

  bool conectado = mqtt.connected();
  bool led = nivelAtual > 0 ? ligado : (conectado ? (t % 3000) < 50 : (t % 400) < 200);
  digitalWrite(PINO_LED, led ? HIGH : LOW);  // piscar rápido = sem conexão com a central
}

void setup() {
  pinMode(PINO_BUZZER, OUTPUT);
  pinMode(PINO_VIBRACAO, OUTPUT);
  pinMode(PINO_LED, OUTPUT);
  serialGps.begin(9600, SERIAL_8N1, PINO_GPS_RX, PINO_GPS_TX);
  snprintf(topicoPosicao, sizeof(topicoPosicao), "expro/capacetes/%s/posicao", ID_CAPACETE);
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_SENHA);
  mqtt.setServer(MQTT_HOST, MQTT_PORTA);
  mqtt.setCallback(aoReceberAlerta);
}

void loop() {
  while (serialGps.available()) gps.encode(serialGps.read());
  conectar();
  mqtt.loop();
  if (mqtt.connected()) enviarPosicao();
  sinalizar();
}
