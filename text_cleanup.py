"""Text cleanup rules for STT transcripts."""

import re

from number_normalization import normalize_numbers

# Word-for-word transcription fixes (case-insensitive, word-boundary match).
WORD_CORRECTIONS = {
    "npxcc usage": "npx ccusage",
    "paragate": "parakeet",
    "para kit": "parakeet",
    "para kate": "parakeet",
    "Shard CN": "shadcn",
    "superbase": "supabase",
}

# Non-lexical hesitation markers - sound placeholders with no lexical meaning.
# Always removed.
HESITATIONS = ("uh", "uhh", "um", "umm", "er", "erm")

# Lexical interjections - carry pragmatic meaning at sentence boundaries
# ("Ah, I see.", "That's nice, eh?"). Only removed when bracketed by , ; :
# on BOTH sides so "thinking, ah, never mind" -> "thinking, never mind".
INTERJECTIONS = ("ah", "ahh", "eh", "ehh", "hm", "hmm")

# Phrases - only removed when followed by , ; : . since they often carry
# meaning in flowing speech ("you know what I mean").
FILLER_PHRASES = ("you know", "i mean")

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
PUNCT_PREFIX = {"at the rate": "@"}


def _space_or_empty(match):
    return "" if match.group(1) == "" else " "


def _punct_space_or_empty(match):
    return match.group(1) + ("" if match.end() == len(match.string) else " ")


_FILLER_PHRASE_RE = re.compile(
    rf"(^|[\s,;:]+)(?:{'|'.join(re.escape(p) for p in FILLER_PHRASES)})\b[,;:.]+(?=\s|$|[!?.,;:])",
    re.IGNORECASE,
)
_HESITATION_RE = re.compile(
    rf"(^|[\s,;:]+)(?:{'|'.join(re.escape(h) for h in HESITATIONS)})\b[,;:.]?(?=\s|$|[!?.,;:])",
    re.IGNORECASE,
)
_INTERJECTION_RE = re.compile(
    rf"([,;:])\s*(?:{'|'.join(re.escape(i) for i in INTERJECTIONS)})\b[,;:]\s*",
    re.IGNORECASE,
)
_TRAILING_SPACE_RE = re.compile(r"\s+([,.;:!?])")
_DUP_PUNCT_RE = re.compile(r"([,;:!?]){2,}")
_MULTI_SPACE_RE = re.compile(r"\s{2,}")


def remove_fillers(text):
    text = _FILLER_PHRASE_RE.sub(_space_or_empty, text)
    text = _HESITATION_RE.sub(_space_or_empty, text)
    text = _INTERJECTION_RE.sub(_punct_space_or_empty, text)
    text = _TRAILING_SPACE_RE.sub(r"\1", text)
    text = _DUP_PUNCT_RE.sub(r"\1", text)
    text = _MULTI_SPACE_RE.sub(" ", text)
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
    text = normalize_numbers(text)
    # Parakeet tacks a sentence-end "." on silence. When the last token is a
    # filename/URL ("...md.", "...tsx.", "...com."), drop that trailing dot.
    # Gated on an extension-like prefix so prose sentences keep their period.
    text = re.sub(r"(\.[a-z0-9]{1,6})\.\s*$", r"\1", text, flags=re.IGNORECASE)
    return text
