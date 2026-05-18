"""Tests for text_cleanup. Run with: python3 test_text_cleanup.py"""

from text_cleanup import apply_corrections, remove_fillers

REMOVE_FILLERS_CASES = [
    # Hesitations - always removed
    ("um this is fine", "this is fine"),
    ("well, uh, let me think", "well let me think"),
    ("uh", ""),
    ("this is um a test", "this is a test"),
    ("Um, hello", "hello"),
    ("UH OH", "OH"),
    ("the umbrella is uh red", "the umbrella is red"),
    ("her err was, um, big", "her err was big"),
    ("erm, erm, erm.", ""),
    ("um. uh. er.", ""),
    ("say um.", "say"),
    ("    leading spaces um here", "leading spaces here"),
    # Words not in any list - left alone
    ("uhm not in list", "uhm not in list"),
    ("uh-huh okay", "uh-huh okay"),
    # Interjections at sentence boundaries - PRESERVED (the main point-3 fix)
    ("Ah, I see what you mean.", "Ah, I see what you mean."),
    ("Hm, interesting.", "Hm, interesting."),
    ("Eh, maybe.", "Eh, maybe."),
    ("That's nice, eh?", "That's nice, eh?"),
    ("Ah ha ha!", "Ah ha ha!"),
    ("Hm.", "Hm."),
    # Interjections bracketed by punctuation on both sides - REMOVED
    ("thinking, ah, never mind", "thinking, never mind"),
    ("yes, hm, maybe", "yes, maybe"),
    ("so, eh, whatever", "so, whatever"),
    ("I went to the store, ah, and got milk.", "I went to the store, and got milk."),
    # Filler phrases - only removed with trailing punctuation
    ("you know what I mean", "you know what I mean"),
    ("well, you know, fine", "well fine"),
    # Empty and no-op
    ("", ""),
    ("no fillers here at all", "no fillers here at all"),
]

APPLY_CORRECTIONS_CASES = [
    ("paragate is great", "parakeet is great"),
    ("search hyphen bar dot tsx", "search-bar.tsx"),
    ("again at the rate transcription dot md", "again @transcription.md"),
    ("see file dot md.", "see file.md"),
    ("um at the rate file dot md", "@file.md"),
]


def run(name, fn, cases):
    fails = []
    for input_text, expected in cases:
        actual = fn(input_text)
        if actual != expected:
            fails.append((input_text, expected, actual))
    if fails:
        print(f"{name}: {len(fails)}/{len(cases)} FAILED")
        for input_text, expected, actual in fails:
            print(f"  input    = {input_text!r}")
            print(f"  expected = {expected!r}")
            print(f"  actual   = {actual!r}")
    else:
        print(f"{name}: {len(cases)}/{len(cases)} passed")
    return len(fails)


if __name__ == "__main__":
    total_fails = 0
    total_fails += run("remove_fillers", remove_fillers, REMOVE_FILLERS_CASES)
    total_fails += run("apply_corrections", apply_corrections, APPLY_CORRECTIONS_CASES)
    raise SystemExit(1 if total_fails else 0)
