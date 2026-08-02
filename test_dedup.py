"""Unit test for hardened character dedup + person title events."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.resolve()))
import system_breakers as sb

CASES = [
    # (shots characters in order, expected unique characters)
    (["IRWIN", "Jessy Irwin", "J. Irwin", "irwin"], {"Jessy Irwin"}),
    (["IRS", "I.R.S.", "the IRS"], {"IRS"}),                 # acronym variants
    (["MARK", "Mark", "mark"], {"Mark"}),                    # case variants
    (["Stefan Mandel", "Mandel", "STEFAN MANDEL", "Dr. Stefan Mandel"], {"Stefan Mandel"}),
    (["John Smith", "John", "Smith"], {"John Smith"}),
    (["Luke Moore", "Moore", "Mr. Moore"], {"Luke Moore"}),
    (["Bank Officer", "the bank officer", "BANK OFFICER"], {"Bank Officer"}),
    (["Bob", "Robert", "Bobby"], {"Bob", "Robert", "Bobby"}),  # no over-merge
    (["John Smith", "John Doe"], {"John Smith", "John Doe"}),  # no over-merge
    (["Smith", "John Smith", "John"], {"John Smith"}),
]
allok = True
for chars, expected in CASES:
    shots = [{"character": c} for c in chars]
    canon = sb._character_canonical_map(shots)
    merged = sb._merge_character_aliases(shots)
    unique = sorted({s["character"] for s in merged})
    ok = set(unique) == expected
    allok &= ok
    print(f"{'PASS' if ok else 'FAIL'} {chars}")
    if not ok:
        print(f"     -> got {unique}, expected {sorted(expected)}")

# person events from fake shots (with tts durations irrelevant - clip_starts given)
fake = [
    {"character": "IRWIN", "narration_idx": 0, "is_chapter": False},
    {"character": "Jessy Irwin", "narration_idx": 1, "is_chapter": False},
    {"character": "NONE", "narration_idx": 2, "is_chapter": False},
    {"character": "Stefan Mandel", "narration_idx": 3, "is_chapter": False},
    {"character": "MANDEL", "narration_idx": 4, "is_chapter": False},
    {"character": "NONE", "narration_idx": 5, "is_chapter": True},
]
starts = [0.0, 10.0, 20.0, 30.0, 40.0, 50.0]
pe = sb._build_person_events(fake, starts)
print("\nPERSON EVENTS:")
for e in pe:
    print(f"  [{e['kind']}] '{e['text']}' para={e['para_idx']} search_from={e['search_from']} anchors={e['anchor_words']}")
assert len(pe) == 2, f"expected 2 person events, got {len(pe)}"
assert pe[0]["text"] == "Jessy Irwin" and pe[1]["text"] == "Stefan Mandel"

print("\nDEDUP:", "ALL PASS" if allok else "SOME FAILED")
