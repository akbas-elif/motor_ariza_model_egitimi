# AI kaydı — 2026-10-27 — v2 veri toplama, 3 düzey model, ESP8266 + arayüz

**Araç:** Claude (Claude Code tabanlı oturum)

## İstekler
- Eski veriyi bırakıp tip 1 motorlarla (1A, 1B) sistemli veri toplama (`tools/logger_v2.py`, kayıt defteri).
- Montajı değiştirerek, motorları sırayla çalıştırarak kayıt alma; ardından model eğitimi.
- 3 düzey sınıflandırma, STM32 kodu, ESP8266 MQTT köprüsü ve canlı arayüz.

## Kararlar (kim, neden)
- AI önerisi: kayıt öncesi 60 s bekleme; kayıt içinde ilk 10 / son 10 pencere farkı > %15 ise uyarı (önceden konan kural).
- AI önerisi: eğitimde/testte aynı kaydın pencereleri hem eğitime hem teste konmaz; test bir montajı (ve ayrıca bir motoru) dışarıda bırakarak yapılır.
- Kullanıcı kararı: hatalı kayıtlar silinmeden `data_v2/atilan` klasörüne taşındı; satırları `kayit_defteri_atilan.csv` içinde nedenleriyle duruyor
  (kayma, motorun kayıt sırasında durması, karton sabitlemesindeki tutarsızlık).
- AI uyarısı: sonucu beğenilmeyen kayıtları atmak veri seçme yanlılığı olur; yalnızca somut hata/önceden konan kural ile atma yapıldı.
- Kullanıcı kararı: düzeyler normal / orta bozuk (2 karton) / çok bozuk (lehimli somun); tek karton kayıtları modele katılmadı.
- Kullanıcı kararı: somun için motor başına 1 kayıt yeterli görüldü (sınıf farkı ~10 kat). Sınırlılık olarak raporlandı.
- AI önerisi: eşikler sınıflar arası boşluğun geometrik ortasına yerleştirildi; STM32'de son 5 tahminin ortancası (sıralı sınıflar).
- AI önerisi: STM32 koduna dokunmadan ESP8266 mevcut `W`/`C` satırlarını eşleştirip JSON yayınlıyor.

## Doğrulama
- `tools/train.py`: montaj dışarıda pencere doğruluğu 0,92, kayıt kararı 12/13, motor dışarıda 0,91.
- STM32: `classify()` ve oylama fonksiyonları masaüstünde ayrı derlenip test edildi; kullanıcı kartta derleyip iki motorda üç durumu LED'de doğruladı.
- Derleme hatası (78 hata): `main.c` içeriği yanlışlıkla `usbh_core.c` dosyasına yapıştırılmıştı. Orijinal dosya
  STM32Cube FW_F4 V1.28.3'ten alındı (diğer USB dosyaları birebir karşılaştırıldı), sorun giderildi.
- ESP8266: kullanıcı Arduino IDE ile yükledi; seri monitörde yayın sayacı artıyor, bozuk satır 0, eşleşmeyen 0.
- Arayüz: tarayıcıda sahte test mesajlarıyla görsel olarak denendi; gerçek sunucu bağlantısı kullanıcı tarafında denenecek.
