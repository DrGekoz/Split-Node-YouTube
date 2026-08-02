"""Generate the 100-image b-roll cache into image-assets/ using FAL GPT Image 2.

1080p-class (landscape_16_9), quality=low (cheapest GPT Image 2 tier).
Every image is NO-CHARACTER b-roll with a keyword-rich filename so the
pipeline's _lookup_broll_asset() finds and reuses it for matching scenes.
Resumable: skips filenames that already exist. Run in background:
    python generate_broll_cache.py
"""
import json
import os
import sys
import time
import urllib.request

PROJECT = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(PROJECT, "image-assets")
FAL_URL = "https://fal.run/openai/gpt-image-2"
FAL_KEY = os.environ.get("FAL_API_KEY", "")

# SCENE_STYLE tail - zero human language so no person is ever generated
NO_PEOPLE = (
    "Realistic 3D render style, Unreal Engine 5 quality environment and prop "
    "render, cinematic lighting, moody atmosphere, dark color grade, film "
    "grain, high detail, 8k, dramatic documentary recreation. EMPTY SCENE - "
    "no people, no humans, no characters, no figures, no silhouettes, no "
    "faces, no bodies, no hands, absolutely no persons in the frame"
)

# 100 b-roll assets: (filename, prompt). Filenames are keyword-rich so the
# scene-keyword cache lookup can match them.
PROMPTS = [
    # --- server farm / datacenter --------------------------------------
    ("server_farm_wide.png", "A vast server farm, endless rows of black server racks receding into darkness, tiny blinking green and blue status LEDs, cold industrial atmosphere"),
    ("server_rack_close.png", "Close-up of a server rack, densely packed drives, glowing status lights, neatly bundled black cables"),
    ("datacenter_corridor.png", "A long narrow corridor between two walls of server racks, blue LED glow, haze in the air"),
    ("server_cables_close.png", "Extreme close-up of tangled fibre-optic cables with glowing ends, shallow depth of field"),
    ("server_drive_bay.png", "Open server chassis showing stacked drive bays with small blinking activity LEDs"),
    ("circuit_board_close.png", "Extreme close-up of a dark circuit board, glowing blue traces and a bright processor chip in the centre"),
    ("cpu_chip_macro.png", "Macro shot of a CPU chip, golden pins, glowing core, electric blue energy arcing across the die"),
    ("server_fans_close.png", "Close-up of spinning server cooling fans, metallic blades, moody rim lighting"),
    # --- AI bot / machine ----------------------------------------------
    ("ai_bot_head.png", "A sleek humanoid robot head in a dark room, matte black metal, single glowing red LED eye, cables trailing"),
    ("ai_interface_ui.png", "A futuristic AI assistant interface floating in a dark room, translucent holographic panels with data readouts"),
    ("neural_network_glow.png", "A glowing neural network of connected nodes and light threads floating in darkness"),
    ("robot_arm_macro.png", "Macro shot of a robotic arm joint, brushed metal, hydraulic pistons, dramatic side light"),
    ("ai_circuit_brain.png", "A stylised glowing brain made of circuit traces on a dark board"),
    ("machine_room_power.png", "A dark server hall with a towering machine glowing with cold blue light"),
    # --- hacker screens (glowing terminal text) ------------------------
    ("hacker_screen_cracked.png", "A computer monitor in a dark room displaying the word CRACKED in large glowing green terminal text on a black grid"),
    ("hacker_screen_access_granted.png", "A monitor displaying ACCESS GRANTED in glowing green text over a dark terminal"),
    ("hacker_screen_breach.png", "A monitor displaying BREACH CONFIRMED in huge glowing green letters over a dark grid, urgent alert"),
    ("hacker_screen_code.png", "A monitor full of scrolling source code in green on black, dark room glow"),
    ("hacker_screen_binary.png", "A monitor with cascading green binary digits raining down, matrix style"),
    ("hacker_screen_denied.png", "A monitor displaying ACCESS DENIED in glowing red terminal text"),
    ("hacker_screen_numbers.png", "A monitor wall of random numbers and figures in green monospace, dark room"),
    ("hacker_screen_password.png", "A terminal showing a password brute-force attempt, dots and asterisks, green on black"),
    ("hacker_terminal_cursor.png", "A dark terminal screen with a single blinking green cursor, minimal"),
    ("hacker_screen_firewall.png", "A terminal with a firewall block diagram in glowing green, log lines streaming"),
    ("hacker_screen_encrypted.png", "A monitor showing a large glowing padlock glyph made of code, encryption theme"),
    ("hacker_screen_transfer.png", "A terminal with a data transfer progress bar, green on black, percentage climbing"),
    ("hacker_screen_trace.png", "A terminal tracing an IP address across a dark map grid, glowing lines"),
    ("hacker_screen_logs.png", "A terminal with streaming server log entries, timestamps and status codes, green on black"),
    ("hacker_screen_matrix.png", "A wall of glowing green matrix code filling the frame, no visible monitor bezel"),
    # --- graphs / charts ------------------------------------------------
    ("graph_rising_green.png", "A stock chart on a dark monitor, a bright green line climbing steeply upward, candlesticks"),
    ("graph_falling_red.png", "A stock chart on a dark monitor, a red line crashing downward, candlesticks in freefall"),
    ("graph_candlestick.png", "Close-up of a candlestick chart, green and red candles, dark background"),
    ("graph_exponential.png", "A glowing exponential growth curve on a dark chart, steep hockey stick"),
    ("graph_crash_red.png", "A market crash screen, deep red plunge line, alarm red glow"),
    ("graph_gold_up.png", "A gold price chart climbing, golden line on black, gold bars at the edge of frame"),
    ("ticker_tape.png", "A glowing stock ticker tape with scrolling numbers and arrows, dark exchange floor"),
    ("dashboard_analytics.png", "An analytics dashboard on a dark monitor, graphs and numbers, dim office"),
    ("odds_probability_table.png", "A dark monitor displaying a probability and odds table, rows of numbers and percentages"),
    ("chart_monitor_office.png", "A single monitor glowing with charts in an otherwise dark empty office"),
    ("graph_line_flat.png", "A flat stock line on a dark chart, no movement, single horizontal line"),
    ("graph_spike.png", "A chart with a sudden vertical spike, glowing green, dark background"),
    # --- money / bank ----------------------------------------------------
    ("cash_bundles_close.png", "Close-up of bundled hundred-dollar bills stacked on a dark desk, moody light"),
    ("money_counter_machine.png", "A banknote counting machine feeding bills, dark room, green glow"),
    ("vault_door.png", "A massive circular bank vault door, brushed steel, combination dial, dim corridor"),
    ("vault_gold_bars.png", "Gold bars stacked inside a vault, warm light reflecting off the metal"),
    ("gold_bars_close.png", "Macro shot of gold bars stacked, engravings visible, dramatic lighting"),
    ("coin_stack_close.png", "A neat stack of gold and silver coins, macro, shallow depth of field"),
    ("bank_exterior_night.png", "A bank building exterior at night, columns and glass, floodlit"),
    ("atm_screen.png", "An ATM screen glowing in the dark, cash slot, night street reflection"),
    ("bank_counter_empty.png", "An empty bank teller counter at night, marble, dim lights"),
    ("lottery_tickets_close.png", "Scratch-off lottery tickets fanned out on a counter, macro, dramatic light"),
    # --- casino -----------------------------------------------------------
    ("casino_floor_slots.png", "A row of slot machines in a dim casino, colourful screens, nobody in frame"),
    ("poker_table_close.png", "A poker table close-up with cards and chip stacks, green felt, moody overhead light"),
    ("roulette_wheel_macro.png", "Macro of a roulette wheel, red and black numbers, spinning blur"),
    ("casino_chips_stacks.png", "Tall stacks of casino chips in red, black and white, dark table"),
    ("card_deck_close.png", "A deck of playing cards close-up, backs facing, dramatic side light"),
    ("casino_neon_exterior.png", "A casino exterior at night, neon signs, wet street reflections"),
    # --- tech / computers -------------------------------------------------
    ("keyboard_backlit_close.png", "Macro of a backlit mechanical keyboard, RGB glow, dark room"),
    ("monitor_dark_room.png", "A single monitor glowing in a dark room, light spilling on an empty desk"),
    ("laptop_open_dark.png", "An open laptop glowing in darkness, screen light on a dark desk"),
    ("computer_case_open.png", "An open PC case with glowing internal components, RGB fans"),
    ("old_crt_monitor.png", "A retro CRT monitor with a green screen in a dim room"),
    ("floppy_disks_close.png", "Vintage floppy disks stacked, macro, nostalgic moody light"),
    ("hard_drive_platter.png", "An exposed hard drive spinning platter, macro, reflective surface"),
    ("phone_screen_dark.png", "A smartphone screen glowing in a dark room, notifications"),
    ("wiring_tangle_close.png", "A tangle of cables and wires close-up, macro, dramatic shadows"),
    ("gaming_mouse_macro.png", "Macro of a gaming mouse with glowing logo on a dark desk"),
    # --- surveillance / security ------------------------------------------
    ("security_cameras_wall.png", "A wall of security cameras, dark control room, red recording lights"),
    ("cctv_feed_grid.png", "A grid of CCTV monitor feeds, grainy footage, dark room"),
    ("security_monitor_room.png", "A room wall of glowing security monitors, empty chairs"),
    ("fingerprint_scan.png", "A fingerprint being scanned, glowing biometric reader, macro"),
    ("keycard_reader.png", "A handless keycard reader on a dark wall, green ready light"),
    ("padlock_macro.png", "Macro of a heavy padlock on a chain-link gate, night"),
    ("security_fence_night.png", "A security fence with razor wire at night, floodlights"),
    ("id_badge_close.png", "A generic blank ID badge with a photo placeholder on a lanyard, macro"),
    # --- environments -------------------------------------------------------
    ("city_skyline_night.png", "A wide city skyline at night, lit windows, dark clouds"),
    ("street_night_rain.png", "A rainy city street at night, neon reflections on wet asphalt"),
    ("office_empty_night.png", "An empty open-plan office at night, desk lights, blinds"),
    ("apartment_block_night.png", "An apartment building at night, grid of lit windows"),
    ("warehouse_dark.png", "A vast dark warehouse interior, high ceilings, single light beams"),
    ("bridge_night.png", "A bridge at night with light trails, long exposure"),
    ("highway_light_trails.png", "A highway at night with red and white light trails, long exposure"),
    ("government_building.png", "A classical government building with columns at dusk"),
    ("courthouse_exterior.png", "A courthouse exterior, steps and columns, overcast light"),
    ("police_station_exterior.png", "A police station exterior at night, blue light"),
    ("financial_district.png", "Skyscrapers of a financial district at night, glass towers"),
    ("tunnel_light_end.png", "Looking down a dark tunnel toward a bright end light"),
    # --- story props ----------------------------------------------------------
    ("newspaper_headline_macro.png", "Macro of a newspaper front page with a dramatic headline, coffee stain"),
    ("documents_on_desk.png", "Scattered documents and papers on a dark desk, desk lamp"),
    ("fountain_pen_signing.png", "A fountain pen signing a document, macro, warm light"),
    ("phone_off_hook.png", "A landline phone off the hook on a dark desk, dial tone silence"),
    ("calendar_dates_close.png", "A wall calendar with dates circled in red, close-up"),
    ("clock_macro.png", "Macro of a clock face, second hand moving, dramatic light"),
    ("magnifying_glass.png", "A magnifying glass over documents, macro, investigator light"),
    ("leather_briefcase.png", "A worn leather briefcase on a dark floor, single spotlight"),
    ("vintage_typewriter.png", "A vintage typewriter in a dark room, paper loaded, moody light"),
    ("smoke_dark_room.png", "Thick smoke curling in a dark room, single beam of light"),
    ("corridor_door.png", "A dark corridor with a single door slightly ajar, light spilling out"),
    ("dark_stairwell.png", "A dark stairwell seen from below, harsh shadows"),
    ("safe_open_cash.png", "An open safe with stacks of cash inside, warm light spilling out, dark room"),
]


def gen_one(prompt, out_path):
    """One GPT Image 2 low-quality call -> saves PNG. Returns True/False."""
    data = json.dumps({
        "prompt": prompt,
        "image_size": "landscape_16_9",
        "num_images": 1,
        "quality": "low",
    }).encode()
    headers = {"Authorization": f"Key {FAL_KEY}", "Content-Type": "application/json"}
    req = urllib.request.Request(FAL_URL, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=300) as r:
        result = json.loads(r.read())
    image_url = result.get("images", [{}])[0].get("url", "")
    if not image_url:
        raise RuntimeError("no image url in response")
    tmp = out_path + ".tmp"
    urllib.request.urlretrieve(image_url, tmp)
    if os.path.getsize(tmp) < 1000:
        os.unlink(tmp)
        raise RuntimeError("downloaded file too small")
    os.replace(tmp, out_path)
    # Pipeline rule: every image generated by FAL GPT Image 2 gets upscaled to
    # 1920x1080 with 4x_NMKD-Siax_200k BEFORE FFmpeg processes it. This is how
    # we render cheap (FAL low quality 608p) but get crisp 1080p output.
    try:
        import subprocess
        subprocess.run(
            [r"F:\ComfyUI_windows_portable\python_embeded\python.exe",
             os.path.join(PROJECT, "upscale_model.py"),
             r"F:\ComfyUI_windows_portable\ComfyUI\models\upscale_models\4x_NMKD-Siax_200k.pth",
             out_path, out_path],
            capture_output=True, text=True, timeout=180)
    except Exception:
        pass


def main():
    if not FAL_KEY:
        print("[FAIL] FAL_API_KEY not set")
        return 1
    os.makedirs(OUT_DIR, exist_ok=True)
    todo = [(name, prompt) for name, prompt in PROMPTS
            if not os.path.isfile(os.path.join(OUT_DIR, name))]
    print(f"[CACHE] {len(todo)}/{len(PROMPTS)} images to generate "
          f"(GPT Image 2, low, landscape_16_9) -> {OUT_DIR}")
    ok = 0
    for i, (name, prompt) in enumerate(todo, start=1):
        out = os.path.join(OUT_DIR, name)
        full_prompt = f"{prompt}. {NO_PEOPLE}."
        for attempt in range(3):
            try:
                gen_one(full_prompt, out)
                ok += 1
                print(f"  [{i}/{len(todo)}] OK {name}")
                break
            except Exception as e:
                body = str(e)
                # schema guard: if 'quality' is rejected, retry without it
                if attempt == 0 and ("quality" in body.lower() or "400" in body or "422" in body):
                    print(f"  [{i}] quality param rejected ({body[:120]}) - retrying without")
                    data = json.dumps({
                        "prompt": full_prompt,
                        "image_size": "landscape_16_9",
                        "num_images": 1,
                    }).encode()
                    headers = {"Authorization": f"Key {FAL_KEY}",
                               "Content-Type": "application/json"}
                    req = urllib.request.Request(FAL_URL, data=data, headers=headers)
                    try:
                        with urllib.request.urlopen(req, timeout=300) as r:
                            result = json.loads(r.read())
                        image_url = result.get("images", [{}])[0].get("url", "")
                        urllib.request.urlretrieve(image_url, out + ".tmp")
                        os.replace(out + ".tmp", out)
                        ok += 1
                        print(f"  [{i}/{len(todo)}] OK {name} (no quality param)")
                        break
                    except Exception as e2:
                        print(f"  [{i}] FAIL {name}: {e2}")
                        time.sleep(3)
                        continue
                print(f"  [{i}] attempt {attempt+1} FAIL {name}: {body[:130]}")
                time.sleep(3)
        else:
            print(f"  [{i}] GAVE UP {name}")
        time.sleep(1.5)
    print(f"[CACHE] done: {ok}/{len(todo)} generated, "
          f"{len(PROMPTS) - ok} failed/skipped")
    return 0 if ok == len(todo) else 2


if __name__ == "__main__":
    sys.exit(main())
