"""Tests for transcriber.py: wiring, end-to-end transcription, and the
splitting semantics behind the utterance_gap setting.

Marked e2e: importing transcriber or parakeet_mlx loads the native MLX
runtime (Apple Silicon + Metal only; aborts in sandboxes), and the clip
test loads the Parakeet model.
"""

import wave
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

FIXTURE = Path(__file__).with_name("fixtures") / "spoken-input.wav"

EXPECTED_TEXT = (
    "Create a short summary from this meeting note and list the next action items."
)


def _load_fixture():
    import numpy as np

    with wave.open(str(FIXTURE), "rb") as wf:
        assert wf.getframerate() == 16000
        assert wf.getnchannels() == 1
        audio = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
    return audio.astype(np.float32) / 32768.0


def test_settings_reach_decoding_config():
    """Wiring: the configured utterance_gap must land in SentenceConfig.

    Catches a hardcoded gap that config parsing tests and the splitting
    tests below would both miss.
    """
    import config
    from transcriber import Transcriber

    transcriber = Transcriber(config.Settings(utterance_gap=1.3))

    assert transcriber.decoding_config.sentence.silence_gap == 1.3


def test_known_clip_transcribes_to_expected_text():
    import config
    from transcriber import Transcriber

    transcriber = Transcriber(config.Settings())
    transcriber.load_model()
    raw, cleaned = transcriber.transcribe(_load_fixture())

    assert raw == EXPECTED_TEXT
    assert cleaned == EXPECTED_TEXT


# --- utterance_gap splitting semantics ---
#
# A pause between words >= the gap starts a new chunk. These tests call
# parakeet's pure splitting function with hand-made timestamps, so a library
# change to the gap semantics fails fast here without loading the model.
# They pin library behavior only; test_settings_reach_decoding_config above
# covers that the configured value actually reaches SentenceConfig.

PAUSE = 1.5


def _token(idx, text, start, end):
    from parakeet_mlx.alignment import AlignedToken

    return AlignedToken(id=idx, text=text, start=start, duration=end - start)


def _tokens_with_pause(pause=PAUSE):
    """hello [pause] world again — no punctuation, so only the gap can split."""
    return [
        _token(0, "hello", 0.0, 0.5),
        _token(1, " world", 0.5 + pause, 1.0 + pause),
        _token(2, " again", 1.1 + pause, 1.5 + pause),
    ]


def _split(silence_gap):
    from parakeet_mlx.alignment import SentenceConfig, tokens_to_sentences

    return tokens_to_sentences(
        _tokens_with_pause(), SentenceConfig(silence_gap=silence_gap)
    )


def test_gap_smaller_than_pause_splits():
    assert [s.text.strip() for s in _split(0.7)] == ["hello", "world again"]


def test_gap_larger_than_pause_keeps_one_chunk():
    assert [s.text.strip() for s in _split(3.0)] == ["hello world again"]


def test_pause_equal_to_gap_splits():
    assert len(_split(PAUSE)) == 2
