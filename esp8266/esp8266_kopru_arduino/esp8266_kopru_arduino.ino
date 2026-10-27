/*
 * ESP8266 (NodeMCU) koprusu: STM32F407 -> UART -> ESP8266 -> Wi-Fi -> MQTT
 *
 * STM32 tarafi DEGISMEZ. STM32 her pencere (~1,03 s) icin iki satir gonderir (115200, 8N1, PA2):
 *   W,seq,rms_x,rms_y,rms_z,rms_mag,peak,crest_x1000,ov,err      (ivme degerleri mikro-g)
 *   C,seq,tahmin,durum                                          (tahmin: pencerenin ham sinifi, durum: 5'li oy)
 * Sinif kodlari: -1 belirsiz/gecersiz, 0 normal, 1 orta bozuk (2 karton), 2 cok bozuk (somun).
 *
 * Baglanti (yalnizca tek yon):  STM32 PA2 (TX) -> NodeMCU D5,  STM32 GND -- NodeMCU GND
 * NodeMCU'da RST-GND jumper'i TAKILI OLMAMALI (o, USB-UART kopru moduydu).
 * NodeMCU kendi USB'sinden beslenir. STM32'nin 3V pininden beslenmez, pinlere 5 V verilmez.
 */
#include <Arduino.h>
#include <ESP8266WiFi.h>
#include <PubSubClient.h>
#include <SoftwareSerial.h>
#include "secrets.h"   // WIFI_SSID ve WIFI_PASSWORD burada (GitHub'a gonderilmez)

static const uint32_t STM_BAUD = 115200;   // STM32 USART2 ile ayni olmali

SoftwareSerial stmSerial(D5, -1);          // yalnizca RX: STM32 PA2 -> D5

WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);

static const char *MQTT_HOST = "broker.emqx.io";
static const uint16_t MQTT_PORT = 1883;
static const char *TOPIC_TELEMETRY = "akbaselif/motor-f407-a91c7e/telemetry";
static const char *TOPIC_STATUS    = "akbaselif/motor-f407-a91c7e/status";

/* Son gelen W satiri; ayni seq'li C satiri gelince birlikte yayinlanir */
struct Pencere {
  bool dolu;
  unsigned long seq;
  long rx, ry, rz, rm, peak, crest;
  unsigned long ov, err;
};
Pencere sonW = {false, 0, 0, 0, 0, 0, 0, 0, 0, 0};

char satir[128];
size_t satirLen = 0;

unsigned long sayYayin = 0, sayBozukSatir = 0, sayEslesmeyen = 0;
unsigned long sonWifiDeneme = 0, sonMqttDeneme = 0, sonDurumYayin = 0;

const char *durumAdi(int d)
{
  switch (d) {
    case 0:  return "normal";
    case 1:  return "orta_bozuk";
    case 2:  return "cok_bozuk";
    default: return "belirsiz";
  }
}

void wifiBaslat()
{
  Serial.print("Wi-Fi baglaniliyor: ");
  Serial.println(WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

void wifiKoru()
{
  if (WiFi.status() == WL_CONNECTED) return;
  unsigned long simdi = millis();
  if (simdi - sonWifiDeneme >= 10000) {
    sonWifiDeneme = simdi;
    Serial.println("Wi-Fi yok, yeniden deneniyor...");
    WiFi.disconnect();
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  }
}

void mqttKoru()
{
  if (WiFi.status() != WL_CONNECTED) return;
  if (mqtt.connected()) { mqtt.loop(); return; }

  unsigned long simdi = millis();
  if (simdi - sonMqttDeneme < 5000) return;
  sonMqttDeneme = simdi;

  String kimlik = "motor-f407-" + String(ESP.getChipId(), HEX);
  Serial.print("MQTT baglantisi deneniyor... ");
  // son vasiyet (LWT): baglanti koparsa broker "offline" yayinlar
  if (mqtt.connect(kimlik.c_str(), TOPIC_STATUS, 0, true, "offline")) {
    Serial.println("BAGLANDI");
    mqtt.publish(TOPIC_STATUS, "online", true);
  } else {
    Serial.print("BASARISIZ, kod=");
    Serial.println(mqtt.state());
  }
}

void yayinla(const Pencere &w, int tahmin, int durum)
{
  const char *ad = durumAdi(durum);
  if (w.ov > 0 || w.err > 0) ad = "olcum_hatasi";

  char json[320];
  snprintf(json, sizeof(json),
           "{\"seq\":%lu,\"rms_x_ug\":%ld,\"rms_y_ug\":%ld,\"rms_z_ug\":%ld,"
           "\"rms_mag_ug\":%ld,\"peak_ug\":%ld,\"crest\":%.3f,\"ov\":%lu,\"err\":%lu,"
           "\"tahmin\":%d,\"durum_kodu\":%d,\"durum\":\"%s\",\"uptime_ms\":%lu}",
           w.seq, w.rx, w.ry, w.rz, w.rm, w.peak, w.crest / 1000.0,
           w.ov, w.err, tahmin, durum, ad, millis());

  if (!mqtt.connected()) {
    Serial.println("MQTT bagli degil, pencere atlandi.");
    return;
  }
  bool ok = mqtt.publish(TOPIC_TELEMETRY, json, false);
  if (ok) sayYayin++;
  Serial.print(ok ? "Yayinlandi: " : "Yayin hatasi: ");
  Serial.println(json);
}

void satirIsle(const char *s)
{
  if (s[0] == 'W' && s[1] == ',') {
    Pencere w;
    int n = sscanf(s, "W,%lu,%ld,%ld,%ld,%ld,%ld,%ld,%lu,%lu",
                   &w.seq, &w.rx, &w.ry, &w.rz, &w.rm, &w.peak, &w.crest, &w.ov, &w.err);
    if (n == 9) { w.dolu = true; sonW = w; }
    else sayBozukSatir++;
    return;
  }
  if (s[0] == 'C' && s[1] == ',') {
    unsigned long seq; int tahmin, durum;
    if (sscanf(s, "C,%lu,%d,%d", &seq, &tahmin, &durum) != 3) { sayBozukSatir++; return; }
    if (sonW.dolu && sonW.seq == seq) {
      yayinla(sonW, tahmin, durum);
      sonW.dolu = false;
    } else {
      sayEslesmeyen++;   // W satiri kaybolmus; bu pencere atlanir
    }
    return;
  }
  sayBozukSatir++;
}

void stmOku()
{
  while (stmSerial.available()) {
    char c = (char)stmSerial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      if (satirLen > 0) {
        satir[satirLen] = '\0';
        satirIsle(satir);
        satirLen = 0;
      }
      continue;
    }
    if (satirLen < sizeof(satir) - 1) satir[satirLen++] = c;
    else { satirLen = 0; sayBozukSatir++; }   // cok uzun satir: at
  }
}

void durumYayinla()
{
  unsigned long simdi = millis();
  if (simdi - sonDurumYayin < 10000) return;
  sonDurumYayin = simdi;
  char msg[160];
  snprintf(msg, sizeof(msg),
           "{\"yayin\":%lu,\"bozuk_satir\":%lu,\"eslesmeyen\":%lu,\"wifi_rssi\":%d}",
           sayYayin, sayBozukSatir, sayEslesmeyen, WiFi.RSSI());
  Serial.print("Sayaclar: ");
  Serial.println(msg);
  if (mqtt.connected()) mqtt.publish(TOPIC_STATUS, msg, false);
}

void setup()
{
  Serial.begin(115200);
  stmSerial.begin(STM_BAUD);
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setBufferSize(512);
  mqtt.setKeepAlive(30);
  wifiBaslat();
  Serial.println();
  Serial.println("ESP8266 motor veri koprusu basladi.");
}

void loop()
{
  stmOku();
  wifiKoru();
  mqttKoru();
  stmOku();
  durumYayinla();
  yield();
}
