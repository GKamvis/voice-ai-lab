from jiwer import wer, cer

def calculate_metrics(reference, hypothesis):
    return {
        "wer": wer(reference, hypothesis),
        "cer": cer(reference, hypothesis),
    }