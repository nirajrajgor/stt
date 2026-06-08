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
        if 1 <= value <= 31:
            _add_replacement(
                replacements,
                tokens[index].start,
                tokens[end_index - 1].end,
                _ordinal_suffix(value),
            )


def _is_month_token(token):
    return token.lower in MONTHS and token.text[:1].isupper()


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
    return previous.lower in DIGIT_CONTEXTS and _is_context_separator(
        text, previous, tokens[index]
    )


def _add_quantity_replacements(text, tokens, replacements):
    index = 0
    while index < len(tokens) - 1:
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
