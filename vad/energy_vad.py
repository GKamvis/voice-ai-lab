import numpy as np

def rms(frame):
    return np.sqrt(np.mean(frame ** 2))

if rms_value > threshold:
    decision = "speech"
else:
    decision = "silence"