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


def test_scratch_that_n_times_deletes_previous_n_utterances():
    result = apply_voice_commands(
        sentences(
            "One. ",
            "Two. ",
            "Scratch that 2 times. ",
            "Three.",
        )
    )

    assert result == "Three."


def test_delete_last_n_words_deletes_from_accumulated_text():
    result = apply_voice_commands(
        sentences(
            "The quick brown fox. ",
            "Delete last two words.",
        )
    )

    assert result == "The quick"


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
