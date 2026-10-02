import csv
import gc
import json
import random
import time
import unicodedata
from pathlib import Path

import numpy as np
import torch
import whisper


SAMPLES = Path(__file__).resolve().parent
ROOT = SAMPLES.parent
OUTPUT = ROOT / "comparison.csv"

MODELS = ["base", "small"]
DEVICE = "cpu"  # Hər iki model eyni cihazda işləyir.
THREADS = 4

torch.set_num_threads(THREADS)


def normalize(text):
    """Registr və durğu işarələrini müqayisədən çıxarır."""
    text = unicodedata.normalize("NFC", text)
    text = text.replace("İ", "i").replace("I", "ı").lower()
    text = "".join(
        " " if unicodedata.category(char).startswith("P") else char
        for char in text
    )
    return " ".join(text.split())


def edit_distance(reference, prediction):
    """Silmə, əlavə etmə və əvəzləmə əməliyyatlarının minimum sayı."""
    previous = list(range(len(prediction) + 1))

    for i, ref_item in enumerate(reference, start=1):
        current = [i]

        for j, pred_item in enumerate(prediction, start=1):
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + (ref_item != pred_item),
                )
            )

        previous = current

    return previous[-1]


def calculate_errors(reference, prediction):
    ref = normalize(reference)
    pred = normalize(prediction)

    ref_words = ref.split()
    pred_words = pred.split()

    # CER hesablamasında boşluqları nəzərə almırıq.
    ref_chars = ref.replace(" ", "")
    pred_chars = pred.replace(" ", "")

    if not ref_words or not ref_chars:
        raise ValueError("İstinad mətni boş ola bilməz.")

    wer = edit_distance(ref_words, pred_words) / len(ref_words)
    cer = edit_distance(ref_chars, pred_chars) / len(ref_chars)

    return wer, cer


def main():
    metadata = json.loads(
        (SAMPLES / "sources.json").read_text(encoding="utf-8")
    )

    # Audio faylları əvvəlcədən oxunur:
    # diskdən oxuma və FFmpeg vaxtı inference_time-a daxil deyil.
    samples = []

    for item in metadata["samples"]:
        path = SAMPLES / item["file"]
        reference = item["transcript"]

        if not normalize(reference):
            raise ValueError(f"İstinad mətni boşdur: {path.name}")

        audio = whisper.load_audio(str(path))  # 16 kHz mono
        duration = len(audio) / whisper.audio.SAMPLE_RATE

        if duration <= 0:
            raise ValueError(f"Audio boşdur: {path.name}")

        samples.append((path.name, audio, duration, reference))

    if not samples:
        raise ValueError("Müqayisə üçün səs nümunəsi tapılmadı.")

    fields = [
        "model",
        "audio_file",
        "audio_duration",
        "inference_time",
        "RTF",
        "WER",
        "CER",
        "transcript",
    ]

    options = {
        "language": "az",
        "task": "transcribe",
        "fp16": False,
        "temperature": 0.0,
        "beam_size": 5,
        "condition_on_previous_text": False,
        "verbose": None,
    }

    with OUTPUT.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()

        for model_name in MODELS:
            print(f"\nModel yüklənir: {model_name}")

            # Yükləmə və internetdən endirmə ölçməyə daxil deyil.
            model = whisper.load_model(model_name, device=DEVICE)
            model.eval()

            with torch.inference_mode():
                # İlk işə salınmanın əlavə xərcini ölçmədən çıxarırıq.
                print("İsinmə keçidi...")
                model.transcribe(samples[0][1], **options)

                for filename, audio, duration, reference in samples:
                    random.seed(42)
                    np.random.seed(42)
                    torch.manual_seed(42)

                    start = time.perf_counter()
                    result = model.transcribe(audio, **options)
                    inference_time = time.perf_counter() - start

                    transcript = result["text"].strip()
                    wer, cer = calculate_errors(reference, transcript)
                    rtf = inference_time / duration

                    writer.writerow({
                        "model": model_name,
                        "audio_file": filename,
                        "audio_duration": round(duration, 3),
                        "inference_time": round(inference_time, 3),
                        "RTF": round(rtf, 4),
                        "WER": round(wer, 4),
                        "CER": round(cer, 4),
                        "transcript": transcript,
                    })
                    handle.flush()

                    print(
                        f"{model_name:5} | {filename:22} | "
                        f"audio={duration:.2f}s | "
                        f"inference={inference_time:.2f}s | "
                        f"RTF={rtf:.3f} | "
                        f"WER={wer:.1%} | CER={cer:.1%}"
                    )
                    print(f"  Mətn: {transcript}")

            del model
            gc.collect()

    print(f"\nNəticələr saxlanıldı: {OUTPUT}")


if __name__ == "__main__":
    main()