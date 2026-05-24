"""Voice-command editing for STT transcripts.

Detects spoken commands embedded in a recording and edits the transcript
before it's pasted. Commands must occupy their own pause-bounded utterance
(Parakeet's silence-gap segmentation handles this - see SentenceConfig).

Supported:
    "scratch that"               - drop the previous content utterance.
    "scratch that N times"       - drop the previous N content utterances.
    "delete last N words"        - drop the last N whitespace tokens from the
                                   surviving text.

N is a digit or number-word one..nine.
"""

import re

# Leading fillers stripped before matching so "uh, scratch that" still fires.
_LEADING_FILLER_RE = re.compile(
    r"^(?:(?:uh|uhh|um|umm|er|erm|okay|ok|so|like)\b[,.\s]*)+",
    re.IGNORECASE,
)
_TRAILING_PUNCT_RE = re.compile(r"[\s.,;:!?]+$")

_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9,
}
_NUM_PATTERN = r"(\d+|one|two|three|four|five|six|seven|eight|nine)"

_SCRATCH_RE = re.compile(
    rf"^scratch that(?:\s+{_NUM_PATTERN}\s+times?)?$",
    re.IGNORECASE,
)
_DELETE_WORDS_RE = re.compile(
    rf"^delete\s+last\s+{_NUM_PATTERN}\s+words?$",
    re.IGNORECASE,
)


def _parse_count(token):
    token = token.lower()
    return int(token) if token.isdigit() else _NUMBER_WORDS.get(token)


def _normalize(text):
    text = _LEADING_FILLER_RE.sub("", text.strip())
    return _TRAILING_PUNCT_RE.sub("", text).strip()


def apply_voice_commands(sentences):
    """Walk pause-bounded utterances in order, apply spoken edits, return text.

    `sentences` is the AlignedSentence list from a Parakeet AlignedResult.
    """
    kept = []

    for sentence in sentences:
        norm = _normalize(sentence.text)

        m = _SCRATCH_RE.match(norm)
        if m:
            n = _parse_count(m.group(1)) if m.group(1) else 1
            if n is None or n < 1:
                kept.append(sentence.text)
                continue
            n = min(n, len(kept))
            if n:
                removed = kept[-n:]
                del kept[-n:]
                for r in removed:
                    print(f'✂️  scratched "{r.strip()}"')
            else:
                print("✂️  scratch ignored (nothing to remove)")
            continue

        m = _DELETE_WORDS_RE.match(norm)
        if m:
            n = _parse_count(m.group(1))
            if n is None or n < 1:
                kept.append(sentence.text)
                continue
            words = "".join(kept).split()
            n = min(n, len(words))
            if n == 0:
                print("✂️  delete-words ignored (no words yet)")
                continue
            dropped = " ".join(words[-n:])
            remaining = words[:-n]
            kept = [" ".join(remaining)] if remaining else []
            print(f'✂️  deleted last {n} words: "{dropped}"')
            continue

        kept.append(sentence.text)

    return "".join(kept).strip()
