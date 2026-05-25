from types import SimpleNamespace

from voice_commands import apply_voice_commands


def sentences(*texts):
    return [SimpleNamespace(text=text) for text in texts]


def test_scratch_that_deletes_previous_utterance():
    result = apply_voice_commands(
        sentences(
            "Use Redis. ",
            "Scratch that. ",
            "Use Postgres.",
        )
    )

    assert result == "Use Postgres."


def test_scratch_that_n_times_stays_literal():
    result = apply_voice_commands(
        sentences(
            "One. ",
            "Two. ",
            "Scratch that 2 times. ",
            "Three.",
        )
    )

    assert result == "One. Two. Scratch that 2 times. Three."


def test_delete_last_n_words_deletes_from_accumulated_text():
    result = apply_voice_commands(
        sentences(
            "The quick brown fox. ",
            "Delete last two words.",
        )
    )

    assert result == "The quick"


def test_delete_last_n_words_preserves_boundary_before_later_speech():
    result = apply_voice_commands(
        sentences(
            "The quick brown fox jumps. ",
            "Delete last two words. ",
            "Then more text.",
        )
    )

    assert result == "The quick brown Then more text."


def test_delete_last_n_words_preserves_utterance_for_later_scratch():
    result = apply_voice_commands(
        sentences(
            "First sentence. ",
            "Second sentence has extra words. ",
            "Delete last two words. ",
            "Scratch that.",
        )
    )

    assert result == "First sentence."


def test_delete_last_n_words_can_span_utterances():
    result = apply_voice_commands(
        sentences(
            "One two. ",
            "Three four. ",
            "Delete last three words.",
        )
    )

    assert result == "One"


def test_scratch_that_inside_normal_utterance_stays_literal():
    result = apply_voice_commands(
        sentences("We should scratch that paragraph from the proposal.")
    )

    assert result == "We should scratch that paragraph from the proposal."


def test_delete_the_last_n_words_is_not_a_command():
    result = apply_voice_commands(
        sentences(
            "The quick brown fox. ",
            "Delete the last two words.",
        )
    )

    assert result == "The quick brown fox. Delete the last two words."
