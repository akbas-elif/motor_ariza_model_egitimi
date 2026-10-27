"""
train.py - STM32 titresim izleme projesi, durum siniflandirma egitimi (PC tarafi).

Girdi : data_v2/kayit_defteri.csv ve data_v2/raw/*.csv  (gercek olcum)
Cikti : sonuclar_v2/  (rapor, model.json, grafikler, tablolar)

Calistirma (depo kok klasorunde):
  py -m pip install -r requirements.txt
  py tools/train.py

Veri: gercek olcum (GY-521 ivmeolcer, STM32F407, motor 1A ve 1B, tip 1 silindir).
Sentetik veri YOKTUR. Tek ozellik: pencere basina rms_mag (ofset cikarilmis, 1024 ornek, 1 kHz).
"""
import json
import os
import sys
import warnings
from datetime import datetime

import numpy as np
import pandas as pd
from sklearn.tree import DecisionTreeClassifier

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.lines import Line2D

warnings.filterwarnings("ignore")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # depo kok klasoru
VERI = os.path.join(KOK, "data_v2")
HAM = os.path.join(VERI, "raw")
CIKTI = os.path.join(KOK, "sonuclar_v2")
os.makedirs(CIKTI, exist_ok=True)

# Logger etiketi -> egitim sinifi (kullanici karari, 2026-10-27):
#   normal              -> 0 normal      (agirlik yok)
#   cok_bozuk (2 karton) -> 1 orta_bozuk
#   dengesiz (somun)     -> 2 cok_bozuk   (lehimli somun)
#   bozuk (1 karton)     -> KULLANILMIYOR
SEVIYE = {"normal": 0, "cok_bozuk": 1, "dengesiz": 2}
AD3 = ["normal", "orta_bozuk", "cok_bozuk"]
ACIKLAMA = {"normal": "agirlik yok", "cok_bozuk": "2 karton", "dengesiz": "lehimli somun"}
AD2 = ["normal", "arizali"]
KAYMA_ESIGI = 15.0          # % (ilk 10 ile son 10 pencere ortalamasi arasi)
ESIK_RMS_BAS = 5.0          # crest > 5 -> glitch penceresi


# ---------------------------------------------------------------- veri
def temizle(d):
    """Gecersiz ve glitch pencerelerini at. (atilan_sayisi, temiz_df) dondurur."""
    d = d[d.gecerli == 1].copy()
    r = d.rms_mag_ug.values / 1000.0
    c = d.crest_x1000.values / 1000.0
    med = np.median(r)
    mad = np.median(np.abs(r - med)) * 1.4826 + 1e-9
    glitch = (c > ESIK_RMS_BAS) | (
        (np.abs(r - med) > 6 * mad) & ((c > 2.7) | (np.abs(r - med) > 0.3 * med)))
    d = d[~glitch].copy()
    d["rms"] = d.rms_mag_ug / 1000.0          # mg
    return int(glitch.sum()), d


def yukle():
    defter = pd.read_csv(os.path.join(VERI, "kayit_defteri.csv"))
    defter = defter[defter.karar == "KABUL"]
    parcalar, kalite, kullanilmayan = [], [], []
    for _, s in defter.iterrows():
        if s.durum not in SEVIYE:
            kullanilmayan.append(s.dosya)
            continue
        yol = os.path.join(HAM, s.dosya)
        if not os.path.exists(yol):
            print(f"UYARI: defterde var, dosyasi yok, atlandi: {s.dosya}")
            continue
        ham = pd.read_csv(yol)
        n_glitch, d = temizle(ham)
        r = d.rms.values
        kayma = 100 * (r[-10:].mean() / r[:10].mean() - 1)
        d["y"] = d.durum.map(SEVIYE)
        d["kayit"] = s.dosya
        d["montaj_grubu"] = d.motor + "_mt" + d.montaj.astype(str)
        d["kaymali"] = abs(kayma) > KAYMA_ESIGI
        parcalar.append(d)
        kalite.append(dict(dosya=s.dosya, motor=d.motor.iloc[0], durum=d.durum.iloc[0],
                           sinif=AD3[SEVIYE[d.durum.iloc[0]]], agirlik=ACIKLAMA[d.durum.iloc[0]],
                           montaj=int(d.montaj.iloc[0]), run=int(d.run.iloc[0]),
                           pencere=len(ham), glitch_atilan=n_glitch,
                           ort_mg=round(r.mean(), 2), std_mg=round(r.std(), 2),
                           min_mg=round(r.min(), 2), max_mg=round(r.max(), 2),
                           kayma_yuzde=round(kayma, 1), kaymali=abs(kayma) > KAYMA_ESIGI))
    V = pd.concat(parcalar, ignore_index=True)
    Q = pd.DataFrame(kalite)
    Q["_s"] = Q.durum.map(SEVIYE)
    Q = Q.sort_values(["motor", "_s", "montaj"]).drop(columns="_s").reset_index(drop=True)
    return V, Q, kullanilmayan


# ---------------------------------------------------------------- model
def ortala(x, t):
    """Esigi, iki yanindaki en yakin egitim degerlerinin geometrik ortasina tasi
    (bosluk varsa esik boslugun ortasina oturur, sinira yapismaz)."""
    alt, ust = x[x < t], x[x >= t]
    if len(alt) == 0 or len(ust) == 0:
        return float(t)
    return float(np.sqrt(alt.max() * ust.min()))


def esik_bul(x, y, k):
    """k=1: 1 esik (2 sinif), k=2: 2 esik (3 sinif). Dogrulugu en yuksek yapan esikleri sec."""
    u = np.unique(x)
    orta_noktalar = (u[:-1] + u[1:]) / 2
    if len(orta_noktalar) > 300:
        secili = orta_noktalar[np.linspace(0, len(orta_noktalar) - 1, 300).astype(int)]
        bosluk = u[1:] - u[:-1]
        en_buyuk = orta_noktalar[np.argsort(bosluk)[-30:]]     # sinif arasi bosluklar kacmasin
        aday = np.unique(np.concatenate([secili, en_buyuk]))
    else:
        aday = orta_noktalar
    if k == 1:
        t = max(((np.where(x < t, 0, 1) == y).mean(), (float(t),)) for t in aday)[1]
        return (ortala(x, t[0]),)
    en = (-1.0, None)
    for i, t1 in enumerate(aday):
        for t2 in aday[i + 1:]:
            a = (np.where(x < t1, 0, np.where(x < t2, 1, 2)) == y).mean()
            if a > en[0]:
                en = (a, (float(t1), float(t2)))
    return tuple(ortala(x, t) for t in en[1])


def tahmin_esik(x, t):
    return np.searchsorted(np.array(t), x, side="right")


def oy5(p):
    """STM32'deki gibi son 5 tahminin ortancasi (kayan pencere; siniflar sirali)."""
    p = np.asarray(p)
    out = p.copy()
    for i in range(len(p)):
        w = np.sort(p[max(0, i - 4): i + 1])
        out[i] = w[len(w) // 2]
    return out


def egit_tahmin(model, tr, te, ikili):
    ytr = (tr.y > 0).astype(int).values if ikili else tr.y.values
    if model == "esik":
        t = esik_bul(tr.rms.values, ytr, 1 if ikili else 2)
        return tahmin_esik(te.rms.values, t), t
    m = DecisionTreeClassifier(max_depth=1 if ikili else 2, random_state=0).fit(tr[["rms"]], ytr)
    t = tuple(sorted(float(v) for v in m.tree_.threshold[m.tree_.feature >= 0]))
    return m.predict(te[["rms"]]), t


def capraz(V, model, ikili, bolme):
    """bolme: 'montaj_grubu' (bir montaji disarida birak) veya 'motor' (bir motoru disarida birak)."""
    y_all, p_all, p5_all, hatali = [], [], [], []
    kayit_dogru = kayit_n = 0
    for g, te in V.groupby(bolme):
        tr = V[V[bolme] != g]
        p, _ = egit_tahmin(model, tr, te, ikili)
        y = (te.y > 0).astype(int).values if ikili else te.y.values
        y_all += list(y)
        p_all += list(p)
        # 5'li oy kayit icinde, kayit sirasina gore
        p5 = np.empty(len(te), dtype=int)
        for _, idx in te.groupby("kayit").indices.items():
            p5[idx] = oy5(np.asarray(p)[idx])
        p5_all += list(p5)
        if bolme == "montaj_grubu":
            for kayit, idx in te.groupby("kayit").indices.items():
                kayit_n += 1
                maj = int(np.bincount(np.asarray(p)[idx], minlength=3).argmax())
                gercek = int(y[idx][0])
                if maj == gercek:
                    kayit_dogru += 1
                else:
                    ad = AD2 if ikili else AD3
                    hatali.append(f"{kayit} (gercek {ad[gercek]}, karar {ad[maj]})")
    y_all, p_all, p5_all = map(np.array, (y_all, p_all, p5_all))
    return dict(acc=float((p_all == y_all).mean()), acc5=float((p5_all == y_all).mean()),
                kayit_dogru=kayit_dogru, kayit_n=kayit_n, hatali=hatali, y=y_all, p=p_all)


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    m = (p + z * z / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (m - h, m + h)


def karisiklik(y, p, n):
    M = np.zeros((n, n), int)
    for a, b in zip(y, p):
        M[a, b] += 1
    return M


# ---------------------------------------------------------------- calistir
V, Q, KULLANILMAYAN = yukle()
Q.to_csv(os.path.join(CIKTI, "kayit_kalitesi.csv"), index=False)
print(f"{Q.shape[0]} kayit, {len(V)} temiz pencere, "
      f"{int(Q.glitch_atilan.sum())} glitch penceresi atildi")
print(Q[["motor", "durum", "montaj", "run", "ort_mg", "std_mg", "kayma_yuzde", "glitch_atilan"]].to_string(index=False))

senaryolar = {"A (tum kayitlar)": V}
if V.kaymali.any() and V[~V.kaymali].y.nunique() == V.y.nunique():
    senaryolar["B (kayma>%15 olanlar haric)"] = V[~V.kaymali]
elif V.kaymali.any():
    print("Not: kaymali kayitlari cikarmak bir sinifi tamamen siliyor; B senaryosu atlandi.")
satirlar, sonuc = [], {}
for sn, D in senaryolar.items():
    nk = D.kayit.nunique()
    for ikili in (False, True):
        for model in ("esik", "agac"):
            mg = capraz(D, model, ikili, "montaj_grubu")
            mm = capraz(D, model, ikili, "motor")
            tum = egit_tahmin(model, D, D, ikili)[1]
            sonuc[(sn, ikili, model)] = (mg, mm, tum)
            satirlar.append({
                "senaryo": sn, "kayit_sayisi": nk, "sinif": "2 (normal/arizali)" if ikili else "3 (normal/orta_bozuk/cok_bozuk)",
                "model": "tek esik" if (model == "esik" and ikili) else ("2 esik" if model == "esik" else "karar agaci"),
                "pencere_dogruluk_montaj_disarida": round(mg["acc"], 3),
                "pencere_dogruluk_5li_oy": round(mg["acc5"], 3),
                "kayit_karari": f"{mg['kayit_dogru']}/{mg['kayit_n']}",
                "pencere_dogruluk_motor_disarida": round(mm["acc"], 3),
                "esikler_mg_tum_veri": ", ".join(f"{t:.1f}" for t in tum)})
T = pd.DataFrame(satirlar)
T.to_csv(os.path.join(CIKTI, "sonuc_tablosu.csv"), index=False)
print("\n", T.to_string(index=False))

# demo modeli: 3 sinif, 2 esik, tum kayitlar (senaryo A); karsilastirma: 2 sinif tek esik
A = senaryolar["A (tum kayitlar)"]
mgA2, mmA2, tumA2 = sonuc[("A (tum kayitlar)", True, "esik")]
mgA3, mmA3, tumA3 = sonuc[("A (tum kayitlar)", False, "esik")]
esik2 = tumA2[0]
esik3 = tumA3
print(f"\nDEMO MODELI (3 sinif): normal < {esik3[0]:.2f} mg <= bozuk < {esik3[1]:.2f} mg <= cok_bozuk")
print(f"KARSILASTIRMA (2 sinif): rms_mag >= {esik2:.2f} mg -> arizali")

model_json = {
    "olusturma": datetime.now().strftime("%Y-%m-%d %H:%M"),
    "veri_kaynagi": "gercek olcum; GY-521 (MPU-6500 uyumlu) + STM32F407, ayni tip iki motor (1A, 1B; tip 1 silindir); sentetik veri yok",
    "ozellik": "rms_mag (pencere basina, ofset cikarilmis, 1024 ornek @ 1 kHz, +-4 g)",
    "demo_modeli": {
        "tur": "2 esik, 3 sinif (normal / orta_bozuk / cok_bozuk)",
        "kural": "rms_mag < esik1 -> normal; esik1 <= rms_mag < esik2 -> orta_bozuk (2 karton); rms_mag >= esik2 -> cok_bozuk (somun)",
        "esikler_mg": [round(t, 3) for t in esik3],
        "esikler_ug": [int(round(t * 1000)) for t in esik3],
        "kayit_sayisi": int(A.kayit.nunique()),
        "pencere_sayisi": int(len(A)),
        "montaj_disarida_pencere_dogrulugu": round(mgA3["acc"], 3),
        "kayit_karari": f"{mgA3['kayit_dogru']}/{mgA3['kayit_n']}",
        "motor_disarida_pencere_dogrulugu": round(mmA3["acc"], 3),
        "durum": "DEMO: ayni tip iki motorla; kor test yapilmadi; STM32'de henuz denenmedi"},
    "karsilastirma_2_sinif": {
        "tur": "tek esik, 2 sinif (normal / arizali)",
        "esik_mg": round(esik2, 3),
        "esik_ug": int(round(esik2 * 1000)),
        "montaj_disarida_pencere_dogrulugu": round(mgA2["acc"], 3),
        "kayit_karari": f"{mgA2['kayit_dogru']}/{mgA2['kayit_n']}",
        "motor_disarida_pencere_dogrulugu": round(mmA2["acc"], 3)}}
with open(os.path.join(CIKTI, "model.json"), "w", encoding="utf-8") as f:
    json.dump(model_json, f, ensure_ascii=False, indent=2)

# ---------------------------------------------------------------- grafikler
YUZEY, INK, INK2, MUTED, GRID, EKSEN = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
MAVI, TURUNCU = "#2a78d6", "#eb6834"
plt.rcParams.update({"font.family": "DejaVu Sans", "figure.facecolor": YUZEY, "axes.facecolor": YUZEY,
                     "axes.edgecolor": EKSEN, "text.color": INK, "axes.labelcolor": INK2,
                     "xtick.color": MUTED, "ytick.color": MUTED})
rampa = LinearSegmentedColormap.from_list("mavi", ["#cde2fb", "#6da7ec", "#2a78d6", "#184f95", "#0d366b"])


def cm_ciz(ax, M, adlar, baslik):
    ax.imshow(M, cmap=rampa, vmin=0, vmax=max(M.max(), 1))
    for i in range(M.shape[0]):
        for j in range(M.shape[1]):
            koyu = M[i, j] > 0.55 * M.max()
            ax.text(j, i, str(M[i, j]), ha="center", va="center", fontsize=12,
                    color="#ffffff" if koyu else INK)
    ax.set_xticks(range(len(adlar)))
    ax.set_xticklabels(adlar, fontsize=9)
    ax.set_yticks(range(len(adlar)))
    ax.set_yticklabels(adlar, fontsize=9)
    ax.set_xlabel("Tahmin")
    ax.set_ylabel("Gercek")
    ax.set_title(baslik, fontsize=11, color=INK, loc="left")
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.tick_params(length=0)


fig, axs = plt.subplots(1, 2, figsize=(10.5, 4.4))
M3 = karisiklik(mgA3["y"], mgA3["p"], 3)
M2 = karisiklik(mgA2["y"], mgA2["p"], 2)
cm_ciz(axs[0], M3, AD3, f"3 duzey (demo modeli): pencere dogrulugu {mgA3['acc']:.2f}")
cm_ciz(axs[1], M2, AD2, f"2 duzey (karsilastirma): pencere dogrulugu {mgA2['acc']:.2f}")
fig.suptitle("Karisiklik matrisleri - bir montaji disarida birakarak test (pencere sayisi)", x=0.02, ha="left",
             fontsize=11, color=INK2)
fig.tight_layout(rect=(0, 0, 1, 0.94))
fig.savefig(os.path.join(CIKTI, "karisiklik_matrisleri.png"), dpi=160)
plt.close(fig)

fig, ax = plt.subplots(figsize=(9.2, 5.0))
rng = np.random.default_rng(1)
for _, s in Q.iterrows():
    x = SEVIYE[s.durum] + (-0.12 if s.motor == "1A" else 0.12) + rng.uniform(-0.05, 0.05)
    renk = MAVI if s.motor == "1A" else TURUNCU
    ax.errorbar(x, s.ort_mg, yerr=s.std_mg, fmt="none", ecolor=renk, elinewidth=1.2, alpha=0.55, zorder=2)
    ax.scatter(x, s.ort_mg, s=80 if s.kaymali else 62, marker="D" if s.kaymali else "o", color=renk,
               edgecolor=YUZEY, linewidth=1.5, zorder=3)
for t, e in zip(esik3, ("esik 1 (normal | orta bozuk)", "esik 2 (orta bozuk | cok bozuk)")):
    ax.axhline(t, color=INK2, lw=1.0, ls=(0, (4, 3)), zorder=1)
    ax.text(2.48, t * 1.04, f"{e}: {t:.1f} mg", ha="right", va="bottom", fontsize=9, color=INK2)
ax.set_xticks(range(3))
ax.set_xticklabels(["normal", "orta bozuk (2 karton)", "cok bozuk (somun)"], fontsize=10)
ax.set_xlim(-0.55, 2.55)
ax.set_yscale("log")
ax.set_ylabel("Kayit ortalamasi rms_mag (mg, log olcek)")
ax.yaxis.grid(True, which="both", color=GRID, lw=0.6)
ax.set_axisbelow(True)
for k in ("top", "right"):
    ax.spines[k].set_visible(False)
ax.set_title("Duzeye gore kayit ortalamalari ve demo modeli esikleri (cubuk = kayit ici std)", loc="left", fontsize=11, color=INK)
lejant = [
    Line2D([0], [0], marker="o", color="none", markerfacecolor=MAVI, markeredgecolor=YUZEY, markersize=9, label="motor 1A"),
    Line2D([0], [0], marker="o", color="none", markerfacecolor=TURUNCU, markeredgecolor=YUZEY, markersize=9, label="motor 1B")]
if Q.kaymali.any():
    lejant.append(Line2D([0], [0], marker="D", color="none", markerfacecolor=MUTED, markeredgecolor=YUZEY, markersize=9,
                         label=f"kayit icinde kayma > %{KAYMA_ESIGI:.0f}"))
ax.legend(handles=lejant, loc="upper left", frameon=False, fontsize=9)
fig.tight_layout()
fig.savefig(os.path.join(CIKTI, "kayit_ortalamalari.png"), dpi=160)
plt.close(fig)

# ---------------------------------------------------------------- rapor
def s(sn, ikili, model):
    mg, mm, tum = sonuc[(sn, ikili, model)]
    lo, hi = wilson(mg["kayit_dogru"], mg["kayit_n"])
    return mg, mm, tum, lo, hi

satir_md = []
for sn in senaryolar:
    for ikili in (False, True):
        mg, mm, tum, lo, hi = s(sn, ikili, "esik")
        satir_md.append(f"| {sn} | {'2 duzey' if ikili else '3 duzey'} | {mg['acc']:.2f} | {mg['acc5']:.2f} | "
                        f"{mg['kayit_dogru']}/{mg['kayit_n']} (%{100*lo:.0f}-%{100*hi:.0f}) | {mm['acc']:.2f} | "
                        f"{', '.join(f'{t:.1f}' for t in tum)} |")

seviye_md = []
for d in AD3:
    g = Q[Q.sinif == d]
    seviye_md.append(f"| {d} ({g.agirlik.iloc[0]}) | {len(g)} | {g.ort_mg.min():.1f} - {g.ort_mg.max():.1f} | {g.ort_mg.mean():.1f} |")

rapor = f"""# Egitim sonuclari (otomatik uretildi: {datetime.now().strftime('%Y-%m-%d %H:%M')})

## Veri
- **Kaynak: gercek olcum.** GY-521 (MPU-6500 uyumlu) + STM32F407, 1 kHz ornekleme, 1024 ornekli pencere, +-4 g.
  Sentetik veri kullanilmadi.
- Motorlar: 1A ve 1B (ayni tip, silindir, 5 V ayar). Duzeyler: normal (agirlik yok), orta bozuk (milde 2 karton parcasi), cok bozuk (milde lehimli somun).
- Kullanilmayan kayitlar (tek karton, bu modelde yer almiyor): {", ".join(KULLANILMAYAN) if KULLANILMAYAN else "yok"}.
- {Q.shape[0]} kayit, {len(V)} temiz pencere ({int(Q.glitch_atilan.sum())} glitch penceresi atildi).
  Her kayit ayri bir montaj: 1A icin {Q[Q.motor=='1A'].montaj.nunique()}, 1B icin {Q[Q.motor=='1B'].montaj.nunique()} montaj. Bagimsiz ornek sayisi bu.
- Ozellik: yalnizca `rms_mag` (mg).

| Duzey | Kayit | Kayit ortalamasi araligi (mg) | Ort. (mg) |
|---|---|---|---|
{chr(10).join(seviye_md)}

## Test yontemi
Her sinamada bir montaj (veya bir motor) tamamen disarida birakilip tahmin ettirildi. Esikler yalnizca kalan veriden secildi.
Ayni kaydin pencereleri hem egitimde hem testte yer almadi. "5'li oy": son 5 tahminin ortancasi (STM32'deki oylama gibi).
Esikler, egitim verisindeki iki sinif arasindaki boslugun geometrik ortasina yerlestirildi.

## Sonuc
| Senaryo | Sinif | Pencere dogr. | 5'li oy | Kayit karari (%95 aralik) | Motor disarida | Esikler (mg, tum veri) |
|---|---|---|---|---|---|---|
{chr(10).join(satir_md)}


![Karisiklik matrisleri](karisiklik_matrisleri.png)
![Kayit ortalamalari](kayit_ortalamalari.png)

## Demo modeli: 3 duzey
- Kural: `rms_mag < {esik3[0]:.2f} mg` normal, `{esik3[0]:.2f} - {esik3[1]:.2f} mg` orta bozuk, `>= {esik3[1]:.2f} mg` cok bozuk
  (STM32 icin: {esik3[0]*1000:.0f} ug ve {esik3[1]*1000:.0f} ug).
- Montaj disarida pencere dogrulugu {mgA3['acc']:.2f}, kayit karari {mgA3['kayit_dogru']}/{mgA3['kayit_n']}, motor disarida {mmA3['acc']:.2f}.
- Yanlis giden kayitlar: {'; '.join(mgA3['hatali']) if mgA3['hatali'] else 'yok'}.
- Bu sonuc ayni tip iki motorla yapilmis bir **demodur**; kor test yapilmamistir ve gelistirilmelidir.

## Karsilastirma: 2 duzey (normal / arizali)
- Tek esik `rms_mag >= {esik2:.2f} mg` -> arizali. Montaj disarida pencere dogrulugu {mgA2['acc']:.2f}, kayit karari {mgA2['kayit_dogru']}/{mgA2['kayit_n']}.
- Yanlis giden kayitlar: {'; '.join(mgA2['hatali']) if mgA2['hatali'] else 'yok'}.

## Sinirliliklar (rapora aynen yazilmali)
- Ayni tip yalnizca 2 motor (tek tip motor uzerinde demo), tek sensor konumu, kayit basina tek montaj; bagimsiz ornek sayisi {Q.shape[0]}; cok bozuk (somun) sinifinda yalnizca {int((Q.sinif=="cok_bozuk").sum())} kayit (motor basina 1).
- Agirliklar el yapimi (karton parcalari, lehimli somun), kutleleri tartilmadi; 1A'da ayni agirlikla kayitlar arasi buyuk fark var.
- Somunlu kayitlarda iki deneme motor kayit sirasinda durdugu icin atildi (data_v2/atilan).
- Pencerelerin yuzde 15'ten fazla kayan kayitlari (motor isinmasi veya agirlik oynamasi) var: {', '.join(Q[Q.kaymali].dosya) if Q.kaymali.any() else 'yok'}.
- Esikler ayni {Q.shape[0]} kayit uzerinde secildi; **henuz gorulmemis yeni kayitlarla kor test yapilmadi.** STM32 uzerinde de denenmedi.
- Sonuc "bu duzenekte" gecerlidir; baska motor/sensor/montaj icin genelleme iddiasi yoktur.
- Calisma, kestirimci bakim degil, mevcut titresimden durum siniflandirmadir.
"""
with open(os.path.join(CIKTI, "egitim_raporu.md"), "w", encoding="utf-8") as f:
    f.write(rapor)

print(f"\nSTM32 icin demo modeli: esik1 = {esik3[0]*1000:.0f} ug, esik2 = {esik3[1]*1000:.0f} ug")
print("Yazilan dosyalar -> " + CIKTI)
