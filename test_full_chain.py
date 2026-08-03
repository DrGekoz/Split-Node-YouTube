#!/usr/bin/env python3
"""Full asset-chain test: location sheets + prop assets -> styled shot.

Exercises the PRODUCTION builders (_build_location_sheets, _build_prop_assets)
and the production shot ref assembly ([face_panel, location_sheet,
prop_asset] - all pre-styled, NO style plate in the shot). Runs the real
_generate_all_shots path with a small hand-built shot list so every piece of
the style chain is verified end to end."""
import sys, os, time
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import system_breakers as sb

PROJECT = Path(__file__).resolve().parent
TEST_DIR = PROJECT / "test_output" / "full_chain"
TEST_DIR.mkdir(parents=True, exist_ok=True)

CONTEXT = {
    "era": "modern",
    "places": ["underground casino vault"],
    "environments": ["dark casino floor"],
    "props": ["black leather briefcase", "stack of cash"],
    "time_of_day": "night",
}

SHEET = {
    "role": "entrepreneur",
    "name": "Elon Musk",
    "age": "50s",
    "gender": "male",
    "appearance": "angular face, short dark hair, light stubble",
    "clothing": "black t-shirt, dark jeans",
}

SHOTS = [
    {
        "narration": "Elon walks into the vault with the briefcase.",
        "narration_idx": 0,
        "shot_type": "MS",
        "angle": "eye-level",
        "character": "Elon Musk",
        "character_role": "entrepreneur",
        "scene": "Elon Musk stands in the dark underground casino vault room "
                 "holding a black leather briefcase, stacks of cash on the "
                 "table beside him, dramatic lighting",
        "sfx": "NONE",
        "tone": "suspense",
    },
]


def main() -> int:
    print("=== FULL ASSET CHAIN TEST (location + prop + face -> shot) ===")
    t0 = time.time()

    # 1. Location sheets (6-grid per location)
    print("\n[1/4] Location sheets...")
    loc_sheets = sb._build_location_sheets(CONTEXT, 42424, TEST_DIR)
    print(f"  -> {len(loc_sheets)} location sheet(s)")
    for loc, path in loc_sheets.items():
        print(f"     {loc}: {os.path.basename(path)}")

    # 2. Prop assets (front+back each, T2I vs real)
    print("\n[2/4] Prop assets...")
    prop_assets = sb._build_prop_assets(CONTEXT, 43424, TEST_DIR)
    print(f"  -> {len(prop_assets)} prop asset(s)")
    for prop, path in prop_assets.items():
        print(f"     {prop}: {os.path.basename(path)}")

    # 3. Character sheet (face panel for identity)
    print("\n[3/4] Character sheet...")
    sheet_path = sb._generate_character_sheet("Elon Musk", SHEET, 44424, TEST_DIR)
    print(f"  -> {'OK' if sheet_path else 'FAIL'} | {sheet_path}")

    # 4. Shots through the REAL production path (face + location + prop refs)
    print("\n[4/4] Shots (production _generate_all_shots, ep=999)...")
    ep_dir = sb.SHOTS_DIR / "ep999"
    ep_dir.mkdir(parents=True, exist_ok=True)
    # _build_shot_prompt expects ARCHETYPE DICTS (like _build_character_sheets
    # produces); the sheet IMAGE paths are resolved inside _generate_all_shots
    # via _generate_character_sheet -> _find_real_reference (cached reuse).
    char_sheets = sb._build_character_sheets(SHOTS, [s["narration"] for s in SHOTS])
    shots = sb._generate_all_shots(SHOTS, char_sheets, episode_num=999,
                                   context=CONTEXT,
                                   location_sheets=loc_sheets,
                                   prop_assets=prop_assets)
    ok = sum(1 for s in shots if s.get("image_path"))
    print(f"  -> {ok}/{len(shots)} shots generated")
    for s in shots:
        print(f"     shot: {s.get('image_path')}")
    print(f"\n=== DONE in {((time.time()-t0)/60):.1f} min ===")
    return 0 if ok == len(shots) else 1


if __name__ == "__main__":
    sys.exit(main())
