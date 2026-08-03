# Changelog

All notable changes to Split Node.

## [1.0.0] - 2026-08-03

Initial release - the complete AI documentary generator pipeline (8 commits).

### Core pipeline

- AI documentary generator: RSS "beat the system" stories (hack / lottery / loophole keywords) -> two-stage LLM (narration script, then shot list with clothed mannequins + camera logic) -> images -> TTS -> render -> YouTube upload
- Mannequin archetypes: shop display mannequin heads, blank plastic faces, always clothed
- PocketTTS built-in narration voice via HTTP, loudnorm to 0dB
- 1080p hevc_nvenc renders with `+faststart` + `avoid_negative_ts`
- Music bed at -18dB (suspense / triumphant by tone) + SFX at -14dB hit-aligned to shots
- SFX library (Nikko Hunt cinematic sounds) with pre-analyzed build / hit / decay times
- YouTube upload enabled + Discord announcement (video description + hype wrap + link, Cloudflare 403 UA fix)

### Chapters & titles

- Chapter system: 10 duration-aligned breaks (intro/outro 15% each, middle even), word-count runtime estimates, LLM-written chapter titles
- Bahnschrift chapter cards ("CHAPTER N" kicker + title), typewriter location/person cards in Consolas
- Split Node title engine (`split_node_titles.py`) with ASS styling

### Cast likeness system

- 20 fixed metahuman archetypes with exact clothing prompts
- Real-photo references via SerpAPI Google Images search + Openverse fallback
- Local LM Studio vision audit (person + text/logo/watermark checks)
- Krea 2 identity LoRA chains: 6-panel character sheets (face -> side -> back -> body), grounding tuned to prevent duplicate figures

### Assets & style

- B-roll cache: reusable no-character shots keyed by scene keywords
- Style sheets (Arcane reference): channel style sheet for assets, dedicated location + prop style sheets, style-transfer-only prompts
- SPANkendata 4x upscaler (bf16 + channels_last, streaming RGB frames to GPU)

### Reliability

- Resume logic + persistent batch clips for long-form render
- Stream-copy concat instead of re-encode
- Test suite: style sheets, identity chains, shot angles, end-to-end mini test
