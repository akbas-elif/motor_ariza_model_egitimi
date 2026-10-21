# STM32 titreşim izleme: normal / dengesiz sınıflandırma

STM32F407 + GY-521 ivmeölçer ile bir DC motorun titreşiminden **normal** / **dengesiz** (rotor dengesizliği)
durum sınıflandırması. Sınıflandırma kartın üzerinde (edge) çalışır, sonuç LED'de görünür.
Sistem kestirimci bakım yapmaz; mevcut titreşimden durum sınıflandırması yapar.

**Tüm veri gerçek ölçümdür** (iki motor, tek sensör konumu). Sentetik veri kullanılmadı.

## Klasörler

| Yol | İçerik |
|---|---|
| `MODEL_EGITIMI.md` | Kapsam, veri kuralları, sınırlılıklar, test düzeni (T1–T4) |
| `data/raw/` | Pencere özetleri (1024 örnek, 1 kHz, ±4 g). Kullanılan dosyalar `kayitlar.csv` içinde `kullanim = egitim_test` |
| `tools/train.py` | Veri yükleme, dağılım grafikleri, baseline, karar ağaçları, T1–T4 testleri, final model |
| `tools/export_c.py` | Final ağacı tam sayı if-else C fonksiyonuna çevirir ve tam sayı mantığını sklearn ile karşılaştırır |
| `models/` | Sonuçlar: `sonuc_raporu.md`, doğruluk tablosu, karışıklık matrisleri, dağılım grafikleri |
| `firmware/main.c` | STM32CubeIDE projesinin `Core/Src/main.c` dosyası (sınıflandırma + 5'li çoğunluk oylaması + LED + UART) |
| `firmware/snippets/` | Aynı değişikliklerin USER CODE bloklarına göre parçaları ve üretilen `classify.c` |
| `docs/ai-log/` | Geliştirmede AI kullanımı: istekler, kararlar, doğrulama |

## Çalıştırma (Windows)

```
py -m pip install -r requirements.txt
py tools/train.py
py tools/export_c.py
```

## Sonuç (özet)

- Final kural: `rms_mag_ug <= 838154` → normal, aksi halde dengesiz (≈ 838 mg).
- `rms_mag` tek eşikle T1–T4 testlerinin dördünde de test pencerelerinin tamamını doğru sınıflandırdı.
  `crest` öznitelikli ağaç bazı testlerde hata yaptı (sınıflar arası boşluk çok dar), kurala konmadı.
- Kartta canlı test (tek motor): kapalı ≈ 5 mg → normal, bantsız ≈ 94 mg → normal, bantlı ≈ 1277 mg → dengesiz.

## Sınırlılıklar

- Bağımsız örnek sayısı 4'tür (dört çalıştırma), pencere sayısı değil.
- Sınıf farkı çok büyüktür; %100'e yakın doğruluk beklenen bir sonuçtur.
- T3/T4'te her sınıfın eğitim örnekleri tek motordan gelir; zayıf kanıttır.
- İki motor, tek sensör konumu, tek tip güçlü dengesizlik. Genel bir "motor arızası tespiti" iddiası değildir.
- Canlı testte değerler eğitim aralığının altında ölçüldü; sınıflandırma doğru çıktı ama ayrım payı daha dar.
- Ayrıntı: `models/sonuc_raporu.md` ve `MODEL_EGITIMI.md`.
