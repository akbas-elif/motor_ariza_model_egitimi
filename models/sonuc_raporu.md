# Model sonuclari: normal / dengesiz (gercek olcum verisi)

Bu dosya `tools/train.py` tarafindan otomatik uretilir. Sentetik veri kullanilmadi.

## Veri

- Dort calistirma: motor A ve B, her biri normal ve dengesiz (her biri ~60 s, 1024 orneklik pencere, 1 kHz, +-4 g).
- Yalnizca `kayitlar.csv` icinde `kullanim = egitim_test` olan dosyalar kullanildi. Bazi kayitlar +-2 g araligi veya tekrar cekim oldugu icin disarida birakildi.
- `dengesiz_mA_r2` ve `normal_mB_r4` dosyalarinin motor bilgisi kayit sirasindaki `--motor` etiketinden degil, deney notundan gelmektedir.

| calistirma | pencere | rms_mag min / ort / max (mg) | crest min / ort / max |
|---|---|---|---|
| A_normal | 59 | 241.6 / 248.1 / 259.1 | 1.818 / 1.877 / 1.974 |
| B_normal | 58 | 188.4 / 264.5 / 311.8 | 1.534 / 1.935 / 2.303 |
| A_dengesiz | 59 | 1364.5 / 1443.5 / 1473.8 | 1.428 / 1.449 / 1.547 |
| B_dengesiz | 59 | 1545.7 / 1556.1 / 1562.3 | 1.452 / 1.470 / 1.510 |

## Dogruluk (test pencereleri uzerinde)

T1: A ile egit, B'de test. T2: B ile egit, A'da test. T3: A dengesiz + B normal ile egit, A normal + B dengesiz'de test. T4: T3'un tersi.

| yapilandirma | T1 | T2 | T3 | T4 |
|---|---|---|---|---|
| baseline [rms_mag] d1 | 1.000 | 1.000 | 1.000 | 1.000 |
| agac [rms_mag] d2 | 1.000 | 1.000 | 1.000 | 1.000 |
| agac [rms_mag] d3 | 1.000 | 1.000 | 1.000 | 1.000 |
| agac [rms_mag+crest] d2 | 0.983 | 0.992 | 1.000 | 0.983 |
| agac [rms_mag+crest] d3 | 0.983 | 0.992 | 1.000 | 0.983 |
| agac [eksenler] d2 | 1.000 | 1.000 | 1.000 | 1.000 |
| agac [eksenler] d3 | 1.000 | 1.000 | 1.000 | 1.000 |
| agac [hepsi] d2 | 1.000 | 1.000 | 1.000 | 1.000 |
| agac [hepsi] d3 | 1.000 | 1.000 | 1.000 | 1.000 |

Karisiklik matrisi sayilari: `sonuclar.csv`, oznitelik onemleri: `oznitelik_onemleri.csv`.

## Bulgular

- `rms_mag` tek basina, tek esikle dort testte de tum test pencerelerini dogru siniflandirdi.
- `[rms_mag, crest]` agaci T1, T2 ve T4'te bolmeyi crest ile yapti (egitim verisinde iki oznitelik de siniflari tam ayiriyor, esitlik crest lehine bozuldu) ve test pencerelerinde hata yapti. Crest'te siniflar arasi bosluk cok dar (normal en dusuk 1,534, dengesiz en yuksek 1,547), rms_mag'da ise genis (normal en fazla ~312 mg, dengesiz en az ~1364 mg). Bu nedenle crest STM32 kuralina konmadi.
- Eksen bazli oznitelikler de bu veride tum testlerde dogru siniflandirdi. Bu, eksen RMS'lerinin guvenilir oldugunu gostermez: sinif farki cok buyuk ve eksen degerleri yeniden montajda bile belirgin oynadi.

## Final agac (tum veri, [rms_mag], max_depth=1)

Birimler: rms_mag_ug = mikro-g, crest_x1000 = crest factor x 1000.

```
|--- rms_mag_ug <= 838154.50
|   |--- class: 0
|--- rms_mag_ug >  838154.50
|   |--- class: 1
```

## Sinirliliklar

- Bagimsiz ornek sayisi 4'tur (dort calistirma); pencere sayisi (~235) bagimsiz ornek sayisi degildir, ayni calistirmanin pencereleri birbirine cok benzer.
- Sinif farki cok buyuktur (normal pencerelerde rms_mag <= ~312 mg, dengesizde >= ~1364 mg). Bu yuzden %100'e yakin dogruluk beklenen bir sonuctur, karmasik model gerekmez.
- T3/T4'te her sinifin egitim ornekleri tek bir motordan gelir; bu testler modelin motor kimligini degil dengesizligi ogrendigine dair yalnizca zayif bir kanittir.
- Esik (~838 mg) iki sinifin arasindaki genis bosluga duser; bu bosluga dusen bir durum (ornegin hafif dengesizlik) olculmedi, bu durumda kuralin ne yapacagi bilinmiyor.
- Calisma iki motor, tek sensor konumu ve tek tip guclu dengesizlik (bantla olusturuldu) ile sinirlidir. Sonuc genel bir 'motor arizasi tespiti' iddiasi degildir; hafif dengesizligin ayirt edilebildigini gostermez.
- Ivme degerleri kalibre edilmedi (bileske ~1,04 g). Gevsek montaj sinifi icin veri toplanmadi, kapsam ikili siniflandirmaya daraltildi.
- Sistem kestirimci bakim yapmaz; mevcut titresimden durum siniflandirmasi yapar.
