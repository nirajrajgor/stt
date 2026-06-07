from text_cleanup import apply_corrections


def test_digit_sequences_normalize_with_context():
    assert apply_corrections("code one two three four") == "code 1234"
    assert apply_corrections("pin: zero one zero five") == "pin: 0105"
    assert apply_corrections("order number, one oh five") == "order number, 105"


def test_digit_sequences_do_not_normalize_without_context():
    assert apply_corrections("one two three four") == "one two three four"
    assert apply_corrections("one more thing") == "one more thing"


def test_quantities_normalize_for_allowlisted_units():
    assert apply_corrections("twenty five dollars") == "25 dollars"
    assert apply_corrections("six files") == "6 files"
    assert apply_corrections("three gigabytes") == "3 gigabytes"


def test_ambiguous_prose_stays_unchanged():
    assert apply_corrections("wait a second") == "wait a second"
    assert apply_corrections("first we need to") == "first we need to"
    assert apply_corrections("one more thing") == "one more thing"
    assert apply_corrections("one day I will fix it") == "one day I will fix it"
    assert apply_corrections("give me one minute") == "give me one minute"
    assert apply_corrections("this took one hour") == "this took one hour"


def test_month_dates_normalize_ordinals():
    assert apply_corrections("July twenty eighth") == "July 28th"
    assert apply_corrections("May first") == "May 1st"
    assert apply_corrections("June first.") == "June 1st."
    assert apply_corrections("today is first May") == "today is 1st May"


def test_month_dates_require_capitalized_months():
    assert apply_corrections("we may first need to refactor") == (
        "we may first need to refactor"
    )
    assert apply_corrections("I may second guess that") == "I may second guess that"
    assert apply_corrections("in march third quarter results") == (
        "in march third quarter results"
    )


def test_times_normalize_with_clear_context():
    assert apply_corrections("at three thirty PM") == "at 3:30 PM"
    assert apply_corrections("meeting at nine fifteen") == "meeting at 9:15"
    assert apply_corrections("at three oh five PM") == "at 3:05 PM"


def test_times_do_not_normalize_without_clear_context():
    assert apply_corrections("three thirty files") == "three thirty files"
    assert apply_corrections("meeting nine fifteen") == "meeting nine fifteen"
    assert apply_corrections("there were around three forty five people") == (
        "there were around three forty five people"
    )
    assert apply_corrections("it grew by ten fifteen percent") == (
        "it grew by ten fifteen percent"
    )
    assert apply_corrections("after one thirty of them left") == (
        "after one thirty of them left"
    )


def test_number_normalization_runs_after_existing_cleanup():
    assert apply_corrections("um code one two three") == "code 123"
