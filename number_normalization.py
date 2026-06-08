"""Conservative English number normalization for STT transcripts."""

from dataclasses import dataclass
import re

from text_to_num import alpha2digit


@dataclass(frozen=True)
class WordToken:
    text: str
    lower: str
    start: int
    end: int


_WORD_RE = re.compile(r"[A-Za-z]+")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_ORDINAL_RE = re.compile(r"(\d+)(st|nd|rd|th)")

DIGITS = {
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
NUMBER_WORDS = set(DIGITS) | {
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy",
    "eighty",
    "ninety",
    "hundred",
    "thousand",
    "million",
    "billion",
    "trillion",
}
NUMBER_TAIL_CONNECTORS = {"and", "or", "to"}

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

DIGIT_CONTEXTS = {"code", "pin", "otp", "zip"}
DIGIT_NUMBER_PREFIXES = {
    "case",
    "confirmation",
    "invoice",
    "order",
    "reference",
    "ticket",
    "tracking",
}

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
BARE_MAGNITUDES = {"hundred", "thousand", "million", "billion", "trillion"}
QUANTITY_PREFIX_BLOCKERS = {"a", "an", "couple", "few", "several"}

TIME_PREPOSITIONS = {"at"}
TIME_LEAD_CONTEXTS = {
    "appointment",
    "appt",
    "begin",
    "began",
    "begins",
    "call",
    "deadline",
    "depart",
    "departs",
    "departure",
    "dinner",
    "due",
    "end",
    "ended",
    "ends",
    "flight",
    "interview",
    "lunch",
    "meet",
    "meeting",
    "reservation",
    "schedule",
    "scheduled",
    "standup",
    "start",
    "started",
    "starts",
    "today",
    "tomorrow",
    "tonight",
    "train",
}
WEEKDAYS = {
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
}
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


def _digit_for_word(word):
    return DIGITS.get(word)


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
        ordinal = _parse_ordinal_phrase(text, tokens, index + 1)
        if not ordinal:
            continue
        value, end_index = ordinal
        if 1 <= value <= 31:
            start = tokens[index + 1].start
            end = tokens[end_index - 1].end
            _add_replacement(replacements, start, end, _ordinal_suffix(value))

    for index in range(len(tokens)):
        ordinal = _parse_ordinal_phrase(text, tokens, index)
        if not ordinal:
            continue
        value, end_index = ordinal
        if end_index >= len(tokens) or not _is_month_token(tokens[end_index]):
            continue
        if not _is_phrase_separator(text, tokens[end_index - 1], tokens[end_index]):
            continue
        if not _month_ends_date_phrase(text, tokens, end_index):
            continue
        if 1 <= value <= 31:
            _add_replacement(
                replacements,
                tokens[index].start,
                tokens[end_index - 1].end,
                _ordinal_suffix(value),
            )


def _is_month_token(token):
    return token.lower in MONTHS and token.text[:1].isupper()


def _month_ends_date_phrase(text, tokens, month_index):
    month = tokens[month_index]
    if month_index + 1 >= len(tokens):
        return True
    next_token = tokens[month_index + 1]
    return bool(re.fullmatch(r"\s*[,.;:!?]+\s*", text[month.end : next_token.start]))


def _parse_ordinal_phrase(text, tokens, index):
    max_end = min(len(tokens), index + 5)
    for end_index in range(max_end, index, -1):
        phrase = _token_phrase(text, tokens, index, end_index)
        if phrase is None:
            continue
        normalized = _alpha2digit(phrase)
        match = _ORDINAL_RE.fullmatch(normalized)
        if match:
            return int(match.group(1)), end_index
    return None


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
    parsed = _parse_number_phrase(text, tokens, index, max_words=1)
    if not parsed:
        return None
    value, end_index = parsed
    if not (1 <= value <= 12):
        return None
    return value


def _parse_time_minute(text, tokens, index):
    if index >= len(tokens):
        return None

    word = tokens[index].lower
    if word in {"oh", "o", "zero"}:
        next_index = index + 1
        digit = (
            _digit_for_word(tokens[next_index].lower)
            if next_index < len(tokens)
            else None
        )
        if (
            digit is not None
            and _is_phrase_separator(text, tokens[index], tokens[next_index])
        ):
            return int(digit), index + 2

    return _parse_number_phrase(text, tokens, index, max_words=2)


def _has_time_context(tokens, start_index, end_index):
    if end_index < len(tokens) and tokens[end_index].lower in AM_PM:
        return True
    if _has_bare_time_context(tokens, start_index):
        return True
    return False


def _has_bare_time_context(tokens, start_index):
    at_index = start_index - 1
    if at_index <= 0 or tokens[at_index].lower not in TIME_PREPOSITIONS:
        return False

    lead = tokens[at_index - 1].lower
    return lead in TIME_LEAD_CONTEXTS or lead in WEEKDAYS


def _add_digit_sequence_replacements(text, tokens, replacements):
    index = 0
    while index < len(tokens):
        if not _has_digit_context(text, tokens, index):
            index += 1
            continue

        end_index = index
        digits = []
        while end_index < len(tokens):
            digit = _digit_for_word(tokens[end_index].lower)
            if digit is None:
                break
            if end_index > index and not _is_context_separator(
                text, tokens[end_index - 1], tokens[end_index]
            ):
                break
            digits.append(digit)
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
    if not _is_context_separator(text, previous, tokens[index]):
        return False
    if previous.lower in DIGIT_CONTEXTS:
        return True
    return _has_identifier_number_context(text, tokens, index - 1)


def _has_identifier_number_context(text, tokens, number_index):
    if number_index == 0 or tokens[number_index].lower != "number":
        return False

    lead = tokens[number_index - 1]
    return lead.lower in DIGIT_NUMBER_PREFIXES and _is_context_separator(
        text, lead, tokens[number_index]
    )


def _add_quantity_replacements(text, tokens, replacements):
    index = 0
    while index < len(tokens) - 1:
        skip_end = _blocked_quantity_skip_end(text, tokens, index)
        if skip_end is not None:
            index = skip_end
            continue

        replacement = _parse_quantity_phrase(text, tokens, index)
        if not replacement:
            index += 1
            continue

        end_index, normalized = replacement
        _add_replacement(
            replacements,
            tokens[index].start,
            tokens[end_index - 1].end,
            normalized,
        )
        index = end_index


def _parse_quantity_phrase(text, tokens, index):
    if _looks_like_ungated_time_tail(text, tokens, index):
        return None
    if _looks_like_number_phrase_tail(text, tokens, index):
        return None
    if _has_blocked_bare_magnitude_prefix(tokens, index):
        return None

    max_unit_index = min(len(tokens), index + 8)
    for unit_index in range(index + 1, max_unit_index):
        if tokens[unit_index].lower not in QUANTITY_UNITS:
            continue
        if not _is_phrase_separator(text, tokens[unit_index - 1], tokens[unit_index]):
            continue

        phrase = _token_phrase(text, tokens, index, unit_index)
        if phrase is None:
            continue
        normalized = _normalize_number_phrase(phrase)
        if normalized is not None:
            return unit_index, normalized
    return None


def _looks_like_number_phrase_tail(text, tokens, index):
    if tokens[index].lower not in NUMBER_WORDS:
        return False
    if index == 0:
        return False

    previous = tokens[index - 1]
    if previous.lower in NUMBER_WORDS and _is_phrase_separator(
        text, previous, tokens[index]
    ):
        return True

    if index < 2 or previous.lower not in NUMBER_TAIL_CONNECTORS:
        return False

    before_previous = tokens[index - 2]
    return (
        before_previous.lower in NUMBER_WORDS
        and _is_phrase_separator(text, before_previous, previous)
        and _is_phrase_separator(text, previous, tokens[index])
    )


def _blocked_quantity_skip_end(text, tokens, index):
    if not _has_blocked_bare_magnitude_prefix(tokens, index):
        return None

    max_unit_index = min(len(tokens), index + 8)
    for unit_index in range(index + 1, max_unit_index):
        if tokens[unit_index].lower not in QUANTITY_UNITS:
            continue
        if not _is_phrase_separator(text, tokens[unit_index - 1], tokens[unit_index]):
            continue

        phrase = _token_phrase(text, tokens, index, unit_index)
        if phrase is not None and _normalize_number_phrase(phrase) is not None:
            return unit_index + 1
    return None


def _has_blocked_bare_magnitude_prefix(tokens, index):
    return (
        index > 0
        and tokens[index].lower in BARE_MAGNITUDES
        and tokens[index - 1].lower in QUANTITY_PREFIX_BLOCKERS
    )


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


def _parse_number_phrase(text, tokens, index, max_words):
    max_end = min(len(tokens), index + max_words)
    for end_index in range(max_end, index, -1):
        phrase = _token_phrase(text, tokens, index, end_index)
        if phrase is None:
            continue
        normalized = _normalize_number_phrase(phrase)
        if normalized is not None and "." not in normalized:
            return int(normalized), end_index
    return None


def _normalize_number_phrase(phrase):
    normalized = _alpha2digit(phrase)
    if _NUMBER_RE.fullmatch(normalized):
        return normalized
    return None


def _alpha2digit(phrase):
    return alpha2digit(phrase, "en", threshold=0)


def _token_phrase(text, tokens, start_index, end_index):
    if start_index >= end_index:
        return None
    for index in range(start_index, end_index - 1):
        if not _is_phrase_separator(text, tokens[index], tokens[index + 1]):
            return None
    return text[tokens[start_index].start : tokens[end_index - 1].end]


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
