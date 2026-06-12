"""Pin the splitting semantics behind the utterance_gap setting.

[settings] utterance_gap feeds SentenceConfig.silence_gap, where a pause
between words >= the gap starts a new chunk. These tests call parakeet's
pure splitting function with hand-made timestamps, so a library change to
the gap semantics fails fast here without loading the model.

This pins library behavior only; that stt.py actually passes the configured
value into SentenceConfig is asserted separately once transcribe() moves to
an importable module.

Marked e2e: importing parakeet_mlx loads the native MLX runtime, which is
unsafe at collection time and unavailable on some machines.
"""

import pytest

pytestmark = pytest.mark.e2e

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
