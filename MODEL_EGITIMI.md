# Model eğitimi: normal / dengesiz sınıflandırma

Bu klasör eğitim verisini ve model eğitimi için gereken bilgileri içerir. Modeli sen (ya da model sohbetindeki Claude Code) eğitecek, bu dosya yol haritasıdır.

## 1. Kapsam (önce bunu oku)

- **İkili sınıflandırma:** `normal` / `dengesiz` (rotor dengesizliği). Gevşek montaj verisi toplanmadı, kapsam dışı.
  Raporda "kapsam daraltıldı, gevşek sınıfı için veri toplanmadı" diye yaz. "Gevşek ayrışmadı" demek doğru olmaz.
- Sistem **kestirimci bakım değil**, mevcut titreşimden durum sınıflandırması yapar. Kalan ömür tahmini yok.
- **Tüm veri gerçek ölçümdür** (STM32F407 + GY-521 ivmeölçer + gerçek DC motor). Sentetik veri yok.
  Sentetik veri üretilirse dosya adında `synthetic` olmalı, `data/synthetic/` altında ayrı tutulmalı ve gerçekle karıştırılmamalı.

## 2. Veri

Klasör: `data/raw/`. Hangi dosyaların kullanılacağı `data/raw/kayitlar.csv` içinde (`kullanim = egitim_test`).

| Dosya | Motor | Durum | Pencere | rms_mag (ort ± std) |
|---|---|---|---|---|
| `pencere_normal_mA_r8_20261021_125011.csv` | A | normal | 59 | 248 mg ± 6 |
| `pencere_dengesiz_mA_r2_20261021_113139.csv` | A | dengesiz | 59 | 1443 mg ± 17 |
| `pencere_normal_mB_r4_20261021_120759.csv` | B | normal | 58 | 264 mg ± 23 |
| `pencere_dengesiz_mB_r7_20261021_124225.csv` | B | dengesiz | 59 | 1556 mg ± 4 |

**Sütunlar** (her satır = 1024 örneklik bir pencere, 1 kHz örnekleme, ≈ 1,03 s, ivme aralığı ±4 g):
`zaman, epoch_s, etiket, run, seq, rms_x_ug, rms_y_ug, rms_z_ug, rms_mag_ug, peak_ug, crest_x1000, overrun, i2c_err, gecerli, motor`

- RMS ve peak değerleri **µg** cinsinden, her pencerede ortalama (yerçekimi/ofset) çıkarılmış.
- `rms_mag_ug` üç eksenin bileşke RMS'i, `peak_ug` ofsetsiz bileşke vektörün en büyük değeri.
- `crest_x1000` = peak / rms_mag × 1000 (tam sayı).
- `gecerli = 1` pencerede örnek kaybı ve I2C hatası yok demek. Dört dosyada da hepsi 1.

**Veri kuralları**
- Sadece `kayitlar.csv` içinde `kullanim = egitim_test` olan dosyaları kullan.
- `seq` değerine göre tekrar eden satırları sil (`drop_duplicates`). Bu dört dosyada tekrar yok, ama kural güvenlik için.
- Sadece `gecerli == 1` satırlar.
- Bir çalıştırmanın (aynı dosyanın) pencerelerini hem eğitime hem teste koyma. Aynı koşuldan gelen pencereler birbirine çok benzer, yani 59 pencere = 59 bağımsız örnek değil.
- Eski ±2 g dosyalarını ve `haric` işaretli dosyaları kullanma.

## 3. Sınırlılıklar (rapora yaz)

- **Yalnızca iki motor**, tek sensör konumu, tek tip ve **güçlü** dengesizlik (bant ile oluşturuldu). Sonuçlar hafif arızayı ayırt edebildiğimizi göstermez.
- Her motor/durum için **tek bir çalıştırma** (60 s). Bağımsız örnek sayısı 4.
- İvme değerleri kalibre edilmedi (bileşke ≈ 1,04 g).
- `normal_mB_r4` dosyasının motor kimliği **kayıt notuna dayanıyor** (kayıt sırasında `--motor` etiketi yoktu).
- Eksen bazlı RMS değerleri aynı motorda yeniden montajda bile çok oynadı (örn. motor A `rms_z` 97–150 mg), motorlar arasında da farklı. Bu yüzden `rms_mag` ve `crest` öne çıkıyor.

## 4. Önerilen adımlar

1. Kurulum (PowerShell): `py -m pip install pandas scikit-learn matplotlib`
2. Veriyi yükle, `kayitlar.csv`'ye göre dört dosyayı birleştir. Her satıra `motor`, `etiket` var zaten.
3. **Dağılımı çiz:** `rms_mag_ug` ve `crest_x1000` için çalıştırma başına kutu grafiği (PNG). Ayrımın ne kadar büyük olduğunu görmek için.
4. **Baseline:** tek eşikli kural, yalnızca `rms_mag_ug` (örneğin `DecisionTreeClassifier(max_depth=1)`).
5. **Karar ağacı:** `DecisionTreeClassifier(max_depth=2 veya 3)`. Şu öznitelik kümelerini kıyasla:
   `[rms_mag]`, `[rms_mag, crest]`, `[rms_x, rms_y, rms_z]`, `[hepsi]`.
6. **Dört test düzeni** (aynı dört dosya, motor temelli ayrım):

   | Test | Eğitim | Test |
   |---|---|---|
   | T1 | A normal + A dengesiz | B normal + B dengesiz |
   | T2 | B normal + B dengesiz | A normal + A dengesiz |
   | T3 (çapraz) | A dengesiz + B normal | A normal + B dengesiz |
   | T4 (ters çapraz) | A normal + B dengesiz | A dengesiz + B normal |

   T3 ve T4, modelin motor kimliğini mi yoksa dengesizliği mi öğrendiğini gösterir. Eksen bazlı öznitelikler burada kötü sonuç verirse bunu açıkça raporla.
7. **Çıktılar:** her test için doğruluk, karışıklık matrisi (PNG), öznitelik önemleri. Sonuçları `models/` altına kaydet.
8. **STM32 için kural:** seçtiğin ağacı `sklearn.tree.export_text` ile çıkar, **tam sayı** if-else C fonksiyonuna çevir.
   Firmware zaten `rms_mag` değerini µg, `crest` değerini ×1000 tam sayı olarak hesaplıyor, eşikleri aynı birimde yaz.
   Önerilen: `classify(int32_t rms_mag_ug, int32_t crest_x1000)` fonksiyonu 0 = normal, 1 = dengesiz döndürsün. Son 5 tahminin çoğunluk oylaması firmware'de yapılsın. Yeşil LED (PD12) normal, turuncu LED (PD13) dengesiz.
9. Sunum için: modeli bir motorla eğitip **diğer motorda** canlı göster (eğitimde kullanılmamış motor).

## 5. Beklenti ve dikkat

- Ayrım çok büyük: normal pencerelerde `rms_mag` en çok ≈ 312 mg, dengesizde en az ≈ 1364 mg. Tek bir `rms_mag` eşiği bile bu veriyi neredeyse kesin ayırır, doğruluğun %100'e yakın çıkması şaşırtıcı olmamalı.
  Bunu abartma, "güçlü dengesizliği iki motorda ayırdık" olarak yaz. Karmaşık model gerekmediğini de söyleyebilirsin.
- Sonuç "motor arızasını tespit etti" gibi genel bir iddia değildir. İki motor, bir sensör konumu, bir arıza tipiyle sınırlıdır.
- Önemli promptları ve kararları `docs/ai-log/` altına Markdown olarak kaydet (hangi kodu AI önerdi, ne değiştirdin, nasıl doğruladın). Ödev kuralı: geliştirirken AI kullanmak yeterli.

## 6. Model sohbetine yapıştırılacak prompt

```
STM32F407 + GY-521 ile toplanmış gerçek titreşim verisiyle normal / dengesiz ikili sınıflandırma yapıyoruz.
MODEL_EGITIMI.md dosyasını baştan sona oku, orada kapsam, veri, sınırlılıklar ve adımlar yazıyor.
Veri data/raw altında, kayitlar.csv'de kullanim=egitim_test olanları kullan.
Kodu tools/train.py olarak yaz: veriyi yükle, seq'e göre tekrarları at, gecerli==1 filtrele, dağılım grafiği,
baseline (tek eşik rms_mag), karar ağacı (max_depth 2-3), T1-T4 testleri, karışıklık matrisleri PNG, models/ altına kaydet.
Sonra kuralı STM32 için tam sayı if-else C fonksiyonuna çevir (tools/export_c.py).
Sonuçları abartma, sınırlılıkları açıkça yaz. Her adımdan sonra ne çalıştırıp ne beklediğimi söyle.
```
