# Changelog

All notable changes to Split Node.

## [1.7.0] - 2026-08-06

### New `mannequin` style profile (9th built-in)

- Added a `mannequin` built-in style profile inspired by the ContentMachine documentary pipeline - seamless glossy porcelain mannequins with a perfectly smooth ceramic finish, featureless smooth porcelain faces (no eyes/nose/mouth), off-white cream or warm brown porcelain skin tones (never realistic human skin), painted or sculpted hair, no doll joints/seams/stands, always fully clothed head-to-toe in period-accurate outfits with explicitly named footwear, photorealistic render + ray tracing + 8K
- Selectable like any other profile: `STYLE=mannequin python system_breakers.py`
- Style preview generated and added to the README "See the look" gallery (Elon Musk face-front, same real-photo identity ref + mannequin style injected)

## [1.6.0] - 2026-08-06

### Easter eggs - one hidden element in one shot

- Every episode can hide one tiny background element in EXACTLY ONE shot - injected into that shot's prompt as a "very small, in the background" element (subtle, easy to miss)
- Startup prompt asks *"Hide an easter egg in one shot?"*; pick one from the list or choose *add new* to write your own prompt (saved to `style_sheets/easter_eggs.json`, selectable on future runs). `EASTER_EGG=<name>` selects without prompting
- Built-in easter egg: **Duck Pope** - Pontiff of the Union of the Peking Duck - a tiny ancient majestic sacred white duck in papal regalia, hidden far-background and out of focus
- The hidden shot prefers a wide/medium shot (room for a background), is picked once, and is kept on resume
- The exact timecode of the hidden shot is reported right after the video finishes rendering AND again after the upload completes (`[EASTER EGG] 'duck pope' is hidden in the shot at HH:MM:SS`)
- CLI: `--list-easter-eggs`, `--add-easter-egg <name> "<prompt>"`, `--remove-easter-egg <name>`

## [1.5.0] - 2026-08-06

### Selectable style profiles - `STYLE=<name>`

- 8 built-in visual style profiles: `arcane` (default), `bold-outline`, `artsy`, `photoreal`, `noir`, `synthwave`, `editorial`, `watercolor` - picked with the `STYLE` env var (or `STYLE_PROFILE`)
- Custom styles persist in `style_sheets/custom_styles.json` and become selectable on every run: `--list-styles`, `--add-style <name> "<descriptor>"`, `--remove-style <name>`
- The selected style is injected as TEXT into every shot, character panel, location and prop prompt - no style-plate image refs, no reference-copy bug
- A resume keeps the exact style the episode was generated with (style recorded in resume state; `STYLE=` overrides)

### Character panels: six individual 1280x1280 refs (no grid merge)

- Every character now gets SIX separate 1280x1280 panels (face, face_side, face_back, body_front, body_side, body_back) instead of one 3x2 grid; style is prompt-injected, the only identity ref is the real photo on the face panel (style-plate ref dropped); panels chain off the face panel with lower ref-boost
- Shot loop rewritten around per-shot ref discovery (`_select_shot_refs`): wide shot -> body panel, close-up -> face panel, facing left -> side panel as-is, facing right -> side panel MIRRORED, back/from-behind -> back panel, hand/object close-up -> no person ref, multi-person -> one panel per character (they can mismatch), business HQ/interior shot -> real brand logo ref added
- Multi-character shots supported (comma-separated names in the shot list; each described from its archetype with which way it faces); tolerant sheet lookup handles legacy combined-keyed defs
- Both fresh and resume image paths use the same logic; ref-boost tuned by ref count (single 4.0/768, multi 2.5/1024)
- tqdm progress bars with per-item ETA on every Krea 2 stage (character panels, location sheets, prop assets, shots, resume regen)
- Location/prop sheets still built but no longer used as shot refs (location always lives in the scene prompt; props in the scene when present)

### Style previews

- `style_previews/` ships one 1280x1280 face-front Elon Musk panel per selectable style (real-photo identity ref + that style injected) so the look can be previewed before choosing

### Output resolution selection - 1080p or 4K

- Pick the final output resolution with the `RESOLUTION` env var or the startup prompt (`RESOLUTION=4k` / `RESOLUTION=1080p`, default 1080p) - it drives BOTH the in-graph image upscale target (4x-FaceUpDAT -> 1920x1080 or 3840x2160) and the FFmpeg clip/video output (including the 4x zoompan overscan, scaled proportionally)
- Persisted to resume state so a resumed episode keeps the same output resolution
- Replaced the standalone SPAN 4x upscaler for the pipeline path with the in-graph 4x-FaceUpDAT (upscale_4k.py remains as an optional separate tool)

## [1.4.0] - 2026-08-04

### B-roll / location / prop sheets: style PROMPT injection (no image refs)

- B-roll shots (char=NONE), location sheet panels and prop sheet panels now generate as PURE txt2img (1280x720 -> in-graph FaceUpDAT 1920x1080) with the channel style injected as TEXT - faster, and impossible to hit the reference-copy bug
- The style descriptor is extracted ONCE from the two approved style sheets (prop_style_sheet.png + location_style_sheet.png) via the local vision model and cached to style_sheets/style_prompt.txt (roleplay-preamble stripped - only the last paragraph is kept; falls back to a static descriptor if vision is unavailable)
- EXCEPTION (Joe): when a location IS a business building (logo_ref available), the business logo still joins as an image ref (Kontext reference mode - prompt controls the building, ref carries the brand mark)
- B-roll image cache retired: image-assets/ lookup + cache-write calls removed from both the fresh and resume image paths (helpers kept for the standalone generate_broll_cache.py)
- Character shots + character sheets + brand assets UNCHANGED (identity refs + patch)

## [1.3.1] - 2026-08-04

### Resume state backup - the resume prompt can't silently disappear

- `_save_resume_state` now writes a `.bak` copy alongside the main state file on every save
- `_load_resume_state` falls back to the `.bak` when the main file is missing or corrupt (prints "Main resume state missing/corrupt - restored from backup")
- `_clear_resume_state` removes both files on completion

## [1.3.0] - 2026-08-04

### Interactive video-length prompt

- Fresh runs now ask "How many narration paragraphs?" (default 115) right after the episode number, print the estimated video length (~14.3s per paragraph - measured from ep8: 120 clips -> 1712.7s voice timeline incl. 0.3s pads), and loop confirm/change until confirmed (typing a new number re-estimates; clamped 10-400)
- `_build_narration_script(paragraphs, target_paras)` uses the confirmed count for the per-article-paragraph expansion and the fallback slice (was the fixed TARGET_NARRATION_PARAS=115)
- The count is persisted to resume state (`target_paras`) - a resumed job sticks with the job-start count and never re-asks (shown in the resume header)

## [1.2.1] - 2026-08-04

### Location/prop style panels: non-patched reference pipeline + 720p -> 1080p

- Style-transfer panels (location sheet panels, generic prop panels) with ONE style ref (the plate) now use the NON-patched reference pipeline (`Krea2OstrisEditModelPatch` + `TextEncodeKrea2OstrisEdit` + Kontext, denoise 1.0) instead of the krea2edit identity patch
- Root cause (Joe report): the krea2edit identity patch is a reference-COPY channel - with a single style plate it reproduced the ref image and forced its own latent AR (720x1280 portrait) instead of honoring the prompt and the requested panel size
- The identity patch is now used ONLY when 2+ refs join: face panel [style_plate, real_photo], branded location sheets [style_plate, logo], brand assets [style_plate, logo], shots with face+location+prop refs. Rule: patch only for 2+ references, 1 style ref = plain reference pipeline
- `krea2_splitnode._generate_once`: single-ref reference mode uploads the RAW image (no padded strip - the dark bars bled into the t=0 ref tokens as layout)
- ALL asset panels now generate at 720p (1280x720) with the in-graph FaceUpDAT upscale to 1920x1080 (was 640x540, no upscale) - location panels, prop panels and the prop txt2img fallback; sheet composition still cells them into 640x540
- Character sheet chain panels unchanged (single IDENTITY refs - the patch is required there and is verified working; Joe's rule scopes to style references)

## [1.2.0] - 2026-08-04

### ComfyUI crash resilience (ep8: 111/120 images failed)

- `krea2_splitnode.generate()` is now a retry wrapper around `_generate_once()`: on ANY connection error (WinError 10061 refused / 10054 reset, timeouts) it clears the cached server URL, polls `/system_stats` up to 240s for ComfyUI to recover (it crashes with a native access violation in `load_image` under Krea2 --lowvram load, then recovers or gets relaunched), and re-runs the whole job - refs re-uploaded, fresh prompt_id. Max 4 crash-retries per image, then gives up so a dead server can't stall the run
- `/history` poll loop swallows transient timeouts (up to ~3 min of consecutive failures) and keeps polling the SAME prompt_id - ComfyUI blocks its HTTP handler while re-staging the 12.9GB UNET between jobs (~80s), which is NOT a dead job. Previously each timeout aborted the job and queued a duplicate render
- `/prompt` submit timeout bumped 60s -> 120s to cover the model-staging window
- `_upload_ref()` re-encodes EVERY reference as a clean 8-bit RGB PNG capped at 4096px before upload - removes the load_image decoder crash trigger (paletted / 16-bit / CMYK / oversized PNGs) and caps VAE-encode VRAM on huge reference photos

### Render no longer crashes on failed images

- `_render_clip()` guards `None` image_path (failed shots store None): falls back to the dark plate instead of `TypeError: stat: path should be string...` at `os.path.isfile`, so the video always renders to completion (missing images = dark frames, retried on the next resume run)

### Resume rebuilds the episode world (not just images)

- `_resume_episode` now rebuilds missing character / location / prop sheets BEFORE regenerating shots, so resumed shots get the SAME identity refs as a fresh run:
  - Location sheets + prop assets: when empty in state, refetch `article_url` -> `fetch_article_paragraphs` -> `_build_episode_context` (LLM, falls back to shot narrations if the fetch fails) -> `_build_location_sheets` / `_build_prop_assets` with the same seeds as the fresh path
  - Character sheets: per character, take the def dict from state (rebuild deterministically via `_build_character_sheets` if missing), reuse the on-disk `<safe>_sheet.png` if a prior run made it, else `_generate_character_sheet` - cached per loop, respects FACE_LOCK=0
  - Fixed latent bug: state stores character sheets as DEF dicts not image paths, so resume's `os.path.isfile(str(def))` was always False - face refs were never attached on resume

## [1.1.1] - 2026-08-04

### Fix: SystemBreakers.bat crash

- Fixed bat crash: unescaped parenthesis in the ComfyUI warning echo ("Start ComfyUI (run_nvidia_gpu.bat)...") terminated the parenthesized IF block early, aborting the batch with "then was unexpected at this time" at the ComfyUI check
- Removed `setlocal enabledelayedexpansion` (it was unused) - exclamation marks in echo text were being swallowed as delayed-expansion references
- Rewritten with CRLF line endings (cmd.exe parses multi-line parenthesized blocks reliably with CRLF)
- Verified end-to-end through cmd.exe: all checks, warn paths and the launch flow complete without errors

## [1.1.0] - 2026-08-04

### Brand & AI logos - official sources first

- Official logo registry (`OFFICIAL_LOGOS`): 36 brands pre-mapped to their Wikimedia Commons logo files - all AI companies (OpenAI, Google/Gemini, Anthropic, Meta, Microsoft/Copilot, xAI/Grok, Mistral, DeepSeek, Stability AI, Midjourney, Runway, Hugging Face, ElevenLabs, Perplexity, Adobe/Firefly, NVIDIA) plus frequently-mentioned big tech (Apple, Amazon, IBM, Tesla, Netflix, Spotify, LinkedIn, Oracle, Sony, Ford, Toyota, Coca-Cola, X, Salesforce, Nike)
- `_commons_logo_bytes`: fetches the official mark via the Commons API, rasterized to a 512px PNG thumbnail (SVG sources rendered server-side - no local converter needed), with a proper User-Agent
- `_find_logo` priority order: cache -> official Wikimedia -> SerpAPI image search (Openverse fallback) ONLY for brands not in the official registry
- Verified live: OpenAI + Tesla resolve from Wikimedia; a non-registry business (Patagonia) falls back to SerpAPI

## [1.0.0] - 2026-08-04

Initial release - the complete AI documentary generator pipeline.

### Story discovery

- RSS "beat the system" story ingestion (hack / lottery / loophole keywords) with junk-article filtering (cookie / newsletter / paywall / sponsored / boilerplate patterns stripped before paragraph extraction)
- LLM relevance scoring for every paragraph vs the overall topic (0-10, off-topic beats discarded) with fail-open keep-on-error behavior
- Trend scoring toolkit (`trend_scorer.py`): SerpAPI demand data + YouTube competition analysis, cached 24h

### Script generation (LLM)

- **Director's bible** (`_build_directors_bible`): deeper problem, protagonist transformation, chapter moods, hero paragraphs for ECU magnification - the plan before any image
- **Episode world** context builder - works for any topic / environment / location
- **Scene board** (`_build_scene_board`): one storyboard card per narration beat, saved to the episode folder for human review before generation
- **Stage 1 - narration script** (`_build_narration_script`): each article paragraph expanded into multiple narration paragraphs, target ~115 total for ~25 min episodes; covered-beat dedupe list injected per call to prevent repetition
- **Stage 1 hardening**: strict OUTPUT CONTRACT (raw narration only - no "Here are 5 paragraphs" meta text), `_strip_narration_meta` gate applied before TTS and at parse, bad-generation retry
- **Stage 2 - shot list** (`_build_shot_list`): one shot entry per narration paragraph - mannequin archetype, camera logic (EWS / WS / MS / CU / ECU), angle, action, SFX category; chapter paragraphs become black cards
- **Chapter system**: 10 duration-aligned breaks (intro/outro 15% each, middle even) estimated from per-paragraph word counts, LLM-written chapter titles (`_llm_chapter_titles`)
- **Style test frame + human review gate**: Krea 2 test frame generated before the run commits; rejection rebuilds the bible with a fresh perspective
- **Episode template**: the winning formula (bible + setup) saved per episode for reuse

### Cast & likeness

- 20 fixed metahuman archetypes (`CHARACTER_ROSTER`) with exact clothing prompts; `_assign_archetype` maps characters by role keywords + gender/age with everyman fallback
- Real-photo reference search via SerpAPI Google Images (~$0.01/query) with Openverse fallback, downloaded to `cast_refs/real/` (gitignored)
- Local LM Studio vision audit (`_audit_real_photo`): person present + text/logo/watermark rejection
- Krea 2 identity LoRA chains: 6-panel character sheets (face -> face-side -> face-back -> body-front -> body-side -> body-back), face-lock portraits, angle-matched views in shots
- Identity prompt fixes: view-description-only prompts (style text in identity prompts flips the model into img2img copy mode); grounding tuned to 768px (1024px caused split/duplicate figures)

### Assets & style chain

- Channel style sheet (`build_style_sheet.py`, Arcane reference) as the single source of truth for the look - no LoRA training
- Dedicated location style sheets (`build_asset_style_sheets.py`): 6-panel 3x2 grids per environment (establishing / front-left / front-right / interior / detail / overhead)
- Prop assets: front + back panels; generic props pure text-to-image with style plate, specific real-world props (brands / models / digits / proper nouns via `_needs_real_prop`) get SerpAPI real photo + style plate; `PROP_REAL_FORCE` overrides
- Style-transfer-only prompt wording ("Use ONLY the painting and render style from the reference artwork") - assets are styled, shots reference ONLY the styled assets (plate as fallback only)
- B-roll cache (`_lookup_broll_asset` / `_cache_broll_asset`, `generate_broll_cache.py`): reusable no-character shots keyed by scene keywords

### Brand & AI logos

- Curated AI company/model registry (OpenAI, ChatGPT, Gemini, Claude, Midjourney, NVIDIA, xAI, DeepSeek, ElevenLabs...) with alias-based detection across the article + narration
- LLM business extraction pass (`_extract_brands`): any other real businesses mentioned get detected and classified as `screen` (entity/product talk) or `building` (HQ / offices / factory / physical location talk); manifest persisted to `cast_refs/logos/brands.json`
- Logo cache (`cast_refs/logos/`): SerpAPI image search (Openverse fallback) downloads the official logo once, then it is reused forever - cache-first, zero repeat searches; `--cache-logos NAME` CLI pre-caches without a full run
- Hacker-screen assets (`image-assets/brand_screens/`): entity talk renders a dark hacker terminal with the real logo centered, refs = [prop style sheet, logo]
- Logo-on-building assets (`image-assets/brand_buildings/`): HQ talk renders the logo as a glowing facade sign at night, refs = [location style sheet, logo]
- Business-building location sheets: when a location IS a business building (e.g. "OpenAI headquarters", "Tesla factory floor"), the logo joins that sheet's refs so it appears inside the generated building
- Shot matching: scenes mentioning a brand pick the screen asset (entity talk) or building asset (HQ words in the scene); brand-name props use the cached logo as their real reference
- Resume-safe: brand assets rebuild from disk caches + manifest, no re-extraction needed

### Imagery

- Local Krea 2 Turbo generation (`krea2_splitnode.py`, ComfyUI --lowvram, identity LoRA `krea2_identity_edit_v1_2_r128`)
- Shots composed from pre-styled refs (face panel + location sheet + prop asset + b-roll), no style plate in shots
- Image generation runs in parallel with TTS (background worker)

### Voice, music & SFX

- PocketTTS narration voice (built-in or cloned ref), loudnorm 0dB
- Music: one continuous bed - suspense for the first 65% crossfading (2s) into triumphant, mixed at -18dB
- SFX library (`cinematic_sounds/`, Nikko Hunt) with pre-analyzed build / hit / decay times (`analyze_sfx.py` -> `sfx_library_extra.json`), hit-aligned at -14dB
- Camera shutter SFX at -4dB on cuts; every video opens with a glitchy suspense hit at t=0

### Rendering & titles

- 1080p hevc_nvenc with stream-copy concat and `+faststart` / `avoid_negative_ts`
- Chapter cards: "CHAPTER N" kicker + title, both ASS dialogs in Bahnschrift with glow-pop; typewriter location/person cards in Consolas (1.5s type / 4s hold / glitch off), pinned to faster-whisper word timings
- SPANkendata 4x upscaler (`upscale_4k.py`): bf16 + channels_last (fp16 corrupts SPAN arch), streaming raw RGB frames to GPU instead of per-frame PNG I/O

### YouTube & Discord

- YouTube upload with native scheduling, per-channel credentials, AI-generated content disclaimer
- Discord announcement after every upload (video description + hype wrap + link, Cloudflare 403 UA fix)

### Reliability & testing

- Resume-safe stages with saved state (story -> images -> render -> upload), persistent batch clips with reuse + cleanup
- Test suite: style sheet tests, identity chain tests (full chain, prod identity), sheet-to-shot, shot angles, style assets, end-to-end mini test (`mini_test.py`)

### Security & ops

- `.env`, `client_secret_*.json`, `*.credentials.json` gitignored - API keys never committed
- Real-person likeness photos (`cast_refs/real/`) gitignored - privacy / copyright
- README showcase images committed under `docs/images/` (optimized copies)
