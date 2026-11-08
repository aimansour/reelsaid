"""Compare CPU audio detectors on labeled mono 16 kHz PCM WAV fixtures."""

import json
import sys
import wave
from pathlib import Path
from time import perf_counter

import numpy as np
import onnxruntime as ort
import webrtcvad
from ai_edge_litert.interpreter import Interpreter


def audio(path):
    with wave.open(str(path), "rb") as source:
        assert source.getframerate() == 16000 and source.getsampwidth() == 2 and source.getnchannels() == 1
        return np.frombuffer(source.readframes(source.getnframes()), dtype="<i2")


def web_rtc(samples):
    vad = webrtcvad.Vad(3)
    values = [vad.is_speech(samples[i:i + 480].tobytes(), 16000) for i in range(0, len(samples) - 479, 480)]
    return float(np.mean(values)) if values else 0


def silero(samples, session):
    state = np.zeros((2, 1, 128), dtype=np.float32)
    context = np.zeros(64, dtype=np.float32)
    sample_rate = np.array(16000, dtype=np.int64)
    scores = []
    for index in range(0, len(samples), 512):
        block = samples[index:index + 512]
        if len(block) < 512:
            block = np.pad(block, (0, 512 - len(block)))
        data = np.concatenate((context, block))
        score, state = session.run(None, {"input": data[None, :], "state": state, "sr": sample_rate})
        scores.append(float(score.item()))
        context = block[-64:]
    voiced = [index for index, score in enumerate(scores) if score >= .5]
    return {
        "voiceFraction": round(len(voiced) / len(scores), 3),
        "maxVoiceScore": round(max(scores), 3),
        "firstVoiceSecond": round(voiced[0] * .032, 3) if voiced else None,
        "lastVoiceSecond": round((voiced[-1] + 1) * .032, 3) if voiced else None,
    }


def yamnet(samples, interpreter):
    source = interpreter.get_input_details()[0]["index"]
    target = interpreter.get_output_details()[0]["index"]
    scores = []
    for index in range(0, max(1, len(samples) - 15599), 7680):
        block = samples[index:index + 15600]
        if len(block) < 15600:
            block = np.pad(block, (0, 15600 - len(block)))
        interpreter.set_tensor(source, block)
        interpreter.invoke()
        scores.append(interpreter.get_tensor(target)[0, [0, 132]])
    return {
        "speechMean": round(float(np.mean(scores, axis=0)[0]), 3),
        "musicMean": round(float(np.mean(scores, axis=0)[1]), 3),
    }


def main(directory):
    options = ort.SessionOptions()
    options.intra_op_num_threads = options.inter_op_num_threads = 1
    silero_session = ort.InferenceSession(
        str(directory / "silero_vad_latest.onnx"), sess_options=options, providers=["CPUExecutionProvider"],
    )
    interpreter = Interpreter(model_path=str(directory / "yamnet.tflite"), num_threads=1)
    interpreter.allocate_tensors()
    result = {}
    for path in sorted(directory.glob("*.wav")):
        pcm = audio(path)
        normalized = pcm.astype(np.float32) / 32768
        start = perf_counter()
        rtc = web_rtc(pcm)
        after_rtc = perf_counter()
        neural = silero(normalized, silero_session)
        after_vad = perf_counter()
        music = yamnet(normalized, interpreter)
        result[path.stem] = {
            "seconds": len(pcm) / 16000,
            "peak": round(float(np.abs(normalized).max()), 5),
            "webrtcVoiceFraction": round(rtc, 3),
            "silero": neural,
            "yamnet": music,
            "milliseconds": [round(1000 * (end - start), 1) for start, end in (
                (start, after_rtc), (after_rtc, after_vad), (after_vad, perf_counter()),
            )],
        }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
