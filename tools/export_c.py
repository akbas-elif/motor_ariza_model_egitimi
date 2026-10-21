"""
models/final_tree.joblib icindeki karar agacini STM32 icin tam sayi if-else C fonksiyonuna cevirir.

Esikler: sklearn esigi t (orn. 838154.5) ile tam sayi x icin  x <= t  <=>  x <= floor(t).
Uretilen kural Python'da ayni tam sayi mantigiyla tum veride yeniden calistirilir ve
sklearn tahminleriyle karsilastirilir; tek bir fark olursa dosya yazilmaz.

Calistirma (veri_egitimi klasorunde, train.py'den sonra):  py tools/export_c.py
Cikti: firmware/snippets/classify.c
"""
import math
import sys
from pathlib import Path

import joblib
from sklearn.tree import _tree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from train import OUT, load_data  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT_C = ROOT / "firmware" / "snippets" / "classify.c"


def leaf_class(clf, node):
    return int(clf.classes_[clf.tree_.value[node][0].argmax()])


def emit(clf, features, classes, node, depth, lines):
    t = clf.tree_
    pad = "  " * depth
    if t.feature[node] == _tree.TREE_UNDEFINED:
        cls = leaf_class(clf, node)
        lines.append(f"{pad}return {cls};  /* {classes[cls]} */")
        return
    name = features[t.feature[node]]
    lines.append(f"{pad}if ({name} <= {math.floor(t.threshold[node])})")
    lines.append(f"{pad}{{")
    emit(clf, features, classes, t.children_left[node], depth + 1, lines)
    lines.append(f"{pad}}}")
    lines.append(f"{pad}else")
    lines.append(f"{pad}{{")
    emit(clf, features, classes, t.children_right[node], depth + 1, lines)
    lines.append(f"{pad}}}")


def predict_int(clf, features, row):
    """C koduyla ayni mantik: tam sayi deger, floor(esik) ile <= karsilastirma."""
    t, node = clf.tree_, 0
    while t.feature[node] != _tree.TREE_UNDEFINED:
        value = int(row[features[t.feature[node]]])
        node = (t.children_left[node] if value <= math.floor(t.threshold[node])
                else t.children_right[node])
    return leaf_class(clf, node)


def main():
    bundle = joblib.load(OUT / "final_tree.joblib")
    clf, features, classes = bundle["model"], bundle["features"], bundle["classes"]

    data = load_data()
    sk_pred = clf.predict(data[features])
    int_pred = [predict_int(clf, features, r) for _, r in data.iterrows()]
    mismatch = sum(int(a != b) for a, b in zip(sk_pred, int_pred))
    errors = sum(int(p != y) for p, y in zip(int_pred, data["y"]))
    print(f"Dogrulama: {len(data)} pencere, sklearn ile fark {mismatch}, etikete gore hata {errors}")
    if mismatch:
        sys.exit("HATA: tam sayi kural sklearn ile ayni sonucu vermiyor, C dosyasi yazilmadi")

    params = ", ".join(f"int32_t {f}" for f in features)
    body = []
    emit(clf, features, classes, 0, 1, body)
    code = "\n".join([
        "/* OTOMATIK URETILDI: tools/export_c.py -- elle degistirme;",
        " * kurali degistirmek icin train.py ve export_c.py'yi yeniden calistir.",
        " * Kaynak: models/final_tree.joblib (gercek olcum verisi, normal / dengesiz)",
        " * Birim: rms_mag_ug = mikro-g, pencere ortalamasi cikarilmis bileske RMS",
        " * Donus: " + ", ".join(f"{i} = {c}" for i, c in enumerate(classes)),
        f" * Dogrulama: {len(data)} pencerede sklearn ile fark {mismatch}, etikete gore hata {errors}",
        " *",
        " * main.c'ye yerlesim:",
        f" *   USER CODE BEGIN PFP : uint8_t classify({params});",
        " *   USER CODE BEGIN 4   : asagidaki fonksiyon",
        " */",
        f"uint8_t classify({params})",
        "{",
        *body,
        "}",
        "",
    ])
    OUT_C.parent.mkdir(parents=True, exist_ok=True)
    OUT_C.write_text(code, encoding="utf-8")
    print(code)
    print(f"Yazildi: {OUT_C}")


if __name__ == "__main__":
    main()
