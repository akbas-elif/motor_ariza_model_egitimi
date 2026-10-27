# Yerel motor titreşim arayüzü

Bu ilk sürüm, mevcut CSV yapısını görselleştirir ve final karar ağacındaki kuralı uygular:

```text
rms_mag_ug <= 838154 -> Normal
rms_mag_ug >  838154 -> Bozuk
```

## Çalıştırma

Depo kökünde:

```powershell
node arayuz\server.mjs
```

Ardından tarayıcıda `http://localhost:8000` adresini açın.

## Kullanım

- **Demo başlat:** Normalden bozuk duruma geçen örnek akışı oynatır.
- **CSV dosyası seç:** `data/raw/` altındaki gerçek pencere CSV dosyalarından birini oynatır.
- **Duraklat / Sıfırla:** Oynatmayı kontrol eder.

Bu sürüm yalnızca tarayıcı içindeki demo/CSV akışını kullanır. STM32 seri port bağlantısı sonraki aşamada eklenecektir.
