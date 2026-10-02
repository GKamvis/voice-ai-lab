import csv
import json
import unicodedata
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
INPUT = ROOT / "comparison.csv"
REFERENCES = ROOT / "samples" / "sources.json"
OUTPUT = ROOT / "benchmark" / "benchmark.csv"


def normalize(text):
    text = unicodedata.normalize("NFC", text)
    text = text.replace("İ", "i").replace("I", "ı").lower()
    text = "".join(
        " " if unicodedata.category(char).startswith("P") else char
        for char in text
    )
    return " ".join(text.split())


def edit_distance(reference, prediction):
    previous = list(range(len(prediction) + 1))

    for i, ref_item in enumerate(reference, start=1):
        current = [i]

        for j, pred_item in enumerate(prediction, start=1):
            current.append(min(
                previous[j] + 1,
                current[j - 1] + 1,
                previous[j - 1] + (ref_item != pred_item),
            ))

        previous = current

    return previous[-1]


def main():
    metadata = json.loads(REFERENCES.read_text(encoding="utf-8"))
    references = {
        item["file"]: item["transcript"]
        for item in metadata["samples"]
    }

    with INPUT.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    if not rows:
        raise ValueError("comparison.csv boşdur.")

    grouped = defaultdict(list)
    seen = set()

    for row in rows:
        model = row["model"]
        filename = row["audio_file"]
        key = (model, filename)

        if key in seen:
            raise ValueError(f"Təkrar nəticə var: {key}")
        seen.add(key)

        if filename not in references:
            raise ValueError(f"İstinad mətni tapılmadı: {filename}")

        duration = float(row["audio_duration"])
        elapsed = float(row["inference_time"])

        if duration <= 0 or elapsed <= 0:
            raise ValueError(f"Yanlış müddət: {key}")

        ref = normalize(references[filename])
        pred = normalize(row["transcript"])

        ref_words = ref.split()
        ref_chars = ref.replace(" ", "")

        if not ref_words or not ref_chars:
            raise ValueError(f"İstinad mətni boşdur: {filename}")

        grouped[model].append({
            "file": filename,
            "duration": duration,
            "time": elapsed,
            "word_errors": edit_distance(ref_words, pred.split()),
            "word_count": len(ref_words),
            "char_errors": edit_distance(
                ref_chars, pred.replace(" ", "")
            ),
            "char_count": len(ref_chars),
        })

    # Hər iki model bütün eyni nümunələri işlətmiş olmalıdır.
    expected_files = set(references)

    for model in ("base", "small"):
        actual_files = {item["file"] for item in grouped[model]}
        if actual_files != expected_files:
            missing = expected_files - actual_files
            extra = actual_files - expected_files
            raise ValueError(
                f"{model}: nümunələr uyğun deyil. "
                f"Çatışmayan={sorted(missing)}, artıq={sorted(extra)}"
            )

    summaries = []

    for model in ("base", "small"):
        items = grouped[model]
        duration = sum(item["duration"] for item in items)
        elapsed = sum(item["time"] for item in items)

        # Fayl faizlərinin sadə ortası deyil:
        # bütün səhvlər / bütün istinad sözləri və ya simvolları.
        wer = (
            sum(item["word_errors"] for item in items)
            / sum(item["word_count"] for item in items)
        )
        cer = (
            sum(item["char_errors"] for item in items)
            / sum(item["char_count"] for item in items)
        )

        summaries.append({
            "model": model,
            "samples": len(items),
            "audio_duration": duration,
            "inference_time": elapsed,
            "RTF": elapsed / duration,
            "WER": wer,
            "CER": cer,
        })

    print("\nÜMUMİ BENCHMARK\n")
    print(
        f"{'Model':<8} {'Audio(s)':>10} {'Inference(s)':>13} "
        f"{'RTF':>8} {'WER':>9} {'CER':>9}"
    )
    print("-" * 63)

    for result in summaries:
        print(
            f"{result['model']:<8} "
            f"{result['audio_duration']:>10.2f} "
            f"{result['inference_time']:>13.2f} "
            f"{result['RTF']:>8.3f} "
            f"{result['WER']:>8.2%} "
            f"{result['CER']:>8.2%}"
        )

    print("\nHƏR SƏS ÜZRƏ\n")
    for filename in sorted(expected_files):
        print(filename)
        for model in ("base", "small"):
            item = next(
                x for x in grouped[model] if x["file"] == filename
            )
            print(
                f"  {model:<5} | "
                f"time={item['time']:.2f}s | "
                f"RTF={item['time'] / item['duration']:.3f} | "
                f"WER={item['word_errors'] / item['word_count']:.2%} | "
                f"CER={item['char_errors'] / item['char_count']:.2%}"
            )

    base, small = summaries
    time_ratio = small["inference_time"] / base["inference_time"]
    wer_change = (small["WER"] - base["WER"]) * 100

    print(f"\nSmall/base emal müddəti nisbəti: {time_ratio:.2f}")
    print(
        f"WER fərqi (small − base): {wer_change:+.2f} faiz bəndi"
        "\nMənfi WER fərqi small modelinin daha az səhv etdiyini göstərir."
    )

    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summaries[0]))
        writer.writeheader()
        writer.writerows(summaries)

    print(f"\nYekun CSV: {OUTPUT}")


if __name__ == "__main__":
    main()