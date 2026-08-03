# Split Node

AI documentary generator. Turns "beat the system" news stories (hacks, lottery wins, loopholes, scams) into ~25-minute 1080p documentaries in the FERN / Black Files style - narrated by a cloned voice, scored with music and cinematic SFX, and cast with a full roster of AI characters. Headless: RSS in, rendered and uploaded episode out.

## Features

- Two-stage LLM pipeline: narration script, then shot list (clothed mannequins, camera logic EWS / WS / MS / CU / ECU)
- Cast likeness system: 20 fixed metahuman archetypes with exact clothing prompts, real-photo reference search (SerpAPI, ~$0.01/query) + local vision audit
- Krea 2 identity LoRA chains: 6-panel character sheets (face -> body), style driven by reference style sheets - no LoRA training required
- Voice-cloned narration (PocketTTS), music beds (suspense crossfading into triumphant), 130+ SFX library with hit-aligned timing
- 1080p hevc_nvenc render, SPANkendata 4x upscaling
- Chapter system: 10 duration-aligned breaks, Bahnschrift chapter cards with glow-pop, typewriter location/person cards
- B-roll asset cache, resume-safe stages
- Trend scoring toolkit (SerpAPI + YouTube competition analysis)
- YouTube upload + Discord announcements

## Pipeline

1. **Story discovery** - RSS "beat the system" stories (hack / lottery / loophole keywords), relevance scoring
2. **Framework + narration** - LLM writes the episode structure and narration script (target ~115 paragraphs / ~25 min)
3. **Shot list** - mannequin archetype per character, camera + angle per shot
4. **Imagery** - Krea 2 identity chains -> style-sheet styled assets -> b-roll cache (no-character shots reused)
5. **TTS** - cloned narration voice via PocketTTS
6. **Music + SFX** - one continuous music bed, SFX hit-aligned to shots
7. **Render** - 1080p hevc_nvenc with burned titles
8. **Upload** - YouTube + Discord announcement

## Requirements

- Python 3.11+
- LM Studio on localhost:1234
- ComfyUI with Krea 2 (identity / asset pipeline, optional for fallback mode)
- PocketTTS server on 127.0.0.1:8769
- FFmpeg with hevc_nvenc (NVIDIA)
- SerpAPI key for real-photo references + trend scoring - set `SERPAPI_API_KEY=...` in `.env`
- YouTube OAuth: `client_secret_*.json` + `oauth_split_node.py`

## Usage

| Command | Purpose |
|---------|---------|
| `SystemBreakers.bat` | Run the full pipeline (story -> upload) |
| `system_breakers.py` | Main pipeline script |
| `krea2_splitnode.py` | Krea 2 identity chain / asset generation |
| `cast_likeness.py` | Build cast likeness references |
| `build_style_sheet.py` | Build the channel style reference sheet |
| `build_asset_style_sheets.py` | Build location / prop style sheets |
| `analyze_sfx.py` | Analyze SFX library (build / hit / decay times) |
| `trend_scorer.py` | Score topic ideas (demand / room / trajectory) |
| `upscale_4k.py` | SPAN 4x upscaler |
| `mini_test.py` | End-to-end pipeline test |
| `split_node_titles.py` | Chapter / title ASS engine |

## Project layout

| Path | Purpose |
|------|---------|
| `shots/` `rendered_audio/` `rendered_video/` `thumbnails/` | Stage outputs (gitignored) |
| `cinematic_sounds/` | SFX library |
| `style_sheets/` `style_refs/` | Krea 2 style reference assets |
| `cast_refs/` | Cast likeness images (`cast_refs/real/` holds real-person photos - gitignored) |
| `voice_refs/` | TTS narration voice clone reference |
| `.env` | API keys (gitignored - never commit) |

## Notes

- Episodes numbered (epNNN), per-episode shot folders under `shots/epN/`
- AI-generated content disclaimer included on uploads
