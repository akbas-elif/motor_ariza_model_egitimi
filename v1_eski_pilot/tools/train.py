"""
Normal / dengesiz ikili siniflandirma (gercek olcum verisi, STM32F407 + GY-521).

Adimlar: veri yukleme -> dagilim grafikleri -> baseline (tek esik rms_mag)
-> karar agaci (max_depth 2-3, dort oznitelik kumesi) -> T1-T4 motor temelli testler
-> tum veriyle final agac (STM32'ye aktarilacak aday).

Calistirma (veri_egitimi klasorunde):  py tools/train.py
Ciktilar: models/ altina PNG, CSV, TXT, MD ve final_tree.joblib
"""
import sys
from pathlib import Path

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from sklearn.metrics import ConfusionMatrixDisplay, accuracy_score, confusion_matrix
from sklearn.tree import DecisionTreeClassifier, export_text

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "models"

LABELS = {"normal": 0, "dengesiz": 1}
CLASS_NAMES = ["normal", "dengesiz"]
RUN_ORDER = ["A_normal", "B_normal", "A_dengesiz", "B_dengesiz"]

FEATURE_SETS = {
    "rms_mag": ["rms_mag_ug"],
    "rms_mag+crest": ["rms_mag_ug", "crest_x1000"],
    "eksenler": ["rms_x_ug", "rms_y_ug", "rms_z_ug"],
    "hepsi": ["rms_x_ug", "rms_y_ug", "rms_z_ug", "rms_mag_ug", "peak_ug", "crest_x1000"],
}

# (motor, etiket) ciftleri: egitim, test
TESTS = {
    "T1": ([("A", "normal"), ("A", "dengesiz")], [("B", "normal"), ("B", "dengesiz")]),
    "T2": ([("B", "normal"), ("B", "dengesiz")], [("A", "normal"), ("A", "dengesiz")]),
    "T3": ([("A", "dengesiz"), ("B", "normal")], [("A", "normal"), ("B", "dengesiz")]),
    "T4": ([("A", "normal"), ("B", "dengesiz")], [("A", "dengesiz"), ("B", "normal")]),
}

# Karisiklik matrisi PNG'si kaydedilecek yapilandirmalar (hepsinin sayilari CSV'de var)
CM_CONFIGS = {("baseline", "rms_mag", 1), ("agac", "rms_mag+crest", 2)}

# STM32'ye aktarilacak kural: tek esik rms_mag (kullanici onayi 2026-10-21).
# crest kirilgan cikti (bkz. sonuc_raporu.md), bu yuzden finalde yok.
FINAL_FEATURES = "rms_mag"
FINAL_DEPTH = 1
SEED = 0


def load_data():
    reg = pd.read_csv(RAW / "kayitlar.csv")
    reg = reg[reg["kullanim"] == "egitim_test"]
    parts = []
    for _, r in reg.iterrows():
        df = pd.read_csv(RAW / r["dosya"])
        n0 = len(df)
        df = df.drop_duplicates(subset="seq")
        n_dup = n0 - len(df)
        df = df[df["gecerli"] == 1].copy()
        n_bad = n0 - n_dup - len(df)
        # Dosya icerigi kayitlar.csv ile uyusmali, T1-T4 bu etiketlere dayaniyor
        if set(df["etiket"]) != {r["etiket"]} or set(df["motor"]) != {r["motor"]}:
            sys.exit(f"HATA: {r['dosya']} etiket/motor bilgisi kayitlar.csv ile uyusmuyor")
        print(f"  {r['dosya']}: {len(df)} pencere (tekrar {n_dup}, gecersiz {n_bad})")
        df["kosu"] = f"{r['motor']}_{r['etiket']}"
        parts.append(df)
    data = pd.concat(parts, ignore_index=True)
    data["y"] = data["etiket"].map(LABELS)
    return data


def summarize_runs(data):
    summary = data.groupby("kosu").agg(
        pencere=("seq", "size"),
        rms_mag_min_mg=("rms_mag_ug", lambda s: s.min() / 1000),
        rms_mag_ort_mg=("rms_mag_ug", lambda s: s.mean() / 1000),
        rms_mag_max_mg=("rms_mag_ug", lambda s: s.max() / 1000),
        crest_min=("crest_x1000", lambda s: s.min() / 1000),
        crest_ort=("crest_x1000", lambda s: s.mean() / 1000),
        crest_max=("crest_x1000", lambda s: s.max() / 1000),
    ).reindex(RUN_ORDER).round(3)
    summary.to_csv(OUT / "ozet_kosu.csv")
    return summary


def plot_distributions(data):
    for col, ylabel, fname in [
        ("rms_mag_ug", "rms_mag (mg)", "dagilim_rms_mag.png"),
        ("crest_x1000", "crest factor", "dagilim_crest.png"),
    ]:
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.boxplot([data.loc[data["kosu"] == k, col] / 1000 for k in RUN_ORDER])
        ax.set_xticks(range(1, len(RUN_ORDER) + 1))
        ax.set_xticklabels(RUN_ORDER)
        ax.set_ylabel(ylabel)
        ax.set_title(f"{ylabel}: calistirma basina dagilim (gercek olcum)")
        ax.grid(axis="y", alpha=0.3)
        fig.tight_layout()
        fig.savefig(OUT / fname, dpi=120)
        plt.close(fig)


def subset(data, pairs):
    mask = pd.Series(False, index=data.index)
    for motor, etiket in pairs:
        mask |= (data["motor"] == motor) & (data["etiket"] == etiket)
    return data[mask]


def configs():
    yield "baseline", "rms_mag", 1
    for fs in FEATURE_SETS:
        for depth in (2, 3):
            yield "agac", fs, depth


def config_name(kind, fs, depth):
    return f"{kind} [{fs}] d{depth}"


def save_cm(y_true, y_pred, title, path):
    fig, ax = plt.subplots(figsize=(4, 4))
    ConfusionMatrixDisplay(
        confusion_matrix(y_true, y_pred, labels=[0, 1]), display_labels=CLASS_NAMES
    ).plot(ax=ax, colorbar=False)
    ax.set_title(title, fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def run_tests(data):
    rows, imp_rows, rule_lines = [], [], []
    for tname, (tr_pairs, te_pairs) in TESTS.items():
        tr, te = subset(data, tr_pairs), subset(data, te_pairs)
        for kind, fs, depth in configs():
            cols = FEATURE_SETS[fs]
            clf = DecisionTreeClassifier(max_depth=depth, random_state=SEED)
            clf.fit(tr[cols], tr["y"])
            pred = clf.predict(te[cols])
            tn, fp, fn, tp = confusion_matrix(te["y"], pred, labels=[0, 1]).ravel()
            rows.append({
                "test": tname, "model": kind, "oznitelikler": fs, "max_depth": depth,
                "n_egitim": len(tr), "n_test": len(te),
                "dogruluk": round(accuracy_score(te["y"], pred), 4),
                "tn": tn, "fp": fp, "fn": fn, "tp": tp,
            })
            for c, v in zip(cols, clf.feature_importances_):
                imp_rows.append({"test": tname, "model": kind, "oznitelikler": fs,
                                 "max_depth": depth, "oznitelik": c, "onem": round(v, 4)})
            if (kind, fs, depth) in CM_CONFIGS:
                title = f"{tname}: {config_name(kind, fs, depth)}"
                save_cm(te["y"], pred, title,
                        OUT / f"cm_{tname}_{kind}_{fs.replace('+', '_')}_d{depth}.png")
                rule_lines.append(f"### {title}\n{export_text(clf, feature_names=cols)}")
    results = pd.DataFrame(rows)
    results.to_csv(OUT / "sonuclar.csv", index=False)
    pd.DataFrame(imp_rows).to_csv(OUT / "oznitelik_onemleri.csv", index=False)
    (OUT / "kurallar_testler.txt").write_text("\n".join(rule_lines), encoding="utf-8")
    return results


def train_final(data):
    cols = FEATURE_SETS[FINAL_FEATURES]
    clf = DecisionTreeClassifier(max_depth=FINAL_DEPTH, random_state=SEED)
    clf.fit(data[cols], data["y"])
    rules = export_text(clf, feature_names=cols)
    (OUT / "kural_final.txt").write_text(rules, encoding="utf-8")
    joblib.dump({"model": clf, "features": cols, "classes": CLASS_NAMES},
                OUT / "final_tree.joblib")
    return rules


def accuracy_table(results):
    results = results.assign(yapilandirma=[
        config_name(k, f, d) for k, f, d in
        zip(results["model"], results["oznitelikler"], results["max_depth"])
    ])
    order = [config_name(*c) for c in configs()]
    return results.pivot(index="yapilandirma", columns="test", values="dogruluk").reindex(order)


def write_report(summary, table, final_rules):
    lines = [
        "# Model sonuclari: normal / dengesiz (gercek olcum verisi)",
        "",
        "Bu dosya `tools/train.py` tarafindan otomatik uretilir. Sentetik veri kullanilmadi.",
        "",
        "## Veri",
        "",
        "- Dort calistirma: motor A ve B, her biri normal ve dengesiz (her biri ~60 s, "
        "1024 orneklik pencere, 1 kHz, +-4 g).",
        "- Yalnizca `kayitlar.csv` icinde `kullanim = egitim_test` olan dosyalar kullanildi. "
        "Bazi kayitlar +-2 g araligi veya tekrar cekim oldugu icin disarida birakildi.",
        "- `dengesiz_mA_r2` ve `normal_mB_r4` dosyalarinin motor bilgisi kayit sirasindaki "
        "`--motor` etiketinden degil, deney notundan gelmektedir.",
        "",
        "| calistirma | pencere | rms_mag min / ort / max (mg) | crest min / ort / max |",
        "|---|---|---|---|",
    ]
    for kosu, r in summary.iterrows():
        lines.append(
            f"| {kosu} | {r['pencere']:.0f} | {r['rms_mag_min_mg']:.1f} / {r['rms_mag_ort_mg']:.1f} / "
            f"{r['rms_mag_max_mg']:.1f} | {r['crest_min']:.3f} / {r['crest_ort']:.3f} / {r['crest_max']:.3f} |"
        )
    lines += [
        "",
        "## Dogruluk (test pencereleri uzerinde)",
        "",
        "T1: A ile egit, B'de test. T2: B ile egit, A'da test. "
        "T3: A dengesiz + B normal ile egit, A normal + B dengesiz'de test. T4: T3'un tersi.",
        "",
        "| yapilandirma | " + " | ".join(table.columns) + " |",
        "|---|" + "---|" * len(table.columns),
    ]
    for name, r in table.iterrows():
        lines.append(f"| {name} | " + " | ".join(f"{v:.3f}" for v in r) + " |")
    lines += [
        "",
        "Karisiklik matrisi sayilari: `sonuclar.csv`, oznitelik onemleri: `oznitelik_onemleri.csv`.",
        "",
        "## Bulgular",
        "",
        "- `rms_mag` tek basina, tek esikle dort testte de tum test pencerelerini dogru siniflandirdi.",
        "- `[rms_mag, crest]` agaci T1, T2 ve T4'te bolmeyi crest ile yapti (egitim verisinde iki "
        "oznitelik de siniflari tam ayiriyor, esitlik crest lehine bozuldu) ve test pencerelerinde "
        "hata yapti. Crest'te siniflar arasi bosluk cok dar (normal en dusuk 1,534, dengesiz en "
        "yuksek 1,547), rms_mag'da ise genis (normal en fazla ~312 mg, dengesiz en az ~1364 mg). "
        "Bu nedenle crest STM32 kuralina konmadi.",
        "- Eksen bazli oznitelikler de bu veride tum testlerde dogru siniflandirdi. Bu, eksen "
        "RMS'lerinin guvenilir oldugunu gostermez: sinif farki cok buyuk ve eksen degerleri "
        "yeniden montajda bile belirgin oynadi.",
        "",
        f"## Final agac (tum veri, [{FINAL_FEATURES}], max_depth={FINAL_DEPTH})",
        "",
        "Birimler: rms_mag_ug = mikro-g, crest_x1000 = crest factor x 1000.",
        "",
        "```",
        final_rules.rstrip(),
        "```",
        "",
        "## Sinirliliklar",
        "",
        "- Bagimsiz ornek sayisi 4'tur (dort calistirma); pencere sayisi (~235) bagimsiz ornek "
        "sayisi degildir, ayni calistirmanin pencereleri birbirine cok benzer.",
        "- Sinif farki cok buyuktur (normal pencerelerde rms_mag <= ~312 mg, dengesizde >= ~1364 mg). "
        "Bu yuzden %100'e yakin dogruluk beklenen bir sonuctur, karmasik model gerekmez.",
        "- T3/T4'te her sinifin egitim ornekleri tek bir motordan gelir; bu testler modelin motor "
        "kimligini degil dengesizligi ogrendigine dair yalnizca zayif bir kanittir.",
        "- Esik (~838 mg) iki sinifin arasindaki genis bosluga duser; bu bosluga dusen bir "
        "durum (ornegin hafif dengesizlik) olculmedi, bu durumda kuralin ne yapacagi bilinmiyor.",
        "- Calisma iki motor, tek sensor konumu ve tek tip guclu dengesizlik (bantla olusturuldu) "
        "ile sinirlidir. Sonuc genel bir 'motor arizasi tespiti' iddiasi degildir; hafif "
        "dengesizligin ayirt edilebildigini gostermez.",
        "- Ivme degerleri kalibre edilmedi (bileske ~1,04 g). Gevsek montaj sinifi icin veri "
        "toplanmadi, kapsam ikili siniflandirmaya daraltildi.",
        "- Sistem kestirimci bakim yapmaz; mevcut titresimden durum siniflandirmasi yapar.",
    ]
    (OUT / "sonuc_raporu.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    OUT.mkdir(exist_ok=True)
    print("Veri yukleniyor:")
    data = load_data()
    print(f"Toplam {len(data)} pencere\n")

    summary = summarize_runs(data)
    print("Calistirma ozeti:")
    print(summary.to_string(), "\n")

    plot_distributions(data)
    results = run_tests(data)
    table = accuracy_table(results)
    print("Dogruluk (satir: yapilandirma, sutun: test):")
    print(table.to_string(), "\n")

    final_rules = train_final(data)
    print(f"Final agac [{FINAL_FEATURES}] max_depth={FINAL_DEPTH} (tum veri):")
    print(final_rules)

    write_report(summary, table, final_rules)
    print(f"Ciktilar: {OUT}")


if __name__ == "__main__":
    main()
