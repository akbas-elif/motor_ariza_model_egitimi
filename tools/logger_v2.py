"""
logger_v2.py - sistemli veri toplama (v2). 4 motor: 1A, 1B (tip 1, silindir), 2A, 2B (tip 2, yassi).

Ornek (motor 1A, normal, 3.3 V ayari, multimetreyle 3.21 V olculdu, 1. montaj, 1. tekrar):
  py logger_v2.py --motor 1A --durum normal --volt 3.3 --olculen_volt 3.21 --montaj 1 --run 1

Her kayit data_v2/raw/ altina otomatik adlandirilmis CSV olarak yazilir ve
data_v2/kayit_defteri.csv dosyasina bir ozet satiri eklenir (el notuna gerek kalmaz).
"""
import argparse
import csv
import os
import statistics
import time
from datetime import datetime

import serial

MOTORLAR = ["1A", "1B", "2A", "2B"]
BEKLENEN_SATIR = 10   # W,seq,rx,ry,rz,rm,peak,crest,ov,err

def ondalik(s):
    """3,21 ve 3.21 yazimlarini ikisini de kabul et (Turkce klavye)."""
    return float(s.replace(",", "."))


ap = argparse.ArgumentParser()
ap.add_argument("--motor", required=True, choices=MOTORLAR)
ap.add_argument("--durum", required=True,
                choices=["normal", "bozuk", "cok_bozuk", "dengesiz"],
                help="normal | bozuk (kucuk agirlik) | cok_bozuk (buyuk agirlik) | "
                     "dengesiz (eski, tek agirlik)")
ap.add_argument("--volt", required=True, type=ondalik, choices=[3.3, 5.0],
                help="regulatorde secilen cikis (3.3 veya 5)")
ap.add_argument("--olculen_volt", required=True, type=ondalik,
                help="motor DONERKEN multimetreyle olculen gercek voltaj")
ap.add_argument("--montaj", required=True, type=int,
                help="montaj numarasi (motor/sensor her sokulup takildiginda artar)")
ap.add_argument("--run", required=True, type=int, help="kayit numarasi")
ap.add_argument("--sure", type=float, default=60, help="saniye (varsayilan 60)")
ap.add_argument("--not", dest="not_", default="", help="serbest not")
ap.add_argument("--port", default="COM7")
ap.add_argument("--baud", type=int, default=115200)
ap.add_argument("--klasor", default="data_v2")
args = ap.parse_args()

tip = args.motor[0]
ham_klasor = os.path.join(args.klasor, "raw")
os.makedirs(ham_klasor, exist_ok=True)
zaman_ek = datetime.now().strftime("%Y%m%d_%H%M%S")
dosya_adi = (f"m{args.motor}_{args.durum}_{args.volt:g}V_"
             f"mt{args.montaj}_r{args.run}_{zaman_ek}.csv")
yol = os.path.join(ham_klasor, dosya_adi)
bozuk_yol = yol.replace(".csv", "_bozuk.txt")
defter_yol = os.path.join(args.klasor, "kayit_defteri.csv")

if abs(args.olculen_volt - args.volt) / args.volt > 0.15:
    print(f"UYARI: olculen voltaj ({args.olculen_volt} V) ayarlanandan "
          f"({args.volt} V) %15'ten fazla sapmis. Motor gucu yetmiyor olabilir; "
          f"degeri dogru yazdigindan emin ol.")

try:
    port = serial.Serial(args.port, args.baud, timeout=1)
except serial.SerialException as e:
    print(f"Port acilamadi: {e}")
    print("Serial Monitor / Tera Term / baska logger acik mi? Port adi dogru mu?")
    raise SystemExit(1)

time.sleep(1.5)            # port acilirken gelen tekrar eden satirlari at
port.reset_input_buffer()

BASLIK = ["zaman", "epoch_s", "motor", "tip", "durum", "volt_set",
          "volt_olculen", "montaj", "run", "seq",
          "rms_x_ug", "rms_y_ug", "rms_z_ug", "rms_mag_ug",
          "peak_ug", "crest_x1000", "overrun", "i2c_err", "gecerli"]

pencereler = []   # (epoch, rms_mag, peak, crest_x1000, gecerli)
gorulen_seq = set()
tekrar_seq = 0
son_seq = None
reset_sayisi = 0
bozuk = 0
bozuk_f = None
baslangic = time.time()


def bozuk_kaydet(satir):
    """Taninmayan satiri say, ilk 2000 tanesini dosyaya yaz."""
    global bozuk, bozuk_f
    bozuk += 1
    if bozuk_f is None:
        bozuk_f = open(bozuk_yol, "w", encoding="utf-8")
    if bozuk <= 2000:
        bozuk_f.write(f"{time.time() - baslangic:7.2f} s\t{satir!r}\n")


print(f"Kayit: {dosya_adi}")
print(f"  motor {args.motor} (tip {tip}) | {args.durum} | {args.volt:g} V ayar, "
      f"{args.olculen_volt} V olculen | montaj {args.montaj} | run {args.run}")
print("Durdurmak icin Ctrl+C")
print("sn   seq   rms_x   rms_y   rms_z  rms_mag   peak  crest  ov err  gecerli")

with open(yol, "w", newline="", encoding="utf-8") as f:
    yaz = csv.writer(f)
    yaz.writerow(BASLIK)
    try:
        while True:
            simdi = time.time()
            if args.sure and simdi - baslangic >= args.sure:
                break

            satir = port.readline()
            ham = satir.decode("utf-8", errors="replace").strip()
            if not ham:
                continue

            parca = ham.split(",")
            if parca[0] == "C" and len(parca) == 4:
                continue    # STM32 siniflandirma satiri (C,seq,tahmin,durum); veri toplamada kullanilmiyor
            if parca[0] != "W" or len(parca) != BEKLENEN_SATIR:
                bozuk_kaydet(satir)
                continue
            try:
                (seq, rx, ry, rz, rm, peak,
                 crest, ov, err) = [int(v) for v in parca[1:]]
            except ValueError:
                bozuk_kaydet(satir)
                continue

            if son_seq is not None and seq < son_seq - 5:
                # sira numarasi geri gitti: kart resetlenmis olabilir (ornegin motor
                # kalkarken voltaj dusmesi). Pencereler yazilir ama kayit KABUL edilmez.
                reset_sayisi += 1
                gorulen_seq.clear()
                print(f"UYARI: seq geri gitti ({son_seq} -> {seq}); kart resetlenmis olabilir.")
            if seq in gorulen_seq:      # ayni pencereyi iki kez yazma
                if time.time() - baslangic > 3:   # ilk 3 sn'deki port-acilis tekrarlari zararsiz
                    tekrar_seq += 1
                continue
            son_seq = seq
            gorulen_seq.add(seq)

            t = time.time()
            zaman = datetime.fromtimestamp(t).strftime("%H:%M:%S.%f")[:-3]
            gecerli = 1 if (ov == 0 and err == 0) else 0
            yaz.writerow([zaman, f"{t:.3f}", args.motor, tip, args.durum,
                          f"{args.volt:g}", args.olculen_volt, args.montaj,
                          args.run, seq, rx, ry, rz, rm, peak, crest,
                          ov, err, gecerli])
            f.flush()
            pencereler.append((t, rm, peak, crest, gecerli))

            print(f"{t - baslangic:4.0f} {seq:5d} {rx:7d} {ry:7d} {rz:7d} "
                  f"{rm:8d} {peak:6d} {crest/1000:6.2f} {ov:3d} {err:3d}  "
                  f"{'OK' if gecerli else 'GECERSIZ'}")
    except KeyboardInterrupt:
        pass
    finally:
        port.close()
        if bozuk_f is not None:
            bozuk_f.close()

print("\n--- OZET ---")
n = len(pencereler)
gecerli_liste = [p for p in pencereler if p[4] == 1]
ng = len(gecerli_liste)
karar = "TEKRARLA"
rm_ort = rm_std = crest_ort = None

if n == 0:
    print("Hic pencere gelmedi.")
    print("Kontrol: STM32 calisiyor mu? RST-GND takili mi? PA2 -> NodeMCU TX mi?")
else:
    sure = pencereler[-1][0] - pencereler[0][0]
    boslukler = [b[0] - a[0] for a, b in zip(pencereler, pencereler[1:])]
    print(f"Pencere: {n}   Gecerli: {ng}   Gecersiz: {n - ng}   "
          f"Taninmayan satir: {bozuk}   Tekrar seq: {tekrar_seq}")
    if sure > 0:
        print(f"Sure: {sure:.1f} s   Hiz: {(n - 1) / sure:.3f} pencere/s")
    if boslukler:
        print(f"Pencereler arasi bosluk: ort {statistics.mean(boslukler):.2f} s   "
              f"en buyuk {max(boslukler):.2f} s")
    if ng:
        rmlist = [p[1] for p in gecerli_liste]
        rm_ort = statistics.mean(rmlist)
        rm_std = statistics.pstdev(rmlist) if ng > 1 else 0.0
        crest_ort = statistics.mean(p[3] for p in gecerli_liste)
        print(f"  rms_mag_ug: ort {rm_ort:.0f}  std {rm_std:.0f}  "
              f"min {min(rmlist)}  max {max(rmlist)}")
        print(f"  crest_x1000: ort {crest_ort:.0f}")

        # motor hala isiniyor / kayma var mi?
        if ng >= 20:
            ilk = statistics.mean(rmlist[:10])
            son = statistics.mean(rmlist[-10:])
            if ilk > 0 and abs(son - ilk) / ilk > 0.15:
                print(f"UYARI: ilk 10 pencere ({ilk:.0f}) ile son 10 pencere "
                      f"({son:.0f}) arasinda %15'ten fazla fark var. "
                      f"Motor hala isiniyor olabilir; bir dahaki sefere daha uzun bekle.")

    beklenen = args.sure / 1.03
    if reset_sayisi:
        print(f"UYARI: kayit sirasinda sira numarasi {reset_sayisi} kez geri gitti "
              f"(kart reset). Bu kayit KABUL edilmez.")
    if tekrar_seq > 2:
        print(f"UYARI: {tekrar_seq} tekrar eden pencere atildi; baglanti/port sorunu olabilir.")
    if ng == n and n >= 0.9 * beklenen and reset_sayisi == 0 and tekrar_seq <= 2:
        karar = "KABUL"
    print(f"\nKARAR: {karar}  (kabul: gecersiz pencere yok, en az "
          f"{0.9 * beklenen:.0f} pencere, reset yok)")

# kayit defterine ozet satiri ekle (kabul/tekrar fark etmeksizin, karari da yazar)
yeni = not os.path.exists(defter_yol)
with open(defter_yol, "a", newline="", encoding="utf-8") as d:
    w = csv.writer(d)
    if yeni:
        w.writerow(["dosya", "tarih", "motor", "tip", "durum", "volt_set",
                    "volt_olculen", "montaj", "run", "pencere", "gecerli",
                    "taninmayan", "rms_mag_ort_ug", "rms_mag_std_ug",
                    "crest_ort_x1000", "karar", "not"])
    w.writerow([dosya_adi, datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                args.motor, tip, args.durum, f"{args.volt:g}",
                args.olculen_volt, args.montaj, args.run, n, ng, bozuk,
                "" if rm_ort is None else f"{rm_ort:.0f}",
                "" if rm_std is None else f"{rm_std:.0f}",
                "" if crest_ort is None else f"{crest_ort:.0f}",
                karar, args.not_])

if bozuk:
    print("Taninmayan satirlar su dosyaya yazildi:", bozuk_yol)
print("Dosya:", yol)
print("Defter:", defter_yol)
