# Changelog

All notable changes to Split Node.

## [1.41.2] - 2026-08-12

### Intro written at end of script-writing from summarized article context

- The intro is now written at the END of the script-writing phase (still before
  any TTS), using a ONE-LINE summary of each article paragraph as context
  (`_summarize_paragraphs`) to save the context window.
- Still prepended to the START of the video, one image per sentence.
- Up to 2 intro sentences are marked KEY (with 2-3 key words) and merged into the
  narration plan, so the intro gets key-word whooshes + on-screen highlights too.

## [1.41.1] - 2026-08-12

### Intro now runs the full Split Node Shorts 6-phase formula

- The episode INTRO is no longer a single 3s hook - the entire opening follows
  the viral shorts sequence: HOOK -> DECLARE -> ASSESS -> ISOLATE -> PROCESS ->
  BUILD -> REVEAL (7 short sentences, one shot each, prepended before chapter 1).
- Strict: NO people names / locations / brand names in the intro - it sets up
  the hook without revealing the specific people or places (those enter in
  chapter 1). The story's REAL key figures are used for the DECLARE claim.

## [1.41.0] - 2026-08-12

### LLM sound-design layer + new narrator voice

- **New voice clone** - `voice_refs/split_node.wav` is now the guy from
  7AfSuJfFkMY (clean 20s solo-voice cut, 24k mono, loudnorm'd). Old clone backed
  up to `split_node.wav.bak_prev`.
- **Intro hook**: LLM generates a snappy ~3s opening hook (shorts 'Declare'
  format) with NO locations/people/brands/figures, prepended before chapter 1.
- **Narration plan** (`_plan_narration`, batched LLM): per paragraph picks the
  ONE key sentence + 2-3 key words (exact substrings) AND a full foley ledger
  (every human/vehicle/object sound + the trigger clause). Persisted to
  `narration_plan.json`; mirrored onto sentence-level shots; fully resumable.
- **Whisper-word timing for ALL SFX**: the audio mix now runs faster-whisper on
  the voice track and aligns key-word whooshes, foley, chapter whoosh and camera
  to the EXACT spoken time - robust to chapter/camera pacing offsets.
- **Key-word whoosh + on-screen highlight**: `soundreality-whoosh-pointer` plays
  its hit exactly on the key word's spoken time (-8dB), and the 2-3 key words are
  burned on screen (pop-in @0.62H) via new keyword ASS events.
- **Foley** (`-5dB`): LLM ledger sounds play at their trigger's whisper time;
  scene-keyword fallback stays. `_fuzzy_foley_match` maps descriptions to the
  sound library.
- **Chapter cards**: `Sub Bass - Whoosh` replaces the boom, hit lands on the card
  transition (-4dB), SFX leads then the card TTS follows (spacious).
- **Camera shutter** only on the FIRST establishing shot of a person and the
  FIRST of a location (-4dB), not every establishing/new-char/new-loc.
- **Pacing**: 1 second breathing gap after every sentence (no cut-offs).
- **Narration rule 9b**: weave people/places into the action - never standalone
  "Meet X" / "The scene is Y" openers.

## [1.40.2] - 2026-08-12

### Packaging framework (Adam Del Duca method) + ep12 render hardening

- **Titles: 6 across 3 proven formulas** (curiosity / number-driven / outcome,
  2 each), all trend-scored, best wins at upload -> AB-test material instead of
  shipping the first guess. `_generate_titles` now returns up to 6 (was 3);
  only `titles[0]` is consumed downstream, so expanding is safe.
- **Thumbnails: art-first + FFmpeg text overlay.** No more rendering text IN the
  image via GPT Image 2 (the recurring garbled-text / "FERN" bug). `_generate_thumbnail`
  generates clean art-only art, then `_burn_thumbnail_text` burns crisp Impact
  "SPLIT NODE" (top-left) + a short curiosity headline (lower third, fitted to
  width) with white fill / black stroke / drop shadow. Font is staged as a bare
  filename beside the output (drawtext rejects drive-letter colons); falls back
  to art-only if the burn fails.
- **Deterministic chapter events** (`_deterministic_chapter_events`): the ASS
  burn only processes `kind==chapter` events, so location/person typewriter
  events can no longer be misread as chapters (missing-card + doubled-slot bug).
- **Single-pass render** + `_purge_ai_slop` / `_flatten_narration_to_sentences`
  / `_is_machine_slop` / `_business_building_clause` hardening carried over from
  the ep12 render reconstruction.

## [1.40.1] - 2026-08-10

### Fix: chapter card timings scrambled on burn (whisper number cross-match)

- ep12's chapter NAMES were correct (the v1.40.0 narration-integrity fix held),
  but the burned card TIMES were out of order (Ch5@655s before Ch3@686s, Ch9
  dumped at 0.00s). `_build_resolved_title_events` searched the WHOLE whisper
  transcript for any "chapter" + number, so a number mis-heard in one clip could
  cross-match to a different chapter. Also its number map only covered 1-6, so
  7-9 always fell back to the raw clip start.
- **Fix:** the "Chapter N" search is now confined to each chapter's OWN narration
  clip window `[clip_starts[pi], clip_starts[pi+1]]`, and the number map is
  expanded to 1-12 (digits + spoken + ordinals), with "chapter" matching the
  number within the next 3 words. Verified: stray numbers in other clips are
  ignored and all 9 chapters resolve in monotonic order.

## [1.40.0] - 2026-08-10

### Fix: stale TTS narration reused on resume -> video/description mismatch

- **The bug (ep11):** the narration clips on disk (`tts_temp/ep_11/narration_XX.wav`)
  spoke a COMPLETELY DIFFERENT story (a Meta/New-Mexico youth lawsuit) than the
  shots, chapter cards, and description (the AI-agents article). A resume gap-fill
  reused any clip named `narration_XX.wav` purely by filename, so a leftover clip
  from an earlier article that reused the same episode number got played over the
  new visuals. Result: the burned chapter titles ("Cracking Hugging Face Vaults
  Open") came from the shot data while the TTS actually said "Anvil drops in Santa
  Fe" - an unmissable mismatch between spoken chapter names and on-screen/description
  titles.
- **The fix:** every time a narration clip is generated we now write a sidecar
  (`tts_temp/ep_N/narration_map.json`) recording a normalized hash of the text that
  was spoken, per narration index (and per-character `char_N` variant). All TTS
  reuse points (fresh worker, resume gap-fill, finalize) now only reuse a clip when
  its recorded hash matches the shot's CURRENT narration text. A clip from a
  different story can never be reused by filename alone again.
- **Conservative migration:** if an episode folder already holds clips but has NO
  narration_map (i.e. a pre-fix state file), `_ensure_tts_sidecar` forces a re-speak
  of every line rather than risk stale narration riding along.

## [1.39.10] - 2026-08-10

### Unattended runs exit cleanly on EOF

- `_yn` and a new `_pause` helper tolerate closed stdin, so a piped/unattended run
  finishes and exits without an `EOFError` traceback at the trailing prompts.

## [1.39.9] - 2026-08-10

### Fix: YouTube upload HTTP 400 "invalidDescription" on long episodes

- The resumable-upload INIT returned HTTP 400 with reason `invalidDescription`
  when the episode description (LLM text + Discord pitch + full whisper-matched
  chapter list) exceeded YouTube's 5000-char cap. The upload silently failed at
  the end of an otherwise-complete render (ep11). `_upload_video_with_progress`
  now clamps the description to ~4990 chars on a newline boundary before the
  init call, so metadata never 400s. Also caps tags at 499 (YouTube max 500).

## [1.39.8] - 2026-08-09

### Resume "no to everything" = true gap-fill (old-state backend auto-detect)

- Selecting "no" to every regen option should just continue the episode where
  it left off, reusing all existing images/TTS/clips. For episodes saved before
  the backend was recorded, the resume could default to `local`/ComfyUI and
  stall trying to build panels on a missing server.
- Added old-state backend detection: if the episode's folder has real
  `chapter_*.png` card images (>2KB), it was generated on codex/fal (local uses
  black placeholder cards), so the resume now infers the codex backend - skipping
  panel generation and using real-person photo refs, no ComfyUI required.
  Combined with v1.39.7's stored-backend restore, a "no to everything" resume is
  now a clean gap-fill that picks up exactly where it stopped.

## [1.39.7] - 2026-08-09

### Resume restores the episode's image backend (no more ComfyUI stall)

- The resume state did NOT store which image backend generated the episode, so
  on resume the backend defaulted to `local` (ComfyUI) even when the episode was
  generated with `codex`/`fal`/`runpod`. A resumed run would try to build
  character panels through a ComfyUI server that isn't running and stall on
  "ComfyUI connection lost". The resume state now stores `img_backend`, and on
  resume it's restored (so codex-generated episodes resume on codex, skipping
  panels). The user's explicit backend choice via the swap-model menu still wins
  over the stored value.

## [1.39.6] - 2026-08-09

### FIX false "style changed" -> forced image re-gen on resume

- When a resume state stored the style as its FULL DESCRIPTION text (e.g.
  "stylized hand-painted comic realism, cel-shaded 3d...") instead of the
  profile name ("arcane"), picking the current style by name compared
  "arcane" against the whole description and wrongly registered as a style
  change - forcing REGEN_IMAGES/REGEN_CLIPS and re-generating every image
  even when the user kept the same style. `_active_style_name()` now maps a
  stored description back to its profile name, so keeping the current style
  is a no-op.

## [1.39.5] - 2026-08-09

### Separate resume control for images vs video clips

- The resume menu now asks separately about images and video clips:
  - "Regenerate ALL images (overwrite)?" - no = use existing images
  - "Regenerate ALL video clips (re-render from images)?" - no = reuse the
    already-generated clips in batch_temp
- New `REGEN_CLIPS=1` env flag forces the video render to re-render every clip
  from its image (ignoring finished clips). Off = reuse finished clips.
- When images are auto-regenerated (script rebuild, style change, model swap,
  or "regenerate all images"), clips are force-rebuilt too since they embed the
  image and would otherwise be stale.

## [1.39.4] - 2026-08-09

### FIX duplicate episode in resume list (dedupe by episode number)

- The resume scan could list the SAME episode twice (once from the legacy
  `.resume_state.json` and once from the per-episode `.resume_state.ep011.json`,
  which both describe ep #011), so the user was asked to resume the same episode
  twice in sequence. `_scan_resume_states` now dedupes by EPISODE NUMBER,
  keeping only the newest state per episode.

## [1.39.3] - 2026-08-09

### FIX title-burn deadlock (ffmpeg stderr pipe)

- The pass-2 title burn (`split_node_titles.burn_titles`) could HANG: it read
  ffmpeg's stdout for the progress bar but did NOT drain stderr until after
  stdout ended. libass emits a lot of stderr output (font warnings), and once
  that filled the ~64KB stderr pipe, ffmpeg blocked writing stderr while the
  parent blocked reading stdout - a classic pipe deadlock that froze the burn
  after the render was done. stderr is now drained in a background thread
  throughout the burn (and collected so it can be surfaced on failure).
- Verified with a real tiny-clip burn: completes instantly, no deadlock.

## [1.39.2] - 2026-08-09

### TTS gap-fill now runs BEFORE image generation on resume

- On resume, the narration TTS gap-fill now runs FIRST (before image gen), so
  images are never generated against narration audio that doesn't exist yet.
- The gap-fill logic was extracted into a reusable helper
  (`_resume_tts_gap_fill`) that reuses clips already on disk (both the narrator
  `narration_XX.wav` and per-character `narration_XX_char.wav` variants) and
  generates only what's missing, with the correct per-character voice.

## [1.39.1] - 2026-08-09

### TTS resume gap-fill fixes

- When TTS regenerate = no, the resume flow now correctly gap-fills: it checks
  which narration clips are already on disk and only generates what's missing.
- Fixed the gap-fill to match BOTH the narrator clip (`narration_XX.wav`) AND
  the per-character clone clip (`narration_XX_char.wav`, used when a shot's
  character maps to a different voice via voice_map.json). Previously it only
  looked for the narrator file, so character-voiced shots were incorrectly
  re-spoken with the narrator voice even when their clip already existed.
- Missing clips are now generated with the correct per-character voice.

## [1.39.0] - 2026-08-09

### HARDENED parallel chapter-card filenames + context-aware logo placement + depth of field

- **FIXED the persistent wrong-filename bug on chapter cards (parallel kept)**.
  Root cause: after codex generates, the pipeline had a "newest unclaimed file"
  fallback that, under parallel card generation, could grab ANOTHER card's
  output and copy it under the wrong name. That fallback is REMOVED - codex
  reports the exact "Saved at: <path>" it produced for each call, and that
  deterministic path is the ONLY way a card claims its output. A missing
  deterministic path now returns failure (clean retry of THAT card) instead of
  guessing, so a card can never be saved under another card's filename.
  Verified with real 4-6-way parallel codex tests (distinct outputs, correct
  mapping) with and without image refs.
- **Separate chapter-card regen honoured**: `_generate_chapter_card` now checks
  `REGEN_CHAPTERS` (in addition to legacy `REGEN_IMAGES`) so a stale/wrong
  cached card is dropped when chapters are regenerated independently.
- **Context-aware business logo placement**: brand assets now come in three
  context variants - `screen` (hacker monitor), `building` (exterior HQ/facade
  logo), and NEW `interior` (logo on the wall behind the reception counter /
  front desk inside). `_brand_context`, `_match_brand_asset` and `_select_shot_refs`
  pick the right variant from the scene (interior cues -> interior asset,
  HQ/exterior -> building, else screen).
- **Realistic camera depth of field** added to every shot and chapter-card
  image prompt (natural bokeh, tack-sharp subject, shallow-to-medium DOF).

## [1.38.6] - 2026-08-09

### Separate shot/chapter regen prompts + shots drop no-text when a business logo ref is attached

- **Ask separately whether to regenerate SHOT images vs CHAPTER CARD images**
  (they're now independent). Env overrides: `REGEN_SHOTS`/`REGEN_IMAGES` for
  shots, `REGEN_CHAPTERS` for chapter cards (legacy: `REGEN_IMAGES` alone
  controls both).
- **Shot prompts drop the "NO text / NO watermark" ban when a business logo is
  attached** (same logic as chapter cards): if a shot is a business-location
  shot (or the ref-check picked a brand), the logo's wordmark is allowed, while
  any OTHER text/captions/labels/signage is still forbidden. Non-business shots
  keep the full NO text clause.

## [1.38.5] - 2026-08-09

### Chapter-card logo injected naturally (no manual placement)

- Chapter-card business logo is now injected into the FULL composition via GPT
  Image 2's normal behaviour - removed the previous "place at top 15% /
  outskirts" instruction. The logo is simply named and the model integrates it
  naturally where it fits. When a logo ref is attached, the card's "NO text /
  no watermark" hard ban is relaxed (so the logo's wordmark can render) but
  still forbids any OTHER text.

## [1.38.4] - 2026-08-09

### ~200 prop visuals injected into shots + chapter cards + parallel cards with correct filenames

- **~200 named props** (vaults, libraries, casinos, labs, servers, vehicles,
  money, security gear...) in a new `prop_visuals.py`. When a shot's narration
  or scene names a prop, its visual descriptor is injected into the shot prompt
  so it appears in-frame with the right context (e.g. 'vault' -> a massive
  steel bank vault; 'academic halls' -> a grand university library). Wired into
  `_build_shot_prompt` and the chapter-card background.
- **Chapter cards run in PARALLEL again with CORRECT filenames**: codex now
  reports the exact "Saved at: <path>" it produced for each invocation, so each
  call claims its OWN output deterministically - the old "newest unclaimed
  file" scan could let card A copy card B's art when two finished concurrently
  (the wrong-filenames bug). Deterministic claim is race-free under parallelism,
  so cards are fast again while keeping correct names. Falls back to the
  newest-file scan only if the path can't be parsed.
- Thumbnail uses the same style prompt as the main video.

## [1.38.3] - 2026-08-09

### Fix chapter-card wrong filenames (sequential) + overlap shot verification + business-location logos + thumbnail style

- **FIX chapter cards getting wrong filenames**: chapter cards were rendering
  in PARALLEL, and codex's "newest generated image" claim raced - each card
  could copy another card's output, so cards got the wrong art/filename. Cards
  now render SEQUENTIALLY (one at a time) in BOTH fresh and resume paths, which
  eliminates the race entirely.
- **LLM shot-verification overlaps card generation**: while the chapter cards
  generate, a background thread LLM-verifies + ref-checks ALL shot prompts, so
  the LLM is busy during card gen and shots are ready to fire the moment cards
  finish.
- **Business-location logos**: improved `_is_business_shot` to detect a business
  location from brand name + location cue (e.g. 'OpenAI California') even
  without an explicit HQ keyword, and `_select_shot_refs` now attaches the
  BRAND BUILDING asset (real logo baked onto the facade) for location shots -
  not just the bare logo mark.
- **Thumbnail uses the same style prompt as the main video** (via
  `_style_inject()`), so the thumbnail matches the episode's look exactly.
- **Arcane style prompt** replaced with the new hand-painted comic-realism
  spec + explicit NO TEXT/no-words/no-letters/no-watermarks/no-logos to stop
  GPT Image 2 hallucinating artifacts.

## [1.38.2] - 2026-08-09

### Canonical shot ordering + 'high detail illustration' prompt hardening

- **Canonical image order tracked via `seq`**: every shot now gets a `seq`
  field = its exact 1-based position in the FINAL ordered shot list - the SAME
  order ffmpeg uses to assemble the video (`enumerate(shots)` in
  `_render_video`). Shot filenames (`shot{NN}_...png`) and the clip/frame
  assembly are both keyed on `seq`, so the right image always lands on the
  right frame regardless of generation order, parallel chunks, or
  `narration_idx` gaps. Previously filenames used `narration_idx`, which could
  diverge from the true display position and produce mis-ordered files.
- **'high detail illustration' added to every image prompt** (shots AND chapter
  cards) to stop GPT Image 2 hallucinating weird artifacts.

## [1.38.1] - 2026-08-09

### Fix run stall + pipelined chunked shot generation + chapter-card title-only logos

- **FIX the random stall**: the pre-verify pass ran the LLM relevance gate AND
  the ref-check on ALL shots up front (2 LLM calls x N shots) with zero
  progress output - so when LM Studio got busy, each call could hang on the
  180s timeout and the whole run died before generating a single image. Now
  shots process in chunks.
- **Pipelined chunked generation (5 at a time)**: the LLM verifies + ref-checks
  a chunk of `SHOT_CHUNK_SIZE` (default 5) shots (the go-ahead), then those 5
  fire in PARALLEL to codex, and while they generate the LLM verifies the NEXT
  5 in a background thread (overlap) - the LLM never idles and codex never
  waits on the LLM. Clear per-chunk `[CHUNK n] rendering (shots ...)` progress.
  Fresh + resume paths. Override chunk size with `SHOT_CHUNK_SIZE`.
- **Ref-check fail-fast**: added a deterministic keyword path (narration/scene
  literally naming a cached brand or known character attaches the ref with NO
  LLM call) and a reachability gate so the ref-check never hangs 180s when LM
  Studio is busy.
- **Chapter-card logo only when the title names the business**: the logo
  image-ref is attached ONLY if the chapter TITLE itself contains the company
  name (e.g. 'hugging face vaults' -> Hugging Face logo). A company that only
  appears in the narration context informs the background scene but does NOT
  get a logo ref.
- **Chapter-card main prompt = title-derived background FIRST**, then the
  channel style + logo injections AFTER (style/brand are finishing touches,
  never the lead).

## [1.38.0] - 2026-08-09

### Premium adaptive image prompting: chapter cards + narration-grounded shots

- **Chapter cards are now grounded in the actual chapter**. The background
  prompt is built from the chapter title PLUS the real narration content of the
  shots inside that chapter, so the art matches what the narrator says - not a
  bare title.
- **Business logo refs on chapter cards**: if a chapter is about a real company
  (e.g. 'hugging face vaults' -> the Hugging Face company), its real cached
  logo is attached as an image ref and the prompt places it on the OUTSKIRTS of
  the frame (top middle ~15%, top-left/top-right) - never in the centre, which
  stays completely open for the title text overlaid later.
- **Shots are grounded in their actual TTS narration**: every shot prompt now
  feeds in the exact narration line spoken over that shot, so the rendered
  scene, subject, business, place and action match the audio 200%.
- **LLM ref-check for shots**: before the parallel batch, an LLM inspects each
  shot's narration + scene and decides IF a business or character is being
  mentioned and WHETHER to attach its image ref (logo / real photo) - the
  correct ref is chosen from the narration context, not just heuristics. Wired
  into both fresh and resume paths. Only picks from already-cached logos (never
  triggers a network logo search in the hot path).
- **Removed ALL concrete examples from every LLM prompt** (adaptive prompting
  only): the shot-list example line, chapter-title example, narration rule-8
  figures, brand-extract example, relevance-judge example, and the story-bible
  age example. This stops the model from copying a stock scene/place/title
  (same root cause as the earlier 'Paris, France.' leak) - everything is now
  derived from the article's own content.

## [1.37.1] - 2026-08-09

### Fix: "Paris, France." leaked into narration via the PLACE ANCHORS prompt example

- Rule 9 (PLACE ANCHORS) of the narration prompt literally showed the LLM
  `'Paris, France.'` as an example location. The model copied that exact string
  into narration even when the article had nothing to do with Paris. The RSS /
  'beat the system' keyword filter was NOT the source (no Paris in feed logic);
  it was purely the prompt example leaking through.
- Rewrote rule 9 to instruct a REAL place actually named in the article, with an
  explicit "NEVER a famous city or location that is not in the article" clause,
  and removed the concrete example string so there's nothing for the model to
  copy. Verified zero "Paris" references remain in the pipeline.

## [1.37.0] - 2026-08-09

### Bulk-parallel codex at the measured optimum (20) + rate-limit throttle

- **Bulk-parallel codex benchmark** (measured live, 5–40 concurrent calls):
  throughput peaks at **20 concurrent codex calls (~478 img/hr)**. Below that
  you leave rate-limit headroom on the table; above ~25 it collapses because
  every call contends for the ONE remote gpt-image-2 quota:

  | N  | img/hr |
  |----|--------|
  | 5  | ~130   |
  | 10 | ~220   |
  | 20 | ~478 (peak) |
  | 25 | ~390   |
  | 30 | ~230   |
  | 35 | ~274   |
  | 40 | ~252   |

- **Codex default concurrency 3 -> 20** (`_image_concurrency`). Local ComfyUI
  stays sequential (1) as before. Override with `IMAGE_CONCURRENCY`.
- **FIX - stale-image fallback**: the old output-claim code, when codex produced
  no NEW file, silently grabbed any pre-existing image in `~/.codex` and
  reported it as a success (and two parallel threads could even claim the same
  stale file, corrupting bulk runs). Now it only claims a file that appeared
  during THIS call; no new output is a genuine failure.
- **Rate-limit throttle (no model fallback)**: if codex/gpt-image-2 is
  rate-limited (no new output), it does NOT fall back to fal/runpod/local. It
  waits one hour (jittered ±10% so parallel threads don't re-trip together as
  a thundering herd) and retries a single image; it keeps doing that until one
  succeeds, then the batch pushes the next image. `CODEX_RATELIMIT_WAIT` env
  overrides the hour.
- **Batch prompt pre-verification**: before the parallel batch fires to codex,
  every shot's final prompt is relevance-gated vs the story topic sequentially;
  off-topic scenes are rewritten up front so a bad prompt can't waste a
  parallel slot mid-batch. Verified prompt cached and reused by the parallel
  pool (no per-shot LLM latency in the hot loop). Applied to both fresh and
  resume paths.

## [1.36.0] - 2026-08-09

### Batch multi-video pipeline + resume-all + reliable async upscaling

- **Batch mode**: the run prompt now asks "How many videos?" (default 1). For
  each video it runs the exact setup flow (episode number, paragraph count,
  resolution, thumbnail provider/model, image provider/model, style, story)
  before moving to the next, then generates them all. Every episode gets its
  own resume state file (`.resume_state.ep{NNN}.json`) so episodes in a batch
  can be resumed independently.
- **Resume-all**: on startup it scans every resume state on disk (legacy
  `.resume_state.json` + per-episode files) and asks per episode whether to
  resume it; answering yes to all runs them all in sequence.
- **Parallel orchestration**: a fresh batch runs ALL LLM/script stages first
  and queues TTS for every episode. For local Krea 2 the image pass waits for
  all TTS (GPU contention); for codex/API backends image generation runs
  simultaneously with TTS, in parallel across episodes.
- **FIX - async upscale worker crash**: the per-image upscale progress bar
  overran its estimated total, making tqdm throw `unsupported format string
  passed to NoneType.__format__`. This killed the worker thread *before* it
  joined the upscale thread, so the upscaled output was never finalized and
  every shot stayed at the source resolution (the "waiting to be upscaled"
  symptom). The bar is now capped at its estimate and the worker always joins
  the upscale thread. RealESRGAN x2 estimate tuned to avoid overrun.
- Generated image paths are logged with each shot, and each image's upscale
  shows a live progress bar plus a `[UPSCALE] OK <name> (WxH) in X.Xs`
  completion line.

## [1.35.5] - 2026-08-09

### Chapter cards: relevance vs title + article, parallel gen, descriptive filenames; upscale visibility

- **Chapter card relevance vs BOTH the article title AND the chapter name**: the
  card background prompt is judged against the article topic (via `_IMG_TOPIC`)
  AND the chapter title itself (passed as `CHAPTER CARD {n}: {title}`), and the
  background is rewritten + re-judged if it drifts off-topic. Chapter names are
  already stored in the resume file (`chapter_title` on each chapter shot +
  `chapter_events`).
- **Chapter cards generate in PARALLEL** (`IMAGE_CONCURRENCY` workers) instead of
  one-at-a-time - the parallel-safe codex output claiming makes the old
  sequential pre-pass unnecessary. Big speedup on the 9-card pass.
- **Descriptive chapter card filenames**: `chapter_{NN}_{slug}.png` e.g.
  `chapter_01_cracking_hugging_face_vaults_open.png` (name from the chapter
  title, filename only - the card image stays clean).
- **Per-image upscale progress bar + completion log**: the async upscale worker
  now shows a progress bar per image and logs `[UPSCALE] OK <name> (WxH) in X.Xs`
  when it finishes, so it's clear images ARE being upscaled (they were silently
  waiting in the async queue at codex's native res, which looked stuck).
- **Shot log shows the generated image path** so each result is identifiable in
  the terminal.

## [1.35.4] - 2026-08-09

### Shot images are 100% text-free + descriptive filenames

- **NO text in any shot image, ever**: a hard `NO_IMAGE_TEXT` clause (no text,
  words, letters, captions, labels, signage, subtitles, watermarks, typography)
  is appended to every shot prompt. All on-screen labels (e.g. establishing
  `/// NAME`) are burned by FFmpeg at render time - never in the source art.
- **Descriptive filenames**: shots are now saved as `shot{NN}_{brief}.png` e.g.
  `shot01_hugging_face_switzerland.png` instead of `shot_{seed}.png`. The name
  is derived from the establishing label or the narration lead, sanitised +
  truncated. The description lives ONLY in the filename; the image itself stays
  clean. Applies to both the fresh and resume paths (retries overwrite the same
  file).

## [1.35.3] - 2026-08-09

### LLM prompt-relevance gate (stops off-story images like the "Mayan pyramid")

- Before every shot image and every chapter card is sent to the image backend,
  the FINAL prompt (scene + style + codex hardening + everything) is passed to
  the local LLM and cross-referenced against the **article title** for relevance.
  If it's judged off-topic, the shot's scene is rewritten by the LLM (grounded in
  the article) and the prompt is rebuilt + re-judged, up to `SHOT_RELEVANCE_RETRIES`
  (default 2). Chapter cards get the same gate via a topic-anchored background.
- `_llm_chapter_bg_prompt` is now topic-aware so card backgrounds belong to the
  story's world, not a random abstraction.
- **Never blocks the pipeline**: `SHOT_RELEVANCE=0` disables it entirely; when
  LM Studio inference is unreachable (a fast 8s chat probe) the gate fails open
  and every prompt passes through untouched - so a dead LM Studio can't hang the
  run on the 180s per-call timeout. Wired into both the fresh and resume image
  paths.

## [1.35.2] - 2026-08-09

### Text is NEVER baked into shots or chapter cards - FFmpeg burns it at the end

- **Establishing shots render clean**: the `/// NAME` label is no longer baked
  into the codex/fal shot image (prompt had "Render the text '/// NAME' in the
  bottom-left corner..."). Every establishing shot now gets a dedicated
  `/// NAME` typewriter title burned by FFmpeg at render time (Myriad Pro Bold,
  red for locations / gold for persons), via a new `_build_establishing_events`
  + `_merge_establishing_titles` pass that guarantees exactly one label per
  establishing frame and dedupes it against the narration-scanned location/person
  anchors.
- **Chapter cards render clean**: `_generate_chapter_card` no longer asks GPT
  Image 2 / codex to render `Chapter N - Title` text onto the card - it produces
  a clean thematically-matched background, and the ASS chapter title is burned
  over it. Removed the codex "skip the ASS chapter burn" logic so the burn
  always fires (matches the local-backend behaviour).
- **Font**: location/person typewriter titles (TypeLoc / TypePerson / ghosts)
  switched from Consolas to **Myriad Pro Bold**. It's a proportional font, so
  `_typewriter_events` now measures each character's advance (PIL) for the
  reveal + cursor instead of assuming monospace. Font resolved from the project
  `fonts/` dir first, then `C:\Windows\Fonts`; the burn filter passes a
  `fontsdir` so libass finds it even when not installed system-wide.

> NOTE: Myriad Pro Bold is a commercial Adobe font not present on this machine -
> drop `MyriadPro-Bold.otf` into `F:\aaaaaVIBECODING\System Breakers\fonts\`
> for it to render (until then libass falls back to a default).

## [1.35.1] - 2026-08-09

### Fix: upscale daemon reported false "neural upscale failed" for paths with spaces

- The `DONE <out_path> <0|1>` line was parsed with `line.split()` and read `parts[2]` as the ok flag. With a space in the path (e.g. `System Breakers`) the path breaks across tokens, so `parts[2]` is a path segment, not `1` — every upscale reported failure even though the output file was written correctly (cards/shots came out at the right 1920x1080). Now reads `parts[-1]` (the flag is always the last token).

## [1.35.0] - 2026-08-09

### Parallel image generation + async upscale queue (fixes FaceUpDAT OOM stall)

- **Parallel generation**: `IMAGE_BACKEND=codex/fal/runpod` now render shots in PARALLEL (`IMAGE_CONCURRENCY`, default 3) via `ThreadPoolExecutor`. Panels within one character stay sequential (they chain). Local ComfyUI stays 1-concurrent (a single server serialises anyway).
- **Codex output detection is parallel-safe**: each `generate_image` call snapshots the on-disk image set under a lock, runs codex, then claims the NEWEST file that appeared during its own call and wasn't already claimed (`_scan_lock` + `_claimed` set). Verified: 3 parallel codex calls produce 3 distinct images, no collision.
- **Async upscale queue**: codex shots enqueue their resolution enforcement and return immediately, so the next prompt fires while the upscaler catches up. A single background worker drains the queue using the persistent upscale daemon. `providers.flush_upscales()` blocks until the queue is empty and is called before the render pass consumes the images. The color grade runs AFTER the upscale (async), never inline.
- **Upscaler switched to 2x RealESRGAN** (`RealESRGAN_x2plus.pth`, spandrel CUDA bf16, ~1s per image): the 8GB card OOM'd on `4xFaceUpDAT` when a 1280x1280 source blew up to a 5120x5120 intermediate, which stalled episode 11's char-sheet pass. FaceUpDAT (4x) is now the fallback used only for genuine >=2x upscales.
- **Persistent FaceUpDAT/RealESRGAN daemon**: model load happens once per run (`faceupdat_upscale.py --serve --model`, line-in/DONE-line-out), then every upscale reuses it. Falls back to one-shot if the daemon can't start.
- `codex_single_test.py` + `codex_parallel_test.py` committed for regression testing parallel codex gen.

## [1.34.1] - 2026-08-09

### ComfyUI check moved AFTER the image-backend prompts (no premature block)

- The launcher (`SystemBreakers.bat`) no longer hard-blocks when ComfyUI is down — the ComfyUI check is now a **non-blocking WARN** there ("Only needed if you pick the LOCAL image backend").
- The real gate now runs in `main()` **after** the thumbnail and episode-image backend prompts. Only the **local** image backend needs the ComfyUI server (Krea 2 gen). If you pick **codex / fal / runpod** for the episode images (no local anywhere), the run proceeds fine with ComfyUI down — FaceUpDAT upscaling runs directly in Python.
- If the episode backend IS local but ComfyUI is down, it explains why and lets you abort or continue, instead of silently dying before you've chosen anything.

## [1.34.0] - 2026-08-09

### Codex CLI image backend now uses image references + runs FaceUpDAT in Python (no ComfyUI server)

- **Image references via `-i`**: the Codex backend (`IMAGE_BACKEND=codex`) now attaches reference images with `codex exec -i <file>` — real-person photos feed the character sheets, and character panels / brand logos feed each shot — so identity and style carry through just like the local backend.
- **FaceUpDAT runs DIRECTLY in Python**: new standalone `faceupdat_upscale.py` loads `4xFaceUpDAT.safetensors` with torch + spandrel via ComfyUI's embedded Python (CUDA). No ComfyUI server is required for upscaling — a codex/fal run hits the target resolution without ComfyUI up. PIL lanczos remains only as a last-resort fallback if torch/spandrel is missing.
- **Sizes enforced**: shots upscale to 1920x1080 (16:9), character panels to 1280x1280, only when the model output is smaller (never downsizes).
- Fixed two Codex CLI gotchas: when any `-i` ref is attached codex reads the prompt from STDIN (now always piped via `echo`), and Codex 0.147+ renames outputs to `call_*.png` (glob now matches both `call_*` and `ig_*`).

### Businesses are no longer personified as people

- New `_is_business_name()` (curated `KNOWN_COMPANY_NAMES` set + corporate suffix/word regex) stops the LLM treating a company as a person: SpaceX, 'the company', the IRS, HackerOne etc. are skipped in `_build_character_sheets` and demoted to `NONE` after the shot-list CAST-LOCK, so they render as their scene/logo instead of a human. The brand logo still attaches as a shot ref for HQ shots.

### Chapter title cards + establishing-shot labels (Codex / fal)

- **Chapter cards**: when using the codex or fal backend, each chapter gets a real rendered "CHAPTER N -- title" card image (GPT Image 2 is very good at text) shown while the narrator reads the chapter; the ASS chapter burn is skipped for codex runs so the text isn't doubled. Local still uses the black placeholder + ASS card.
- **Establishing shots**: for codex/fal the name/location is baked into the image bottom-left (`/// LOCATION NAME` for a location, the name for a character); the matching typewriter burn is dropped to avoid doubling.

### Mix levels

- Music bed now **-19.5dB**, SFX **-15dB**, camera shutter **-5dB** (was -18 / -14 / -4).

## [1.33.0] - 2026-08-07

### TTS finishes before image generation (no more GPU contention)

- The fresh-run pipeline used to run TTS and image generation **concurrently** - the TTS worker kept going in the background while `_generate_all_shots` started hammering ComfyUI/Krea. Both hit the same GPU (PocketTTS and image gen), causing VRAM contention.
- The TTS worker still **starts early** (right after the narration is written, so the clips generate while the bible / scene board / shot list / character sheets / brand + location + prop assets are being built), but the pipeline now **joins the worker and finalises every narration clip BEFORE `_generate_all_shots`** runs. Image generation only starts once all TTS (including per-character clone voices) is finished and the GPU is free.

## [1.32.0] - 2026-08-07

### Killed the "Goulburn / Queen Square, Sydney" leak at the source

- **Root cause found**: the narration system prompt's STYLE RULES embedded Luke Moore demo specifics as its examples - "Goulburn, New South Wales." / "Queen Square, Sydney." (rule 9 place anchors), his exact figures ("$2.1 million", "$9 fee", "$449 a fortnight", "five taps of $4,999"), and his metaphors/rhetorical questions ("Who is watching this account?", "heart stopping between beats"). The LLM copy-pasted these exemplars into every unrelated article - which is why those two Australian places kept appearing everywhere.
- **All demo specifics generalized** in `NARRATION_SYSTEM_PROMPT`: rule 8 now says use the ARTICLE's exact figures (placeholder `'$X million', 'Y months'`), rule 9 now uses generic examples ("Paris, France." / "The airport tarmac.") and explicitly forbids importing a location from another story, and rules 10-13 were rewritten with non-episode-specific wording. Verified: zero leaked demo terms remain in any prompt constant.
- **Hard guard on extracted places**: `_build_episode_context` now drops any extracted place whose key tokens are NOT actually present in the article text (e.g. "Goulburn, New South Wales" / "Apollo Global Management" are rejected when the article only says "the United States"). Belt-and-suspenders on top of the prompt fix.

### No more back-to-back same-location repetition

- New **`_dedupe_consecutive_locations()`** runs right after the narration script is built (before chapters/anchors/establishing so all index maps stay aligned). If two+ consecutive paragraphs open with the **same** location anchor, it strips the redundant location **prefix** from the later ones - the paragraph's actual content is preserved, only the repeated "Goulburn, New South Wales." / "Queen Square, Sydney." lead is removed. A location can still recur across the episode when separated by other content (a scene shift back to a prior place still re-states it).

## [1.31.1] - 2026-08-07

### Fresh run now asks for the episode image provider too

- New **`_ask_image_backend()`** prompt on every fresh run asks which provider to use for the **actual episode shot images** (local / fal / runpod / codex), just like the thumbnail provider prompt. Writes `IMAGE_BACKEND` / `IMAGE_MODEL`.
- Default is **local** (ComfyUI Krea 2 Turbo) because the shots use character-identity panels as reference images, which only the local backend honours. Cloud backends (fal / runpod / codex) are text-to-image only and drop the identity/face refs.
- Thumbnail and episode images are asked separately and can use different backends.

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



## [1.30.0] - 2026-08-07

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
