# STM32 titreşim izleme: 3 düzey durum sınıflandırma + canlı arayüz

STM32F407 + GY-521 ivmeölçer ile bir DC motorun titreşiminden **normal / orta bozuk / çok bozuk**
durum sınıflandırması. Sınıflandırma kartın üzerinde (edge) çalışır, sonuç LED'de görünür.
ESP8266 sonucu MQTT ile internete yayınlar, `docs/index.html` sayfası canlı gösterir.
Sistem kestirimci bakım yapmaz; mevcut titreşimden **durum sınıflandırması** yapar.

**Tüm veri gerçek ölçümdür** (aynı tip iki motor, tek sensör konumu). Sentetik veri kullanılmadı.

```
GY-521 --I2C--> STM32F407 --UART 115200--> ESP8266 (NodeMCU) --Wi-Fi/MQTT--> broker.emqx.io --WSS--> docs/index.html
                 (pencere, rms, sınıf, LED)
```

## Klasörler

| Yol | İçerik |
|---|---|
| `firmware/main.c` | STM32CubeIDE projesinin `Core/Src/main.c` dosyası (kartta çalışan sürüm) |
| `esp8266/esp8266_kopru_arduino/` | NodeMCU kodu (Arduino IDE). `secrets.example.h` → `secrets.h` olarak kopyalanıp Wi-Fi bilgisi yazılır |
| `docs/index.html` | Canlı izleme arayüzü (GitHub Pages ile yayınlanır) |
| `tools/logger_v2.py` | USB-UART köprüsüyle pencere kaydı (`data_v2/raw/` + `data_v2/kayit_defteri.csv`) |
| `tools/train.py` | Eğitim ve test (montaj dışarıda bırakılarak), `sonuclar_v2/` çıktıları |
| `data_v2/` | Ham pencere kayıtları, kayıt defteri, atılan kayıtların defteri (nedenleriyle) |
| `sonuclar_v2/` | `egitim_raporu.md`, `model.json`, karışıklık matrisleri, grafikler |
| `docs/ai-log/` | Geliştirmede AI kullanımı: istekler, kararlar, doğrulama |
| `v1_eski_pilot/` | İlk deneme (21 Ekim, farklı motorlar A/B, normal/dengesiz). Arşiv, güncel model değil |

## Model (v2)

| Sınıf | Logger etiketi | Mildeki ağırlık | rms_mag (kayıt ort.) | LED |
|---|---|---|---|---|
| 0 normal | `normal` | yok | 12,9–19,9 mg | yeşil (PD12) |
| 1 orta bozuk | `cok_bozuk` | 2 karton parçası | 23,1–42,6 mg | turuncu (PD13) |
| 2 çok bozuk | `dengesiz` | lehimli somun | 421–499 mg | kırmızı sabit (PD14) |

Tek karton (`bozuk`) kayıtları bu modelde kullanılmadı (veride duruyor).

- Kural (STM32 `classify()`): `rms_mag_ug < 21844` → normal, `< 119839` → orta bozuk, aksi halde çok bozuk.
  Son 5 tahminin ortancası LED'e yansır. Yanıp sönen kırmızı = sensör yok.
- Test (13 kayıt, her seferinde bir montaj dışarıda): pencere doğruluğu 0,92, kayıt kararı 12/13,
  bir motor dışarıda 0,91. Ayrıntı: `sonuclar_v2/egitim_raporu.md`.
- Kartta canlı deneme: iki motorda üç durum LED'de doğru gösterildi (eğitimdeki aynı motorlar).

## Arayüze bağlanma (MQTT)

| | |
|---|---|
| Broker | `broker.emqx.io` (herkese açık test sunucusu; kişisel bilgi gönderilmez) |
| ESP8266 | TCP `1883` |
| Tarayıcı | `wss://broker.emqx.io:8084/mqtt` |
| Telemetri konusu | `akbaselif/motor-f407-a91c7e/telemetry` (pencere başına bir JSON, ~1 s) |
| Durum konusu | `akbaselif/motor-f407-a91c7e/status` (`online` / `offline` retained, 10 s'de bir sayaçlar) |

Telemetri JSON örneği:

```json
{"seq":105,"rms_x_ug":2668,"rms_y_ug":2281,"rms_z_ug":3651,"rms_mag_ug":5065,"peak_ug":14610,
 "crest":2.884,"ov":0,"err":0,"tahmin":0,"durum_kodu":0,"durum":"normal","uptime_ms":123456}
```

- `*_ug`: mikro-g. `rms_mag_ug / 1000` = mg.
- `tahmin`: o pencerenin ham sınıfı; `durum_kodu`: son 5 pencerenin ortancası (LED ile aynı).
  Kodlar: `-1` belirsiz, `0` normal, `1` orta bozuk, `2` çok bozuk.
- `durum`: `normal`, `orta_bozuk`, `cok_bozuk`, `belirsiz`, `olcum_hatasi` (`ov` veya `err` > 0).

Arayüzü yayınlamak: GitHub'da **Settings → Pages → Branch: `main`, klasör `/docs`** → Save.
Sayfa birkaç dakika sonra `https://aysenurgeyik.github.io/motor_ariza_model_egitimi/` adresinde açılır.
Yerelde denemek için `docs/index.html` dosyasını tarayıcıda açmak yeterli.

## Bağlantılar

| Bağlantı | Pinler |
|---|---|
| GY-521 → STM32 | VCC→3V, GND→GND, SCL→PB6, SDA→PB9 (I2C1, 400 kHz, ±4 g) |
| STM32 → NodeMCU (Wi-Fi modu) | PA2 (USART2 TX) → D5, GND ↔ GND. RST–GND jumper'ı **takılı değil** |
| STM32 → NodeMCU (veri toplama, USB köprü) | PA2 → TX, GND ↔ GND, RST–GND **takılı**; `tools/logger_v2.py` |

NodeMCU kendi USB'sinden beslenir. Motor ayrı güç modülünden beslenir.

## Çalıştırma (Windows)

```
py -m pip install -r requirements.txt
py tools/train.py
py tools/logger_v2.py --motor 1A --durum normal --volt 5 --olculen_volt 4.8 --montaj 1 --run 1 --sure 60
```

## Sınırlılıklar

- Aynı tip yalnızca 2 motor (tek tip motor üzerinde demo), tek sensör konumu; bağımsız örnek sayısı 13 kayıt.
- Çok bozuk (somun) sınıfında motor başına yalnızca 1 kayıt var; iki somun denemesi motor kayıt sırasında durduğu için atıldı.
- Ağırlıklar el yapımı (karton, lehimli somun), kütleleri tartılmadı. 1A'da aynı ağırlıkla kayıtlar arası fark büyük.
- Somunlu kayıtlarda titreşim kayıt boyunca yükseliyor (%23–34); tutuldu ve raporda not edildi.
- Eşikler aynı veriden seçildi; **görülmemiş motorla kör test yapılmadı**. Sonuç bu düzenek için geçerlidir.
- Normal ile orta bozuk sınırı dar (en yüksek normal pencere 21,4 mg, eşik 21,8 mg).
