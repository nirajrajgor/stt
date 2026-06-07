"""Conservative English number normalization for STT transcripts."""

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class WordToken:
    text: str
    lower: str
    start: int
    end: int


_WORD_RE = re.compile(r"[A-Za-z]+")

DIGIT_WORDS = {
    "zero": "0",
    "oh": "0",
    "o": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
}

CARDINAL_ONES = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}

CARDINAL_TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}

ORDINAL_ONES = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
    "tenth": 10,
    "eleventh": 11,
    "twelfth": 12,
    "thirteenth": 13,
    "fourteenth": 14,
    "fifteenth": 15,
    "sixteenth": 16,
    "seventeenth": 17,
    "eighteenth": 18,
    "nineteenth": 19,
}

ORDINAL_TENS = {
    "twentieth": 20,
    "thirtieth": 30,
}

MONTHS = {
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
}

DIGIT_CONTEXTS = {"code", "pin", "otp", "zip", "number"}

QUANTITY_UNITS = {
    "cent",
    "cents",
    "dollar",
    "dollars",
    "file",
    "files",
    "gigabyte",
    "gigabytes",
    "megabyte",
    "megabytes",
    "percent",
    "percentage",
}

TIME_CONTEXTS = {"at"}
AM_PM = {"am", "pm"}


def normalize_numbers(text):
    tokens = _word_tokens(text)
    replacements = []

    _add_date_replacements(text, tokens, replacements)
    _add_time_replacements(text, tokens, replacements)
    _add_digit_sequence_replacements(text, tokens, replacements)
    _add_quantity_replacements(text, tokens, replacements)

    return _apply_replacements(text, replacements)


def _word_tokens(text):
    return [
        WordToken(match.group(0), match.group(0).lower(), match.start(), match.end())
        for match in _WORD_RE.finditer(text)
    ]


def _separator(text, left, right):
    return text[left.end : right.start]


def _is_phrase_separator(text, left, right):
    return bool(re.fullmatch(r"[\s-]+", _separator(text, left, right)))


def _is_context_separator(text, left, right):
    return bool(re.fullmatch(r"[\s,;:-]+", _separator(text, left, right)))


def _parse_cardinal(text, tokens, index):
    if index >= len(tokens):
        return None

    word = tokens[index].lower
    if word in CARDINAL_ONES:
        return CARDINAL_ONES[word], index + 1

    if word not in CARDINAL_TENS:
        return None

    value = CARDINAL_TENS[word]
    next_index = index + 1
    if (
        next_index < len(tokens)
        and tokens[next_index].lower in CARDINAL_ONES
        and 0 < CARDINAL_ONES[tokens[next_index].lower] < 10
        and _is_phrase_separator(text, tokens[index], tokens[next_index])
    ):
        value += CARDINAL_ONES[tokens[next_index].lower]
        next_index += 1
    return value, next_index


def _parse_ordinal(text, tokens, index):
    if index >= len(tokens):
        return None

    word = tokens[index].lower
    if word in ORDINAL_ONES:
        return ORDINAL_ONES[word], index + 1
    if word in ORDINAL_TENS:
        return ORDINAL_TENS[word], index + 1

    next_index = index + 1
    if (
        word in CARDINAL_TENS
        and next_index < len(tokens)
        and tokens[next_index].lower in ORDINAL_ONES
        and 0 < ORDINAL_ONES[tokens[next_index].lower] < 10
        and _is_phrase_separator(text, tokens[index], tokens[next_index])
    ):
        return CARDINAL_TENS[word] + ORDINAL_ONES[tokens[next_index].lower], index + 2

    return None


def _ordinal_suffix(value):
    if 10 <= value % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
    return f"{value}{suffix}"


def _add_date_replacements(text, tokens, replacements):
    for index, token in enumerate(tokens[:-1]):
        if not _is_month_token(token):
            continue
        if not _is_phrase_separator(text, token, tokens[index + 1]):
            continue
        ordinal = _parse_ordinal(text, tokens, index + 1)
        if not ordinal:
            continue
        value, end_index = ordinal
        if 1 <= value <= 31:
            start = tokens[index + 1].start
            end = tokens[end_index - 1].end
            _add_replacement(replacements, start, end, _ordinal_suffix(value))

    for index in range(len(tokens) - 1):
        if not _is_month_token(tokens[index + 1]):
            continue
        if not _is_phrase_separator(text, tokens[index], tokens[index + 1]):
            continue
        ordinal = _parse_ordinal(text, tokens, index)
        if not ordinal:
            continue
        value, end_index = ordinal
        if end_index == index + 1 and 1 <= value <= 31:
            _add_replacement(
                replacements,
                tokens[index].start,
                tokens[index].end,
                _ordinal_suffix(value),
            )


def _is_month_token(token):
    return token.lower in MONTHS and token.text[:1].isupper()


def _add_time_replacements(text, tokens, replacements):
    for index in range(len(tokens) - 1):
        hour = _parse_time_hour(text, tokens, index)
        if hour is None:
            continue
        if not _is_phrase_separator(text, tokens[index], tokens[index + 1]):
            continue

        minute = _parse_time_minute(text, tokens, index + 1)
        if not minute:
            continue
        minute_value, end_index = minute
        if not (0 <= minute_value <= 59):
            continue

        has_time_context = _has_time_context(tokens, index, end_index)
        if not has_time_context:
            continue

        replacement = f"{hour}:{minute_value:02d}"
        _add_replacement(
            replacements,
            tokens[index].start,
            tokens[end_index - 1].end,
            replacement,
        )


def _parse_time_hour(text, tokens, index):
    parsed = _parse_cardinal(text, tokens, index)
    if not parsed:
        return None
    value, end_index = parsed
    if end_index != index + 1 or not (1 <= value <= 12):
        return None
    return value


def _parse_time_minute(text, tokens, index):
    if index >= len(tokens):
        return None

    word = tokens[index].lower
    if word in {"oh", "o", "zero"}:
        next_index = index + 1
        if (
            next_index < len(tokens)
            and tokens[next_index].lower in CARDINAL_ONES
            and _is_phrase_separator(text, tokens[index], tokens[next_index])
        ):
            value = CARDINAL_ONES[tokens[next_index].lower]
            if 0 <= value <= 9:
                return value, index + 2

    return _parse_cardinal(text, tokens, index)


def _has_time_context(tokens, start_index, end_index):
    if start_index > 0 and tokens[start_index - 1].lower in TIME_CONTEXTS:
        return True
    if end_index < len(tokens) and tokens[end_index].lower in AM_PM:
        return True
    return False


def _add_digit_sequence_replacements(text, tokens, replacements):
    index = 0
    while index < len(tokens):
        if not _has_digit_context(text, tokens, index):
            index += 1
            continue

        end_index = index
        digits = []
        while end_index < len(tokens) and tokens[end_index].lower in DIGIT_WORDS:
            if end_index > index and not _is_context_separator(
                text, tokens[end_index - 1], tokens[end_index]
            ):
                break
            digits.append(DIGIT_WORDS[tokens[end_index].lower])
            end_index += 1

        if len(digits) >= 2:
            _add_replacement(
                replacements,
                tokens[index].start,
                tokens[end_index - 1].end,
                "".join(digits),
            )
            index = end_index
        else:
            index += 1


def _has_digit_context(text, tokens, index):
    if index == 0:
        return False

    previous = tokens[index - 1]
    return previous.lower in DIGIT_CONTEXTS and _is_context_separator(
        text, previous, tokens[index]
    )


def _add_quantity_replacements(text, tokens, replacements):
    index = 0
    while index < len(tokens) - 1:
        parsed = _parse_cardinal(text, tokens, index)
        if not parsed:
            index += 1
            continue
        if _looks_like_ungated_time_tail(text, tokens, index):
            index += 1
            continue

        value, end_index = parsed
        if (
            end_index < len(tokens)
            and tokens[end_index].lower in QUANTITY_UNITS
            and 0 <= value <= 99
            and _is_phrase_separator(text, tokens[end_index - 1], tokens[end_index])
        ):
            _add_replacement(
                replacements,
                tokens[index].start,
                tokens[end_index - 1].end,
                str(value),
            )
            index = end_index
        else:
            index += 1


def _looks_like_ungated_time_tail(text, tokens, index):
    if index == 0:
        return False
    previous_hour = _parse_time_hour(text, tokens, index - 1)
    minute = _parse_time_minute(text, tokens, index)
    return (
        previous_hour is not None
        and minute is not None
        and 0 <= minute[0] <= 59
        and _is_phrase_separator(text, tokens[index - 1], tokens[index])
    )


def _add_replacement(replacements, start, end, replacement):
    if any(
        start < old_end and end > old_start for old_start, old_end, _ in replacements
    ):
        return
    replacements.append((start, end, replacement))


def _apply_replacements(text, replacements):
    if not replacements:
        return text

    result = []
    last = 0
    for start, end, replacement in sorted(replacements):
        result.append(text[last:start])
        result.append(replacement)
        last = end
    result.append(text[last:])
    return "".join(result)
