"""Text cleanup rules for STT transcripts."""

import re

# Word-for-word transcription fixes (case-insensitive, word-boundary match).
WORD_CORRECTIONS = {
    "npxcc usage": "npx ccusage",
    "paragate": "parakeet",
    "para kit": "parakeet",
    "para kate": "parakeet",
    "Shard CN": "shadcn",
    "superbase": "supabase",
}

# Fillers that should be removed from pasted/saved transcripts. Keep this list
# conservative: words like "like" can be meaningful outside obvious hesitations.
FILLER_PHRASES = (
    "you know",
    "i mean",
)

FILLER_WORDS = (
    "ah",
    "eh",
    "er",
    "erm",
    "hm",
    "uh",
    "uhh",
    "um",
    "umm",
)

# Spoken punctuation that fuses tokens on BOTH sides - eats whitespace before
# and after, e.g. "search hyphen bar dot tsx" -> "search-bar.tsx".
PUNCT_FUSE = {
    "hyphen": "-",
    "underscore": "_",
    "dot": ".",
    "comma": ",",
    "slash": "/",
}

# Spoken punctuation that only fuses to the FOLLOWING token - preserves the
# leading space so "again at the rate transcription dot md" becomes
# "again @transcription.md", not "again@transcription.md".
PUNCT_PREFIX = {
    "at the rate": "@",
}


def remove_fillers(text):
    for filler in FILLER_PHRASES:
        text = re.sub(
            rf"(^|[\s,;:]+){re.escape(filler)}\b[,;:.]+(?=\s|$|[!?.,;:])",
            lambda match: "" if match.group(1) == "" else " ",
            text,
            flags=re.IGNORECASE,
        )
    for filler in FILLER_WORDS:
        text = re.sub(
            rf"(^|[\s,;:]+){re.escape(filler)}\b[,;:.]?(?=\s|$|[!?.,;:])",
            lambda match: "" if match.group(1) == "" else " ",
            text,
            flags=re.IGNORECASE,
        )
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"([,;:!?]){2,}", r"\1", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip(" ,;:")


def apply_corrections(text):
    for wrong, right in WORD_CORRECTIONS.items():
        text = re.sub(rf"\b{re.escape(wrong)}\b", right, text, flags=re.IGNORECASE)
    for wrong, right in PUNCT_FUSE.items():
        # [,.;]? eats the stray comma/period Parakeet adds when the speaker
        # pauses after a punctuation word (e.g. "at the rate, transcription.md"
        # -> "@transcription.md" instead of "@, transcription.md").
        text = re.sub(
            rf"\s*\b{re.escape(wrong)}\b[,.;]?\s*",
            right,
            text,
            flags=re.IGNORECASE,
        )
    for wrong, right in PUNCT_PREFIX.items():
        text = re.sub(
            rf"\b{re.escape(wrong)}\b[,.;]?\s*",
            right,
            text,
            flags=re.IGNORECASE,
        )
    text = remove_fillers(text)
    # Parakeet tacks a sentence-end "." on silence. When the last token is a
    # filename/URL ("...md.", "...tsx.", "...com."), drop that trailing dot.
    # Gated on an extension-like prefix so prose sentences keep their period.
    text = re.sub(r"(\.[a-z0-9]{1,6})\.\s*$", r"\1", text, flags=re.IGNORECASE)
    return text
