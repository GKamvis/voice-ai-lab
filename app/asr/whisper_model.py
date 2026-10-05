"""Load local weights once per application process, without request warm-up."""
import time


def load_model(name='small'):
    import torch
    import whisper
    torch.set_num_threads(4)
    started = time.perf_counter()
    model = whisper.load_model(name, device='cpu')
    return model, time.perf_counter() - started
