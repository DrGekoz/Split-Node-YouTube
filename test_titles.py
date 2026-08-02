"""Verify ASS title generation handles chapter + location + timeline + person."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.resolve()))
import system_breakers as sb

events = [
    {"kind": "chapter", "start": 2.0, "end": 6.0, "chapter_num": 1,
     "title": "The Account That Never Said No",
     "text": "Chapter 1 - The Account That Never Said No"},
    {"kind": "timeline", "start": 8.0, "text": "December 12th, 2012", "para_idx": 1},
    {"kind": "location", "start": 8.2, "text": "Goulburn, New South Wales", "para_idx": 1},
    {"kind": "person", "start": 15.0, "text": "Jessy Irwin", "para_idx": 3},
    {"kind": "person", "start": 8.5, "text": "STEFAN MANDEL", "para_idx": 1},  # collides w/ timeline+location
]
out = str(Path(__file__).parent / "test_output" / "unit_titles.ass")
sb.split_node_titles.build_title_ass(events, out, 1920, 1080, 24)
txt = Path(out).read_text()
print("ASS lines:", len(txt.splitlines()))
# style checks
for style in ("TypePerson", "TypePersonGhost", "TypeLoc", "TypeTime", "ChapCore"):
    assert style in txt, f"missing style {style}"
print("styles OK: TypePerson gold + TypePersonGhost present")
# person events rendered with gold style
person_lines = [l for l in txt.splitlines() if "TypePerson" in l]
print("TypePerson dialogue lines:", len(person_lines))
assert any("Jessy Irwin" in l for l in person_lines)
# STEFAN MANDEL -> person card should display title-cased... wait, display conversion happens in _build_person_events,
# not in the ASS builder. Text here is raw.
# chapter card centered check (Dialogue lines only)
chap = [l for l in txt.splitlines() if "Dialogue:" in l and "ChapCore" in l]
assert chap and r"\an5" in chap[0] and "The Account That Never Said No" in chap[0]
print("chapter card centered OK (an5)")
# stacking: person at 8.5 collides with timeline (8.0) + location (8.2) -> _stack_up=2 -> base_y = H-110-148
import re
# find the person event y positions
for l in person_lines:
    m = re.search(r"\\pos\(([\d.]+),([\d.]+)\)", l)
    if m:
        print(f"  pos({m.group(1)},{m.group(2)}) style={l.split(',')[3]}")
print("UNIT ASS OK")
