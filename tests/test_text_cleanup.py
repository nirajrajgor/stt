from text_cleanup import apply_corrections


def test_digit_sequences_normalize_with_context():
    assert apply_corrections("code one two three four") == "code 1234"
    assert apply_corrections("pin: zero one zero five") == "pin: 0105"
    assert apply_corrections("order number, one oh five") == "order number, 105"
    assert apply_corrections("ticket number two three four") == (
        "ticket number 234"
    )
    assert apply_corrections("tracking number one two three") == (
        "tracking number 123"
    )


def test_digit_sequences_do_not_normalize_without_context():
    assert apply_corrections("one two three four") == "one two three four"
    assert apply_corrections("one more thing") == "one more thing"
    assert apply_corrections("number two three combo") == "number two three combo"
    assert apply_corrections("we ranked number two three four") == (
        "we ranked number two three four"
    )


def test_quantities_normalize_for_allowlisted_units():
    assert apply_corrections("twenty five dollars") == "25 dollars"
    assert apply_corrections("six files") == "6 files"
    assert apply_corrections("three gigabytes") == "3 gigabytes"
    assert apply_corrections("one hundred twenty five dollars") == "125 dollars"
    assert apply_corrections("two thousand dollars") == "2000 dollars"
    assert apply_corrections("two point five percent") == "2.5 percent"
    assert apply_corrections("one point five gigabytes") == "1.5 gigabytes"
    assert apply_corrections("one thing. ten files") == "one thing. 10 files"


def test_quantities_do_not_strand_articles_before_magnitudes():
    assert apply_corrections("a hundred dollars") == "a hundred dollars"
    assert apply_corrections("a thousand dollars") == "a thousand dollars"
    assert apply_corrections("a million dollars") == "a million dollars"
    assert apply_corrections("a hundred twenty five dollars") == (
        "a hundred twenty five dollars"
    )
    assert apply_corrections("a hundred and twenty dollars") == (
        "a hundred and twenty dollars"
    )
    assert apply_corrections("a few hundred megabytes") == (
        "a few hundred megabytes"
    )
    assert apply_corrections("a hundred reasons cost twenty dollars") == (
        "a hundred reasons cost 20 dollars"
    )


def test_quantities_do_not_convert_tails_of_larger_number_phrases():
    assert apply_corrections("we need five to ten files") == (
        "we need five to ten files"
    )
    assert apply_corrections("between two and three gigabytes") == (
        "between two and three gigabytes"
    )
    assert apply_corrections("save four or five files") == (
        "save four or five files"
    )
    assert apply_corrections("nineteen ninety nine dollars") == (
        "nineteen ninety nine dollars"
    )
    assert apply_corrections("one oh one dollars") == "one oh one dollars"


def test_ambiguous_prose_stays_unchanged():
    assert apply_corrections("wait a second") == "wait a second"
    assert apply_corrections("first we need to") == "first we need to"
    assert apply_corrections("one more thing") == "one more thing"
    assert apply_corrections("one day I will fix it") == "one day I will fix it"
    assert apply_corrections("give me one minute") == "give me one minute"
    assert apply_corrections("this took one hour") == "this took one hour"


def test_month_dates_normalize_ordinals():
    assert apply_corrections("July twenty eighth") == "July 28th"
    assert apply_corrections("July thirty first") == "July 31st"
    assert apply_corrections("May first") == "May 1st"
    assert apply_corrections("June first.") == "June 1st."
    assert apply_corrections("today is first May") == "today is 1st May"
    assert apply_corrections("first May, we launch") == "1st May, we launch"
    assert apply_corrections("today is twenty eighth May") == "today is 28th May"


def test_month_dates_normalize_years():
    assert apply_corrections("June twenty twenty six") == "June 2026"
    assert apply_corrections("June eighth twenty twenty six") == "June 8th 2026"
    assert apply_corrections("June eighth two thousand twenty six") == (
        "June 8th 2026"
    )
    assert apply_corrections("today is eighth June twenty twenty six") == (
        "today is 8th June 2026"
    )


def test_month_dates_require_capitalized_months():
    assert apply_corrections("we may first need to refactor") == (
        "we may first need to refactor"
    )
    assert apply_corrections("I may second guess that") == "I may second guess that"
    assert apply_corrections("in march third quarter results") == (
        "in march third quarter results"
    )


def test_ordinal_month_dates_do_not_rewrite_adjective_phrases():
    assert apply_corrections("our first March meeting went well") == (
        "our first March meeting went well"
    )
    assert apply_corrections("the first January snowfall was heavy") == (
        "the first January snowfall was heavy"
    )
    assert apply_corrections("this is the second August in a row") == (
        "this is the second August in a row"
    )


def test_times_normalize_with_clear_context():
    assert apply_corrections("at three thirty PM") == "at 3:30 PM"
    assert apply_corrections("meeting at nine fifteen") == "meeting at 9:15"
    assert apply_corrections("tomorrow at five ten") == "tomorrow at 5:10"
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
    assert apply_corrections("look at three thirty page documents") == (
        "look at three thirty page documents"
    )
    assert apply_corrections("staring at twelve fifteen year olds") == (
        "staring at twelve fifteen year olds"
    )
    assert apply_corrections("at five ten the deal closed") == (
        "at five ten the deal closed"
    )


def test_overlapping_number_false_positives_stay_literal():
    assert apply_corrections("three thirty files") == "three thirty files"
    assert apply_corrections("it grew by ten fifteen percent") == (
        "it grew by ten fifteen percent"
    )
    assert apply_corrections("one oh one dollars") == "one oh one dollars"
    assert apply_corrections("we need five to ten files") == (
        "we need five to ten files"
    )
    assert apply_corrections("a hundred dollars") == "a hundred dollars"


def test_number_normalization_runs_after_existing_cleanup():
    assert apply_corrections("um code one two three") == "code 123"
