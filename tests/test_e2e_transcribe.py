"""End-to-end transcription test against a known speech clip.

Deliberately self-contained: it re-implements the audio -> model -> cleanup
pipeline instead of importing stt.py, whose import has app-level side effects
(logging tee, env reads). Once transcribe() moves to an importable module,
this test should call the production function instead.
"""

import wave
from pathlib import Path

import pytest

FIXTURE = Path(__file__).with_name("fixtures") / "spoken-input.wav"
PARAKEET_REPO = "mlx-community/parakeet-tdt-0.6b-v2"
UTTERANCE_GAP = 0.7  # mirrors the default in stt.py

EXPECTED_TEXT = (
    "Create a short summary from this meeting note and list the next action items."
)


@pytest.mark.e2e
def test_known_clip_transcribes_to_expected_text():
    # Heavy imports stay inside the test so collecting the fast suite is instant.
    import mlx.core as mx
    import numpy as np
    from huggingface_hub import hf_hub_download
    from parakeet_mlx import DecodingConfig, SentenceConfig, from_pretrained
    from parakeet_mlx.audio import get_logmel

    from text_cleanup import apply_corrections
    from voice_commands import apply_voice_commands

    with wave.open(str(FIXTURE), "rb") as wf:
        assert wf.getframerate() == 16000
        assert wf.getnchannels() == 1
        audio = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
    audio = audio.astype(np.float32) / 32768.0

    try:
        config_json = hf_hub_download(PARAKEET_REPO, "config.json", local_files_only=True)
        model = from_pretrained(str(Path(config_json).parent))
    except Exception:
        model = from_pretrained(PARAKEET_REPO)

    mel = get_logmel(mx.array(audio), model.preprocessor_config)
    decoding_config = DecodingConfig(sentence=SentenceConfig(silence_gap=UTTERANCE_GAP))
    result = model.generate(mel, decoding_config=decoding_config)[0]

    raw = result.text.strip()
    cleaned = apply_corrections(apply_voice_commands(result.sentences))

    assert raw == EXPECTED_TEXT
    assert cleaned == EXPECTED_TEXT
