# Changelog

All notable changes to Split Node.

## [1.31.0] - 2026-08-07

### Interactive resume (regenerate anything, tweak as you go)

- **Resume now asks what to rebuild** instead of silently only filling gaps: rebuild the narration **SCRIPT** from the article, regenerate **ALL TTS** clips, regenerate **ALL images**, and/or **swap the image-gen model**. Each is a separate `[y/N]` prompt.
- **"Rebuild script"** re-fetches the article and re-runs the full pipeline (story bible → narration → relevance rating → chapters → anchors → establishing shots → scene board → shot list → character sheets → brand assets), then forces image + TTS regeneration. A new script resets the derived titles / description / tags so they regenerate too.
- **"Swap image-gen model"** interactively picks a backend (`local` / `runpod` / `fal` / `codex`) and a model, writing `IMAGE_BACKEND` / `IMAGE_MODEL`, and forces image regen so the new look applies.
- `SKIP_RESUME_MENU=1` restores the old gap-fill-only resume flow.

### No more bracketed stage directions spoken aloud

- New **`_strip_stage_directions()`** strips parenthetical/bracketed LLM stage directions (e.g. `(Waitshifting context slightly to the US office floor...)`) from narration **before** TTS — in both fresh runs and resumed TTS regeneration. Real content parentheticals like `(KKR)` / `(OTC)` / `(Falcon, Helix, Pink)` are kept. A lowercase lead left after a leading bracket is re-capitalised.

### Locations now come from the article (no invented cities)

- Episode-context and story-bible extraction prompts tightened: places must be **EXPLICITLY named in the article** (empty list if none, "NEVER invent a city, street or venue"). This stops hallucinations like "Queen Square, Sydney" / "Goulburn, NSW" / "Boston, MA" when the article only states a region (e.g. "the United States").
- **Establishing-shot locations capped to the 4 earliest-mentioned places** so an episode stops fragmenting across too many locations (the dropped places are logged).



### Establishing shots (new place/person gets a proper intro)

- **`_inject_establishing_shots()`** injects a dedicated establishing narration line immediately BEFORE the first paragraph that mentions each unique **location** and each unique **character** (from the story bible's `key_places` + character roster). Each becomes its own shot rendered as a **wide/full establishing frame**: `EWS` (extreme wide) for a location, `WS` (full-body) for a character.
- **Camera shutter + instant cut** — every establishing shot triggers a camera-shutter SFX + whoosh/sweep in the audio mix AND the 2-black-frames shutter cut in the render, so when a new place or person is first introduced the video cuts straight to a proper establishing shot of them instead of jumping into the scene. Both `_camera_shutter_paras` and the audio-mix shutter logic were updated.
- Establishing character shots reuse the bible roster names (pass the cast-lock) and use the character's identity panels, so the intro shot shows the right person.

### Age / gender now fed from the article via the story bible

- **Bible schema upgraded**: the LLM now writes a descriptive best-guess **age** (e.g. "early 20s", "mid 40s", "late 60s", or a specific "23-year-old") inferred from the article, instead of the old 4 coarse buckets (`young|mid30s|mid40s|old`).
- **New `_age_to_number()`** parses a descriptive age into a numeric midpoint (specific year, decade bands like "early/mid/late 20s", and word fallbacks).
- **`_assign_archetype()` reworked** — precedence: role-keyword match (with an age-veto so a young suspect never gets an elderly archetype), then gender + **closest numeric age** among roster archetypes, then generic everyman. A "23-year-old man" and a "retired 70-year-old" now get DIFFERENT archetypes instead of both collapsing to mid-40s.

### Props & location asset sheets OFF by default

- `LOCATION_SHEETS` and `PROP_SHEETS` now **default to 0** (Joe 2026-08-07). The pipeline no longer builds 6-grid location sheets or front/back prop assets — it generates only the **6 individual non-merged character identity panels** per character, plus the new establishing shots. (Set the env var to `1` to re-enable.)

### Chapter cards (black background + match the spoken title)

- **Full-frame black background** behind each chapter card (a new `ChapBg` layer-0 rectangle) so the card never bleeds over the next scene.
- **Card duration = how long the TTS reads the chapter title** — `_build_resolved_title_events` now ends the card at the whisper time of the last spoken word of "Chapter N - Title" (plus a short hold), instead of holding until the next clip's start. Cards no longer stay on too long. Font stays **Bahnschrift** (kicker + title).



## [1.29.0] - 2026-08-07

### Story Bible hardening (no empty bible, no leaked names)

- **Story bible now retries up to 3×** on an empty/incomplete result. A transient LM Studio timeout used to yield an empty bible (silently disabling the visual-hook + character-roster lock for the whole episode). Now `_build_story_bible()` retries fresh until it gets at least a character roster or a visual hook.
- **Deterministic roster enforcement on the shot list (`[CAST-LOCK]`).** Even when the LLM hallucinates or leaks a name from a past episode, the shot list is now hard-filtered so only characters in the story bible's REAL roster (or `NONE`) survive. Invented/leaked names are dropped — belt-and-suspenders that kills the cross-episode 'Stefan Mandel' / 'Richard Lustig' leak for good.
- **Character sheet archetypes are now driven by the bible's gender/age.** `_assign_archetype()` accepts explicit gender/age from the story bible (more reliable than role-keyword sniffing) so e.g. a "23-year-old man" renders young, never as an elderly archetype. The bible's age band also overrides a contradictory role-keyword match.
- **Multi-person character sheets split into individual sheets.** A shot field like 'Name A, Name B' now produces a separate archetype sheet per person (via `_bible_meta_for()`), instead of one combined sheet.
- **Generic shot-list example.** The `SHOT_SYSTEM_PROMPT` no longer hardcodes 'Stefan Mandel' as the example character — it uses a generic placeholder so the LLM never pattern-matches a leaked name into a real shot.

### Thumbnail text fix

- **No more 'FERN' baked into thumbnails.** The thumbnail prompt no longer ends with 'FERN documentary channel style' (which the image model rendered as literal on-image text). It now explicitly forbids the word FERN, channel names, logos, brands and watermarks — only 'SPLIT NODE' (top-left) and the headline (lower third) may appear as text.

## [1.28.0] - 2026-08-07

### Story Bible before script (FERN + Isaac scripting framework)

- **New `_build_story_bible()` stage runs BEFORE the script is written** and locks the episode structure from the article: visual hook (the thing the viewer must SEE), deeper question (the mystery the episode answers), surface + deeper problem, protagonist transformation arc, hero's-journey beats, key numbers/places, and — critically — the **REAL character roster** extracted from the article.
- **Narration is written to follow the bible.** The bible is injected into the narration system prompt (`_narration_prompt_with_bible`), so every paragraph obeys the locked structure and uses only the article's actual people.
- **Removed the episode-template system** (`last_episode.json` load/save). Every story is now written fresh from its own article — no stale formula, no leaked character names from a previous episode.
- **Fixed the character leak.** The shot list now receives the bible's real character roster and is instructed to use ONLY those exact names. Verified: the Alex-casino story now produces Alex / Tracey Elkerton / Willy Allison — no "Stefan Mandel" contamination.

### Deterministic pacing & rhythm (LLM can't break it)

- **`_pace_narration()`** — a deterministic pass that splits overlong sentences at clause boundaries into distinct spoken sentences, and breaks monotone length-runs (Isaac's rhythm rule) so the voice reads with natural variety. No LLM involved.
- **`_pace_gaps_after()`** — per-shot silence gaps computed in code and applied to the audio mix + clip starts: chapter cards 1.6s, rhetorical questions 1.2s, reveal/drop openers 1.0s, hero/ECU beats 0.9s, place anchors 0.7s, default 0.4s. The voice now breathes where the story needs it.

### FERN-style title & description (tags/chapters/Discord unchanged)

- `_generate_titles` and `_generate_description` now receive the story bible and use the visual hook + deeper question to write clickbait titles and descriptions. Tags generation, chapter timecodes, and the Discord link stay exactly as they were.

### Anti-duplicate figure fix (2-humans bug)

- **Negative prompt support added** through the full Krea2 stack (`_krea_generate` → `providers.generate_image` → `krea.generate` → `build_identity_api`). Single-character character-sheet panels and single-character shots now pass `NO_DUPLICATE_NEGATIVE` (bans "two people, duplicate, clone, mirror image, split body...") — on top of the existing grounding_px=768 fix, this steers the sampler away from rendering two bodies on the side/back views. Multi-person shots keep their multiple identities.
- Krea2 can take up to **8 identity references** at once (nodes A–H), so shots with two+ characters lock all their identities in one generation.

### Per-episode resume state

- **`EPISODE_RESUME=<n>` env var** points the pipeline at a dedicated `.resume_state.ep{n}.json`, so two episodes (e.g. one on RunPod + one on Krea2) can run in parallel in the same folder without clobbering each other's state.

### New narration voice

- **Voice clone replaced with Hamza** ("Get Deeper Voice Naturally" short, `youtube.com/shorts/X_957URxtgM`) — clean 18s window, 24kHz mono, loudnorm 0dB → `voice_refs/split_node.wav`. Old ref backed up to `split_node.wav.bak_old`.

## [1.27.0] - 2026-08-06

### Harden real-photo reference search (audit + CDN filtering)

- **Audit no longer rejects on uncertainty.** `_audit_real_photo()` previously required `PERSON: YES` to pass, so when the local vision model returned an unparseable/`?` response every candidate was rejected — meaning NO real ref was ever accepted and the pipeline burned all 99 candidate downloads. It now **only rejects on an explicit `PERSON: NO` or `TEXT: YES`**; an uncertain/`?` response is accepted best-effort (the real photo is kept for identity)
- **Known-bad CDNs skipped before download** — `lookaside.instagram.com`, `tiktok.com/api`, `encrypted-tbn0.gstatic.com`, `ytimg.com`, `redd.it`, `pbs.twimg.com`, `googleusercontent.com`, `facebook.com`/`fbcdn.net`, `gstatic.com` (all routinely serve HTML redirects / 403 / thumbnails) via new `_bad_realref_url()`
- **Candidate cap** — `REALREF_MAX_CANDIDATES` (default 12) stops the search after N real candidates instead of looping 99
- **Failure cache** — when no usable ref is found for a person, the name is written to `cast_refs/real/_failures.json` so future runs skip the search entirely and go straight to the txt2img fallback (no repeat 99-download burn)
- README: updated the real-photo feature bullet

## [1.26.0] - 2026-08-06

### Fix corrupt real-photo refs killing character face panels

- Root cause: some real-person reference photos (Google Images via Instagram's `lookaside.instagram.com`) were saved as **HTML redirect/error pages** with a `.jpg` extension. ComfyUI's `LoadImage` node then failed with `PIL.UnidentifiedImageError`, which cascaded into every character's face panel failing (Stefan Mandel, David van der Zee, Xandem Operator)
- New `_is_real_image()` (PIL decode check) guards `_find_real_reference()`:
  - **Cached refs** are validated on reuse - a corrupt cached `.jpg` is deleted and re-fetched instead of being reused and crashing the face panel
  - **Downloaded blobs** are validated before saving - HTML/bad bytes are discarded and the next candidate tried
- Verified: identity-mode face panel generation succeeds with a valid ref (previously the exact prompt failed); corrupt cached refs are now flagged `False` and re-fetched
- README: noted the real-photo ref is validated as a decodable image

## [1.25.0] - 2026-08-06

### Panels-first character generation

- Character identity panels are now generated in a **dedicated pass before any shot renders** — in both the fresh run (`_generate_all_shots`) and the resume run (`_resume_episode`)
- New `_build_all_character_sheets()` collects every character across all shots, builds their six panels up front, reuses panels already on disk, and **retries face-panel failures** before moving on to shots
- Fixes the cascade where a mid-loop ComfyUI hiccup left the face panel (and therefore the whole character) missing across all ~111 shots — panels are resolved first, then shots reuse them
- README: added the Panels-first feature bullet

## [1.24.0] - 2026-08-06

### Style selection on resume - new style auto re-generates

- On resume, the pipeline now **asks which style profile to use** (numbered list, Enter keeps the current/resume style) via new `_ask_style_selection()`
- Picking a style **different from the current/resume style automatically forces `REGEN_IMAGES=1`** — so the new look actually applies to every image instead of keeping stale shots
- The resume image loop now regenerates **all** shots when `REGEN_IMAGES=1` (was: only missing ones); the fresh-run path got the same style selection coupled to its resume/re-gen prompt
- `STYLE`/`STYLE_PROFILE` env still override the prompt
- README: updated the Resume-safe feature bullet to document the on-resume style prompt + auto-regen on style change

## [1.23.0] - 2026-08-06

### Image-generation resume vs re-generate prompt

- At startup the pipeline now **asks whether to resume image generation or re-generate everything** (R/e), with a `REGEN_IMAGES=1` env var to force overwrite non-interactively
- `_ask_image_regen()` returns the mode; resume keeps already-rendered shots (only missing ones generate), re-generate overwrites every shot image
- In re-generate mode, cached character-sheet panels are also dropped and rebuilt (`_generate_character_sheet` reuse check gated on `REGEN_IMAGES`), so a full rebuild covers shots + panels/sheets
- README: updated the Resume-safe feature bullet to document the prompt + `REGEN_IMAGES`

## [1.22.0] - 2026-08-06

### CRITICAL style enforcement on all image prompts

- `_style_inject()` hardened: the selected style profile is now injected into every shot / character-panel / location / prop prompt as a **CRITICAL, non-negotiable requirement** — emphatic framing that the style is mandatory, overrides all other art direction, and must be applied to the entire frame (background, lighting, color grade, rendering finish)
- Stops shots from dropping, diluting, or drifting to a generic look when the style profile is `arcane`, `noir`, `mannequin`, `roman-statue`, etc.
- README: updated the style-injection feature bullet to document the CRITICAL framing

## [1.21.0] - 2026-08-06

### Codex CLI image backend (local GPT Image 2)

- New **`codex`** image backend in `providers.py`: if the **OpenAI Codex CLI** is installed (`npm install -g @openai/codex`), set `IMAGE_BACKEND=codex` (or `THUMBNAIL_BACKEND=codex`) and every image — shots, character sheets, props, thumbnails — is generated by Codex's `/imagegen` (GPT Image 2), with **no API key needed**
- `Codex` class runs `codex exec --skip-git-repo-check '/imagegen <prompt>'` via PowerShell, then grabs the newest PNG from `~/.codex/generated_images/` (no reliable "saved to X" line — detects the new session file)
- New `_faceupdat_upscale()` — pipes the Codex/GPT-Image-2 output through ComfyUI's **FaceUpDAT upscaler + ImageScale** to reach the shot/panel/thumbnail resolution (in-graph, no second GPU process). Verified 640x360 → 1280x720
- The `codex` backend appears in the startup thumbnail prompt (option 4) and is reachable through the shared `_krea_generate` → `providers.generate_image` path for all image types
- README: `IMAGE_BACKEND`/`THUMBNAIL_BACKEND` now list `codex`; added a "Codex CLI backend" note + image-models table row + updated the backends feature bullet

## [1.20.0] - 2026-08-06

### Custom article URL input

- At startup the pipeline now asks **"Enter a URL, or press Enter for RSS"** - paste any `http(s)` article link to skip RSS entirely and run the full pipeline (script → images → render → upload) on that specific article
- New `_fetch_page_title()` fetches the article's `<title>` tag for the story label (URL-derived fallback if the fetch/title parse fails); the custom URL is recorded as used so it won't be re-suggested
- Invalid non-URL input falls back to the normal RSS scan
- README: added the custom-URL option to the Story Discovery features

## [1.19.0] - 2026-08-06

### Thumbnail provider selection + YouTube metadata docs

- The pipeline now **asks which image-gen provider to use for the thumbnail** at startup (1. local ComfyUI / 2. fal GPT Image 2 / 3. RunPod z-image-turbo) - sets `THUMBNAIL_BACKEND` / `THUMBNAIL_MODEL` (env vars skip the prompt)
- Thumbnails default to fal.ai GPT Image 2 (best text rendering for the "SPLIT NODE" + headline); `providers.py` gained a `generate_thumbnail()` entry point + `_resolve_thumbnail()` that routes the shared image path with 16:9 landscape sizing
- `_generate_thumbnail` now routes through the provider layer instead of a hardcoded FAL call
- README: documents the `THUMBNAIL_BACKEND` selection + a new "YouTube metadata & publishing" section covering **chapterizing** (chapter cards + whisper-pinned timestamps written to the description), **title generation** (3 clickbait titles scored vs trends), **description generation**, **tag generation** (12 LLM tags), and thumbnail generation

## [1.18.0] - 2026-08-06

### Discord multi-server / multi-channel support

- The `discord_bot.py` setup wizard now lets you pick **multiple servers and multiple channels** at once (comma-separated numbers, or by pasting names/IDs), and re-running `--setup` **adds** channels instead of replacing them
- New management commands: `--list` (shows configured channels with their server/channel names), `--remove <id>` (drops a channel)
- `--send` and `--test` now act on **all** configured channels; `send_to_all()` posts the announcement across every server/channel in `DISCORD_ANNOUNCE_CHANNELS`
- The pipeline announcement already iterates every channel in `DISCORD_ANNOUNCE_CHANNELS`, so a single bot token now fans out to any number of servers + channels
- README: updated Discord setup section + Common Commands to document multi-server/multi-channel

## [1.17.0] - 2026-08-06

### Roman-statue style

- New `roman-statue` built-in style profile (10th) - renders every character as a classical ancient Roman marble statue
- Uses the same canonical **real-face method** as the mannequin style: the real person's photo is the single identity reference, and the result is carved from smooth white Carrara marble (chiseled features matching the ref exactly, sculpted marble hair, draped in a classical toga) - license-safe and striking
- `_generate_mannequin_panels` generalized to `_generate_material_panels(look)` shared by both `mannequin` and `roman-statue`; `_look_panels_spec()` + new `ROMAN_STATUE_PANELS` added
- `_generate_character_sheet` routes either material style automatically; text-hair fallback when no real photo exists
- Style preview generated (Elon face-front, real-face method) + added to the README "See the look" gallery and built-ins list (now 10 styles)

## [1.16.0] - 2026-08-06

### Pre-mapped brand logos from Wikimedia Commons

- `premap_logos.py` auto-resolves 1000+ curated brand names (AI/tech, autos, banks, food, retail, airlines, media, gaming, pharma, energy, telecom, insurance, etc) to their Wikimedia Commons logo via the Commons search API, downloads the 512px rasterized PNG, and writes them to `cast_refs/logos/`
- ~450 logos downloaded and **committed to the repo** (cast_refs/logos/ no longer gitignored) - each brand resolves cache-first via `_find_logo`, so no network or SerpAPI needed for pre-mapped brands
- `OFFICIAL_LOGOS` now loads the committed manifest at startup, extending the hand-curated 36-brand registry with the full pre-mapped set
- `_find_logo` verified resolving committed logos (Netflix, Tesla, Nike, Adidas, Walmart, ...) without network
- Re-run `python premap_logos.py` anytime to fill remaining brands (it skips already-downloaded ones)

## [1.15.0] - 2026-08-06

### Docs - system storage requirements

- README now documents the **storage requirement for the default local setup** (~35 GB): ~25 GB of ComfyUI image models (`krea2_turbo_fp8` 13 GB, `z-image-turbo` 5.6 GB, text encoders + VAE), ~5 GB LLM, ~0.5 GB TTS, ~4-5 GB runtime/repo
- Notes that cloud image backends (`IMAGE_BACKEND=runpod`/`fal`) skip the ~25 GB of image models, and that an SSD is strongly recommended since the 13 GB UNET is streamed to VRAM per image

## [1.14.0] - 2026-08-06

### Bring-your-own Discord bot + channel setup

- New `discord_bot.py` (self-contained, stdlib only - no pip installs, no discord.py): a guided `--setup` wizard that creates/attaches your own bot, invites it to your server, and picks an announcement channel
- Commands: `python discord_bot.py --setup / --test / --send "msg"` (also `python system_breakers.py --setup-discord`)
- Discord REST calls now retry on rate limits (429) and 5xx with exponential backoff
- Announcement channels are now configurable via `.env` (`DISCORD_ANNOUNCE_CHANNELS` as comma-separated IDs or `#names`, or a single `DISCORD_CHANNEL`) instead of hardcoded IDs; a fallback keeps older installs working
- `_post_discord_announcement` now routes through `discord_bot` for channel-name resolution + retries; uploads still succeed even if Discord isn't configured (announcement skipped gracefully)
- README: new "Discord announcements setup" section + common commands; verified live against the API (bot connected, 2 guilds)

## [1.13.0] - 2026-08-06

### Video-length prompt - ask minutes, work backwards to paragraphs

- The episode-length prompt now asks for the **video length in minutes** instead of a raw paragraph count
- It works backwards from the chosen length (at ~14.3s per narration paragraph, measured pace) to the target paragraph count: `paragraphs = round(minutes * 60 / 14.3)` - e.g. 25 min -> ~105 paras, 30 min -> ~126 paras
- Default length 25 minutes (`DEFAULT_VIDEO_MINUTES`); the loop lets you confirm, change the length in minutes, or type a raw paragraph count; derived count clamped 10-400 (`MIN_PARAS`/`MAX_PARAS`)
- Confirmed target still persisted to resume state so a resumed job sticks with the job-start count and never re-asks

## [1.12.0] - 2026-08-06

### Hardened RSS article selection - recency-first + rejection cooldown

- Candidate articles are now sorted **most recent first** (matching the filters) instead of only by score - fresh stories surface before older ones, so the same few links stop looping every run
- Article dates captured from HN Algolia (`created_at`) and RSS feeds (`pubDate` / Atom `updated`); `_parse_item_date` parses ISO / RFC-822 timestamps with a 0.0 fallback for missing dates
- Rejected articles are now **persisted** to `.rejected_articles.json` (gitignored) with a timestamp and **not re-presented for 7 days** (`REJECT_COOLDOWN_DAYS` env) - previously a "no" only skipped for that one session
- Old rejection entries older than the cooldown are auto-pruned on load so the file stays small
- Used articles remain permanently excluded; new env knob `REJECT_COOLDOWN_DAYS` (default 7)

## [1.11.0] - 2026-08-06

### Mannequin style - canonical real-face method

- The mannequin style now uses the **real-face method** (Joe-approved): it takes the real person's photo as the single identity reference (krea2edit identity mode) and renders a glossy **porcelain mannequin whose facial features match that person exactly** (bone structure, brow, nose, lips, jaw) - polished museum-mannequin look, not realistic human skin; coloured hair matches the reference
- `MANNEQUIN_PANELS` rewritten to the real-face prompts (face = real photo ref boost 4.0, chained panels = face ref boost 2.0 / 768 grounding)
- `_generate_mannequin_panels` uses the real photo when available, and falls back to text-hair injection when no real photo exists
- Mannequin preview regenerated with the real-face method

### YouTube auto-upload setup - add channel email as test user

- Setup instructions (README + terminal prompt + `oauth_split_node.py`) now include adding the **YouTube channel's email as a test user** in the OAuth consent screen - required until the Google Cloud project is verified, otherwise the auth URL refuses to log in

## [1.10.0] - 2026-08-06

### Foley pipeline - action-driven sound effects

- New `FOLEY_MAP` + `_foley_for_scene()`: each shot's scene text is scanned for the action being performed, and the matching sound is bedded under the whole clip
- Typing → typewriter clicks, driving → engine/traffic, walking → footsteps, rain → downpour, thunder → thunderclap, ocean → waves, river/waterfall → flowing water, boat → boat engine, fire → crackle, door → door close, city → street/construction, jungle → jungle ambience, church/prayer → bells, cooking → gas stove, and more - all mapped to the existing 130+ Nikko Hunt library
- Foley only fires when the LLM didn't already pick an SFX for that shot, so a dramatic hit and an action bed never double-stack on the same beat; beds run for the clip length (bounded to ~8s so long ambience doesn't bleed into the next shot)
- Boat rule moved above driving so "boat engine" maps correctly

## [1.9.0] - 2026-08-06

### YouTube auto-upload setup - prompts for your API secret .json

- When uploads are enabled and no token is authorized yet, the pipeline now **prompts for your YouTube API secret `.json`** before uploading - it prints step-by-step instructions and the link to the Google Cloud Credentials page directly in the terminal log
- `_ensure_youtube_secret()` waits for `client_secret_*.json` to be placed in the project folder (up to 60 min), then upload proceeds once authorized
- `oauth_split_node.py` rewritten to be self-setup: auto-discovers the secret `.json`, prints the auth URL + link, handles the file-based code handoff, and saves credentials to `~/.youtube-upload-credentials.json`
- README: new "YouTube auto-upload setup" section with the full one-time setup (create OAuth Desktop-app client, enable YouTube Data API v3, download secret, save, authorize)

### Mannequin style - text hair injection, no image reference

- The `mannequin` style no longer uses an image reference at all - the porcelain face is fully prompt-controlled and the person's **hair** is fetched as **text** (quick SerpAPI web search -> local LLM extracts one hair sentence -> character-archetype fallback) and injected into each character panel prompt
- New `_is_mannequin_style()`, `_serpapi_web_snippets()`, `_describe_hair_text()`, `MANNEQUIN_PANELS`, and `_generate_mannequin_panels()`; `_generate_character_sheet` routes to the text-hair path automatically when the style is active
- Character panels render as pure text-to-image blank porcelain mannequins with only the described hair carried over - high prompt adherence over identity transfer
- Mannequin preview regenerated through the text-hair path (no image ref)

### Docs - how a tiny local model writes the whole script + free on 8GB VRAM

- README now explains the injection architecture (RSS feed injection, paragraph injection with sliding window, covered-beat dedupe, style injection, single-purpose prompts) that lets a 7.5B local model at 12,222-token context write an entire ~25-min documentary
- New "Run it for free on 8GB VRAM" section: everything runs local on one RTX 3070 8GB (images + LLM + voice + music + render); the only optional paid step is AI video generation for low-end PCs

## [1.8.0] - 2026-08-06

### Provider backends - local / RunPod / fal.ai for images AND video

- New `providers.py`: one entry point for every image and video call, with backend + model selection via `IMAGE_BACKEND` / `IMAGE_MODEL` / `VIDEO_BACKEND` / `VIDEO_MODEL`
- **Images** - `local` (ComfyUI Krea 2 Turbo, default), `runpod` (`z-image-turbo`, `nano-banana-2` edit), `fal` (`flux-schnell`, `flux-dev`, `nano-banana-2`, `z-image-turbo`)
- **Videos** - `runpod` (`hailuo-02-std`, `hailuo-2-3-fast`, `veo3-1-fast` i2v, `p-video`), `fal` (`runway-gen3`, `veo3-1`, `minimax-hailuo`), `local` (ComfyUI video, when a workflow is installed)
- `_krea_generate` now routes through the provider layer (default stays fully local); `_generate_motion_clip` + `_upload_to_public_url` added for AI image-to-video from shots
- New `comfy_manager.py`: auto-start ComfyUI (`run_nvidia_gpu.bat`), health-check, auto-download missing models (Krea 2 / Z-Image / Qwen from Hugging Face), and run API-format workflows
- Keys read from `.env` (RUNPOD_API_KEY / FAL_API_KEY) - never committed
- CLI: `python providers.py --list-images / --list-videos`, `python comfy_manager.py start|check-models|download-models|run <workflow.json>`

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
