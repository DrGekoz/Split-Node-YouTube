# Changelog

All notable changes to Split Node.

## [1.67.0] - 2026-08-16

### Fix: SA3 startup stall + silent single-pass render + resume key-word regen

- **SA3 port prompt no longer hangs startup.** `resolve_sa3_port` auto-detects a single live SA3 UI and uses it silently; if nothing is detected it no longer hard-blocks on a bare `input()` (a run stalled indefinitely waiting for a port that was never detected). Headless/redirected runs (cron, no console, piped stdin - or `SA3_HEADLESS=1`) skip straight to the static music pool; it only prompts when nothing is detected AND stdin is a real console. The startup call is also guarded by `MUSIC_BACKEND=sa3`, so static-pool runs never touch SA3.
- **Single-pass render now shows live progress.** The render used `subprocess.run(..., capture_output=True)` with zero output, so for a multi-minute 10:50 video it looked like a stall right after the title-serialization line and got killed mid-encode (leaving a partial no-moov mp4 - ep001.mp4 was 4.3MB with "moov atom not found"). It now streams `-progress pipe:1 -nostats` to a tqdm bar (`[RENDER] % | ETA`); stderr is drained in a background thread so the pipe can never deadlock ffmpeg.
- **New resume option: "Regenerate key-words from existing narration?"** Pressing `y` re-runs the contiguous key-word LLM extraction on the existing key sentences (`_regenerate_key_words`) and clears the video path so it re-renders to bake the new (contiguous, in-order) keyword highlights - audio mix + whisper cache are reused. Useful after the v1.66.0 contiguous-phrase change to refresh old episodes. Joe 2026-08-16.

## [1.66.0] - 2026-08-16

### Key-word titles: contiguous phrase + per-word spoken-time animation

- The key words on a key sentence are now a 2-3 word phrase that is a CONTIGUOUS, in-order substring of the sentence itself (`_sanitize_key_words`), not 3 words picked at random. It prefers the contiguous span covering the LLM's flagged words and falls back to the most informative contiguous content-word n-gram — always in the exact order they appear.
- Each keyword word is now timed individually with faster-whisper on the voice track. New `_resolve_phrase_word_times` matches the contiguous phrase in-order against whisper word timings and returns a start/end per word; `_build_keyword_events` attaches them to the event as `words`.
- The title engine (`split_node_titles._keyword_events`) now animates each word separately: each word pops in CENTRED on the 0.62H row the instant it is spoken (like the Crayon Diet word-level subtitles) and stays until the phrase ends, positioned contiguously with PIL-measured widths so they never overlap. Offsets are exact — the voice track is the timeline base at 0dB, so whisper times are already absolute video seconds. Joe 2026-08-16.

## [1.65.0] - 2026-08-16

### Fix: resume actually picks up pre-existing shots (style change no longer nukes them)

- A style change on resume no longer force-regenerates existing shots. Previously picking a style different from the episode's current one set `REGEN_IMAGES=1` unconditionally, so a resume that should have reused already-generated images (reconciled against disk) instead re-rendered ALL of them — overriding your explicit "no" to image regen. Now a style change only forces full re-render if you ALSO opted into image regeneration (`_wants_img_regen`); otherwise resume keeps the existing shots and the new style applies only to genuinely-missing ones. `_reconcile_shot_image`/`_reconcile_chapter_card` were already correctly matching the on-disk files; this removes the override that bypassed them. Joe 2026-08-16.

## [1.64.0] - 2026-08-16

### Fix: no stall after the first image batch on resume / batch render

- The v1.62.0 "don't block the batch loop on the next chunk's LLM verify" change went too far: it removed ALL waiting, so the NEXT chunk's shots rendered before their `_verified_prompt`/`_llm_refs` were set. `_regen_one`/`_render_one` then fell back to two inline LLM calls per shot across 20 parallel workers, hammering LM Studio into an apparent stall after the first batch.
- Restored pre-verification with a **two-chunk lookahead**: chunk 0 is verified up front, chunks 1+ are verified in background threads, and each chunk's verify is submitted a full two chunk-renders before that chunk renders - so it is ALWAYS done before the shot fires. `_regen_one`/`_render_one` never fall back to inline LLM calls, and each batch proceeds immediately. The async upscale queue still overlaps codex generation (upscale stays in the background via `providers.enqueue_upscale`), which was the real win Joe wanted. Local (ComfyUI) is unchanged (its upscale runs in the workflow). Joe 2026-08-16.

## [1.63.0] - 2026-08-16

### Fix: chapter-card regen no longer cascades from a shot regen

- Chapter-card regeneration is now controlled ONLY by `REGEN_CHAPTERS`. Previously `REGEN_IMAGES` (which a style-change shot regen sets) was also honoured as a legacy "regen all", so choosing "no" to regenerate chapter cards was overridden whenever you picked a new style and it force-regenerated every card anyway. Now `_generate_chapter_card` drops an existing card only when `REGEN_CHAPTERS=1`, and the resume `_chap_missing` detection regenerates cards only when `REGEN_CHAPTERS=1` or the card is genuinely missing on disk. A shot-only regen (style change) keeps your existing chapter cards. Joe 2026-08-16.

## [1.62.0] - 2026-08-16

### Fix: resume reconciles shots + chapter cards against disk + API-backend batch overlap

- Resume now reconciles SHOT images AND chapter cards against their deterministic on-disk filenames (new `_reconcile_shot_image` + `_reconcile_chapter_card`). Previously the shot `missing_img` detection only checked the stored `image_path` (a stale/missing path caused a genuinely-generated image to be re-done), and the chapter-card checks did the same. Both the resume detection and the pre-render validation pass now adopt whatever's really on disk and only regenerate what's truly absent, so resume picks up char sheets, shots, and chapter cards and continues where it left off. Joe 2026-08-16.
- API backends (codex/fal/runpod) no longer block the batch loop on the next chunk's LLM pre-verify. The async upscale queue already overlaps generation, so the only thing that was stalling the next batch was the verify; it now runs in the background and shots fall back to an inline relevance gate when their verified prompt isn't ready. Local (ComfyUI) still waits, since its upscale runs in the workflow anyway. Joe 2026-08-16.
- runpod and fal now enqueue the same async upscale as codex (`enqueue_upscale` on success), so all three API backends enforce target resolution without blocking the shot loop. Joe 2026-08-16.
- Resume menu gained a dedicated "Regenerate CHAPTER CARD images (overwrite)?" question (sets `REGEN_CHAPTERS=1`) separate from the all-shots regen, so you can rebuild just the cards. Joe 2026-08-16.

## [1.61.0] - 2026-08-16

### Fix: codex batch image grabbing under parallelism

- Each codex image call now runs in its OWN isolated `CODEX_HOME`, so its output lands in a unique `generated_images/` namespace. Under 5-way parallel generation the shared `~/.codex/generated_images` got several fresh uuid dirs at once and the grab couldn't tell which belonged to which call (so ~half of batched gens failed to claim and were retried). Isolation makes grabbing deterministic - each call's dir holds exactly one new image. Joe 2026-08-16.

## [1.60.0] - 2026-08-16

### Arcane style simplified

- Cut the default `arcane` style prompt from 12 lines of overlapping descriptors to a concise descriptor. New arcane = stylized painterly 3D animation, bold inked outlines, cel-shaded graphic-novel texture, gritty weathered surfaces, dramatic rim lighting, saturated slightly-dirty colors, cinematic video-game concept art finish, no text/logos.

## [1.59.0] - 2026-08-16

### Logo download validation

- A logo is only accepted when the downloaded source's filename contains the exact brand word (e.g. `spacex`, `mcdonalds`, `dixpord`), case-insensitive. Candidates whose filename doesn't name the brand are never downloaded; if nothing matches, a new logo is generated as the brand's own ref (`_generate_logo_ref`). Joe 2026-08-16.

## [1.58.0] - 2026-08-16

### LLM backend selector

- At startup, pick which LLM writes the narration/script: **LM Studio** (lists the currently-loaded models, you choose one) or **Codex** (lists models sorted cheapest-first, you choose one).
- All narrative LLM calls route through the chosen backend + model (`_script_chat` dispatches to Codex exec or LM Studio). Aux LM Studio calls (relevance scoring, chapter titles, reachability probe) use the chosen local model.
- Headless/cron runs can set `LLM_PROVIDER` + `LLM_MODEL` env vars to skip the prompt. Joe 2026-08-16.

## [1.57.0] - 2026-08-16

### Image-ref / logo hardening

- `_find_logo` now validates cached logos with PIL and drops corrupt files (e.g. an SVG saved as a .png) so codex never receives an unprocessable ref. SVG logo downloads (Wikimedia/SerpAPI) are rasterized to a real PNG (`_coerce_raster_image`).
- When no real logo exists for an entity, the pipeline generates a logo as its own ref through the configured image provider (`_generate_logo_ref`, "Generate a logo for <name>"), cached per brand.
- `providers.py` adds `_ref_is_valid_image()`: every image ref is PIL-verified before it reaches codex; a bad ref is dropped (with a WARN) so the shot still generates txt2img instead of silently breaking codex claiming.

### Style / prompt cleanup

- Removed '3D character'/'perfect anatomy' from image prompts and LLM shot/character instructions; character look now comes only from style injection.
- Removed hardcoded style from main image prompts; style only via style injection.
- Removed 'machine' from the LLM shot-list b-roll example (was 'ticket machine'); the word only appears when it is part of the actual story/article.

### Repo hygiene

- `cast_refs/` and `episodes/` are no longer tracked in git (copyright/privacy-weighted + large; re-downloaded or generated at runtime). Joe 2026-08-16.

## [1.53.0] - 2026-08-14

### Fix: narration pacing crash on short paragraphs

`_pace_narration` indexed its per-paragraph sentence cap with `caps[i]`, but `i`
only gets assigned inside the inner `for i in range(2, len(sents))` rhythm loop.
For any paragraph with 2 or fewer sentences that loop never runs, so `i` was
unbound and the pipeline died with `UnboundLocalError: cannot access local
variable 'i'`. Switched the outer loop to `enumerate(paras)` and index `caps`
by the paragraph index. Any paragraph length now caps correctly.

### New: resumable batches

A batch no longer vanishes when it crashes. A manifest (`.batch_state.json`)
persists the full list of queued episode configs + a per-episode `pending` /
`done` status. `run_fresh_batch` saves it up front and updates it as each
episode finishes (a finish failure stays resumable instead of being marked
done). On startup `main()` checks for a leftover manifest and offers to resume
the batch: already-finished episodes are skipped, episodes with a saved
per-episode resume state pick up where they left off, and the rest run fresh
from the saved config without re-entering interactive setup. The manifest is
re-saved after every episode so a second crash still resumes cleanly, and is
dropped once the whole batch completes.

## [1.52.3] - 2026-08-14

### Fix: broken byline regex crashed every article fetch

Joe 2026-08-14. `_is_junk_paragraph`'s author-byline regex had an escaped
`\]` inside its character class, producing an unterminated character set that
threw `re.error` on EVERY `fetch_article_paragraphs` call. That made every RSS
candidate report "did not resolve" and get auto-skipped (even though the links
were fine). Rewrote the byline pattern (handles "By John Smith", "By J.R.R.
Tolkien", "by Mary-Kate Jones", initials; case-flexible "By"; no false
positives on story sentences). Verified: fetches that previously failed now
return paragraphs.

## [1.52.2] - 2026-08-14

### Parse links before presenting them

Joe 2026-08-14. `_pick_story` now **fetches + extracts every candidate article
before it's shown to you**. A link that fails to resolve (blocked, dead,
paywalled, empty) is **auto-skipped** with no prompt — you only ever see links
that actually parse, and the next working story is offered instead. The
resolved paragraphs are returned with the accepted story (no double fetch);
custom-URL input is also verified up front.

## [1.52.1] - 2026-08-14

### SA3 startup port prompt: type a port to override

Joe 2026-08-14. At the SA3 startup prompt you can now **type a different port
directly** if the auto-detected one is wrong, instead of only accepting it or
saying no. The detected-port prompt accepts Enter/Y/yes (accept detected), a
port number (override), or n/no (fall through to manual entry). Blank still
skips music and falls back to the static pool.

## [1.52.0] - 2026-08-14

### Story-adaptive Stable Audio 3 music beds via resident medium model

Joe 2026-08-14. The continuous music bed is now generated as a real
text-to-audio bed by **Stable Audio 3** instead of crossfading the static MP3
pool. The SA3 **medium** model is loaded ONCE in the running Pinokio Gradio UI;
generating through its `/generate` endpoint (`gradio_client`) reuses that
resident copy, so there's **no second 5.7GB model reload per episode**. Wired in
`sa3_music.py` (`generate_via_gradio` / `generate_bed_via_gradio`) and driven
from the mix step in `system_breakers.py`.

- **Chunked generation** — any bed section longer than **380s (6:20)** is split
  into N x 380s segments plus a final remainder (e.g. a 20-min episode =
  380s x 3 + 60s), generated separately, then concatenated.
- **STORY-ADAPTIVE** — the story/narration text is split **proportionally**
  across the audio chunks, so each chunk's music prompt reflects the part of
  the story happening in that time window. The two bed sections stay
  suspense (0–65%) → triumphant (65%–end), each prompt now reflecting its own
  section's narration.
- **Ducking** — music base level `-10dB`, ducked to `-19.5dB` under the voice
  via `sidechaincompress` in the mix.
- **Fallback** — if SA3 isn't installed/available or generation fails, the mix
  falls back to the static pool (an episode never breaks). `MUSIC_BACKEND=sa3`
  (default) / `=pool`.

### SA3 startup port prompt (SA3 opens on a different port each run)

Joe 2026-08-14. SA3's Pinokio launcher opens on a **different localhost port
each run** (7860, 7861, …), so the hardcoded `SA3_GRADIO_URL` default was
unreliable. `sa3_music.py` now exposes `resolve_sa3_port(project)`, called at
the top of `main()` (after preflight, **before any pipeline work**). It
socket-probes ports 7860–7890 for live Gradio listeners, fetches `/config` on
the listening ones, and identifies SA3 by its `pingpong` + `Stable Audio`
signature (`detect_sa3_port`). It then asks the user to **confirm the detected
port** (or enter it manually; blank to skip music) and updates `SA3_GRADIO_URL`
in place. Set `SA3_GRADIO_URL` to skip the prompt.

### Narration length cap — max 1 paragraph per article paragraph

Joe 2026-08-14 (ba8b352). The narration script is now capped to keep it tight
and stop length blowup / beat repetition:
- **Max 1 narration paragraph per source article paragraph** (no multi-
  paragraph expansion of a single excerpt).
- Each narration paragraph is capped at **2 sentences per article sentence**
  (and never more than the global `SENTENCES_PER_PARAGRAPH = 4` cap), enforced
  deterministically in code (`_cap_paragraph_sentences`) on top of the LLM's
  requested output.

## [1.49.0] - 2026-08-14

### Story resolve-and-retry (don't quit / skip on a blocked article)

Joe 2026-08-14. Previously the article URL was chosen during setup but fetched
later in the LLM phase, so a blocked / dead / paywalled / empty article aborted
the whole episode (single) or silently skipped a video (batch) after all the
setup prompts. Now `_episode_setup` resolves the article via
`_pick_resolvable_story()`: it fetches the article immediately, and on failure
rejects that URL and loops back to picking a different story. Works for BOTH
single and batch (setup runs once per video), so a batch can't move to the next
video until the current one resolves. The resolved paragraphs are carried in the
config and reused in `_phase_llm` (no second fetch that could fail on a
block-repeat site). Retries up to `STORY_RESOLVE_ATTEMPTS` (default 5).

## [1.48.0] - 2026-08-14

### Character rendering fixes (Bug 1-3, codex backend)

Joe 2026-08-14. The codex (gpt-image-2) shots had three recurring visual bugs:
every shot showed the same frozen facial expression, one character rendered as
two distinct-looking people (one photoreal, one stylized), and the Arcane style
hallucinated hands.

- **Per-shot facial expression + gaze.** `_character_prompt_block` now accepts
  optional `expression`/`gaze`, derived per shot by `_shot_expression_gaze()`
  from the narration + scene (deterministic emotion-keyword map, fail-open to
  the neutral sheet look). Every character block emits explicit `Expression:`
  and `Eyes:` lines, so the same person's face changes shot to shot instead of
  being frozen in one neutral pose.
- **Pre-stylized canonical identity portrait.** New `_stylized_identity_portrait()`
  resolves the real person's photo once, produces a single forward-facing,
  neutral-expression portrait rendered in the channel style, and caches it to
  `cast_refs/real/<safe>_portrait.png`. codex shots now use THIS as the identity
  ref (via `_select_shot_refs`) instead of the raw photo, so every shot holds
  both the person's likeness AND the style - no more photo-vs-style split into
  two distinct characters. Falls back to the raw photo if the pass fails.
- **Anatomy conflict resolved + hands clause.** `_active_render_style()` returns
  a style-aware render style: the photoreal RENDER_STYLE (perfect anatomy,
  subsurface scattering) previously fought the Arcane/stylized profiles and
  drove gpt-image-2 to hallucinate hands. Stylized profiles now get a matching
  stylized render style without the photoreal anatomy language. `_shot_shows_hands()`
  detects hand-visible shots (CU/ECU/hand narration) and appends an explicit
  anatomy-correct-hands clause (five natural fingers, no extra/fused/claw digits).

### Character dedupe pass (Bug 4)

New `_llm_merge_duplicate_characters()` sends the resolved cast list back to the
LLM and asks it to flag semantic duplicates the deterministic alias merge can't
catch (e.g. `Stefan Mandel` vs `Mandel` vs `Stefan`). Wired into
`_collapse_characters` so merged canon propagates to sheets, real-photo refs and
on-screen titles. Fail-open on LLM error; `CHAR_DEDUPE=0` disables.

## [1.47.0] - 2026-08-13

### YouTube titles drop the episode number

Joe 2026-08-13: episode numbers stay internal (folders, filenames, resume
state, descriptions) but the public YouTube video titles no longer carry the
`#NNN - ` prefix. `_generate_titles` stops emitting the prefix (and defensively
strips any the model still adds); the upload fallback titles dropped it too.

### Deterministic video length (no more ballooning)

Joe 2026-08-13: a requested length now actually lands. Previously the length
prompt converted minutes -> paragraphs assuming ~14.3s/paragraph (2-4
sentences), but the 4B model wrote 4-6+ sentences per "paragraph", so a 7-min
request could render ~25 min. Fixes:
- `SENTENCES_PER_PARAGRAPH = 4` hard cap enforced in `_pace_narration`
  (`_cap_paragraph_sentences`), so paragraph count maps to real duration.
- `_write_narration_block` replaces the one-paragraph-per-call writer: ONE LLM
  call per article paragraph asks for EXACTLY N paragraphs of EXACTLY N
  sentences each, split on blank lines in code. This kills both the end-of-
  video beat repetition and the length blowup.
- Intro capped at 3 sentences (was 4-6).

### Multi-track music bed (65% suspense / 35% triumphant)

Joe 2026-08-13: the continuous music bed now CROSSFADES DISTINCT tracks back
to back at their natural length instead of looping one track per section.
`_build_music_chain` cycles the suspense pool for the first ~65% of the
timeline, crossfades into the triumphant pool for the final ~35%. Whole clips
play out - no per-shot cuts, no single-track repetition.

### Unattended easter-egg defaults

Joe 2026-08-13: the easter-egg prompt no longer hangs an unattended run.
`_input_timeout` (msvcrt non-blocking stdin) falls through to defaults: no
answer to "Hide an easter egg?" in 10s -> YES; no answer to the egg choice in
another 10s -> 'duck pope'. Invalid choices also fall back to duck pope.

### Pre-render self-healing (chapter cards + real photos)

Joe 2026-08-13: before ffmpeg, if the internet was off during image gen the
pipeline now heals itself:
- Missing/black chapter cards are regenerated (already handled, confirmed).
- NEW `_retry_realref_before_render`: real-person photo downloads that were
  cached as `no-real-ref` (internet off) are retried; any that now succeed flag
  the affected shots (`_force_regen_realref`) so they regenerate with the real
  face instead of being skipped because an image already exists.

## [1.46.1] - 2026-08-13

### Two-voice narration: announcement intro + storytelling body

Joe 2026-08-13: the narrator now uses TWO cloned voices cut from the SAME
source video (`7AfSuJfFkMY`, "Dark Confession Threads" by Snook):
- `voice_refs/split_node_intro.wav` = the START of the video (announcement
  style) -> the episode INTRO is spoken in this voice, so it sounds like an
  announcement.
- `voice_refs/split_node_story.wav` = the MIDDLE of the video (storytelling
  style) -> everything from chapter 1 onwards is spoken in this more
  storytelling voice.

`_tts_worker` (and the resume gap-fill / render-time repair paths) pick the
voice by narration index: the leading `intro_count` sentences use `INTRO_VOICE`,
the rest use `STORY_VOICE`. `intro_count` is computed from the prepended intro
paragraph and persisted in the resume state so a resume regenerates any missing
clip with the correct voice. `TTS_VOICE` now defaults to the storytelling voice.

## [1.46.0] - 2026-08-13

### Intro is ONE natural paragraph (no more stilted 7-beat list)

Joe 2026-08-13: the intro used to be 7 separate punchy sentences (a JSON array)
which read like a checklist. Now the article is summarized ONE paragraph at a
time (each paragraph -> its own one-line summary, saved), then ALL the summaries
are sent as context to a single intro call along with the intro rules, and the
model writes ONE flowing ~4-6 sentence paragraph that moves through the Split
Node Shorts 6-phase formula naturally (HOOK -> DECLARE -> ASSESS -> ISOLATE ->
PROCESS -> BUILD -> loop-tease). It still flattens into per-sentence shots and
keeps up to 2 key-sentence highlights with real key words.

### Key-word titles show REAL words, not 3 characters

Joe 2026-08-13: the 4B LLM frequently returned key_words as single characters
('c','o','l') so the on-screen highlight read as 3 letters. New `_sanitize_key_words`
keeps only items that are whole-word substrings of the key sentence and, when
nothing survives, falls back to the 2-3 most distinctive content words of the
sentence. Applied to both the narration plan and the intro.

### Character detection + real-person reference hardening

Joe 2026-08-13: the shot-list model sometimes wrote the character field as
'ION CECAN, NONE' or 'Robert Pagliarini, attorney, tax person, financial adviser'.
Those polluted tokens showed up verbatim in the bottom-left person title
('(name), none') AND made the codex real-ref search look up ROLE WORDS as if
they were people, so real-people reference images came out wrong. New
`_clean_character_field` collapses a shot's character to its real names (drops
placeholders + lowercase role/descriptor tokens while preserving genuine
multi-person lists). Because the field is now canonical, every shot of the same
person resolves to the SAME cached real-photo file in `cast_refs/real/` - the
exact same image reference for each character, every time.

### Foley: all SFX to -15dB, typewriter only on real typing

Joe 2026-08-13: foley was too loud / annoying. All foley is now `FOLEY_DB = -15`
(was -5). The typewriter click no longer fires from a bare 'keyboard'/'typewriter'
object in the scene - it now only triggers on active typing verbs ('typing',
'types on', 'at the keyboard', 'taps on', 'hits the keys', etc.) so it never
plays when no one is physically typing in the image and it plays far less often.
The chapter-card whoosh keeps its current volume (`CHAPTER_DB = -4`).

### Chapter titles: single-line pop reveal (alignment fixed)

Joe 2026-08-13: the chapter title used a per-char `\pos` typewriter whose
PIL-measured advances disagreed with libass, producing gaps and a misaligned
yellow glow ghost that made it hard to read. The title (and its glow) are now a
single `\an5` centred dialogue, so libass lays out the proportional font with
correct spacing and the glow hugs the text exactly - no gaps, perfectly aligned.

### Codex prompt no longer breaks on long/quoting shot prompts (ep014)

The providers.py fix from ep014: feeding `/imagegen <prompt>` via a temp file
(`Get-Content -Raw` piped into codex) instead of `echo '<prompt>'` on the
command line, so multi-KB shot prompts with embedded double-quotes can't push
the PowerShell command past its argument-parser limit (the "missing terminator"
instant-fail that blackened shots).

## [1.45.3] - 2026-08-13

### Codex face reference is inspiration, not a copy source

When `IMAGE_BACKEND=codex`, the shot prompt now explicitly tells the model the
attached face reference is guidance only - "use the face image as reference
only - do not copy it directly rather use it as inspiration to get the face of
the person looking correct" - so likeness comes through without the model
copying the ref verbatim into the cinematic frame.

## [1.45.2] - 2026-08-12

### Every narration sentence gets its own image (shot cap removed)

Joe 2026-08-12: the shot count is no longer capped at 120. `MAX_SHOTS` is now
effectively uncapped (400, matching the paragraph clamp), so EVERY flattened
TTS sentence becomes its own shot with its own image + TTS clip - the episode's
ending is never dropped and the narration list, TTS worker and shot list stay
in lock-step. Normal episodes (~150-190 sentences) are never trimmed.

## [1.45.1] - 2026-08-12
## [1.45.1] - 2026-08-12

### Timeline consistency (fresh-eyes review of the full pipeline)

- Clip start times now ALWAYS apply the real per-shot pacing gaps (1.0s
  breathing / 1.6s chapter / 1.2s question). `_compute_clip_starts` runs
  `_pace_gaps_after` before the math, so the '/// NAME' establishing labels and
  other burn times no longer drift earlier by ~0.7s per shot (previously they
  used the stale 0.3s default while the audio used 1.0s gaps).
- `_resume_tts_gap_fill` now invalidates a stale `mix.wav` whenever it adds any
  missing narration clip, so a resumed render rebuilds the audio mix instead of
  reusing an old mix that lacks those clips (which caused silent sentences and
  A/V drift).
- New `_ensure_all_tts_before_render` runs right before the audio mix and
  regenerates any narration clip missing on disk (chapter, narrator and
  per-character clone voices), so a spoken beat is never silently dropped from
  the final video.

## [1.45.0] - 2026-08-12
## [1.45.0] - 2026-08-12

### Spoken narration never cuts off mid-sentence (ep13)

ep13's narration had sentences that played out cut off early - even the
individual TTS files were clipped (e.g. a paragraph ending "...legal conte" or
on a dangling em-dash). The 4B scriptwriter occasionally hit the token cap
mid-sentence; the clipped paragraph was spoken verbatim. This was NOT the
keyword/plan feature (it only extracts words after the script is written).

- New narration truncation guard in `_build_narration_script`: every generated
  paragraph is checked with `_paragraph_is_truncated` (ends mid-word, no
  terminal punctuation, or a dangling em/en-dash). A clipped paragraph is
  re-written (`_write_narration_paragraph`, up to 3 attempts, max_tokens
  raised to 600) and only if every full re-write clips does it attempt a
  targeted completion of the final sentence (`_complete_truncated_paragraph`).
  Every spoken sentence now plays out in its entirety.

### "Story-context words" (crypto / meet character) no longer said verbatim

Establishing shots were inserting synthetic bare narration lines ("Crypto." /
"Meet Thevamanogari Manivel.") that the narrator read aloud - exactly the
labels rule 9b of the script prompt forbids. Now `_inject_establishing_shots`
marks the FIRST real narration sentence that naturally mentions each
location/character as the establishing point instead of inserting a new line.
The establishing shot (wide frame + burned "/// NAME" typewriter label,
camera-shutter + VCR cut) still fires, but the narrator speaks the real story
prose, so names and places enter mid-action the way the prompt intends.

### codex output-claiming hardened further (v1.44.0 follow-up)

Still under heavy parallel codex generation the "Saved at:" path was
frequently unparsed (PowerShell pipes ANSI colour escapes into the captured
text, and the exact path wrapper varies by codex version), so valid images
were marked failed and fell to the black placeholder / were orphaned.

- Strip ANSI escape codes from codex output before matching the path.
- Broaden the path regex to "Saved at:" / "Saved to:" / "image written to:"
  and fall back to ANY absolute .png path, skipping this call's reference
  images so an echoed "-i C:\...
ef.jpg" can never be claimed as the output.

### Never render a black / restarted frame for a missing image

A shot whose image is genuinely missing must never render as a fresh black
clip (or restart the zoom on a reused image).

- `_render_video` now merges visual clips that share one on-screen image: a
  missing shot image is folded into the PREVIOUS clip, extending it to cover
  that sentence's duration too (the prior zoompan keeps going - no restart, no
  black frame), and consecutive clips with the identical image path are merged
  into ONE continuous zoom. The audio timeline is untouched, so every
  sentence's narration still plays at its real absolute time.
- New `_reclaim_orphaned_codex_images`: before rendering, the pre-render pass
  sweeps `~/.codex/generated_images/` for valid PNGs that were generated but
  never claimed and rescues them into the episode folder (reclaim only when the
  orphan count matches the missing-shot count exactly, so a wrong image is
  never assigned to a sentence). Anything still missing is then regenerated.
- HARD GATE (Joe 2026-08-12): after the pre-render reclaim + regen pass, the
  pipeline HALTS before ffmpeg if any shot image is still missing - it never
  renders until every frame is intact.### Chapter cards always read, typewriter + ALL-CAPS titles (Joe 2026-08-12)

Chapter cards were going silent: the shot-list TTS mapper set a chapter's
clip path without verifying the worker produced it, and the resume re-speak
pass skipped chapter shots entirely, so a missing chapter clip was never
regenerated and the card played with no spoken title.

- Chapter TTS is now built programmatically and GUARANTEED: `_finalize_tts`
  generates the 'Chapter N - Title' clip on the spot if it is missing, and the
  regen path re-speaks chapter cards too. The title comes from the same source
  as the description - read exactly once, no LLM duplication.
- Chapter ffmpeg titles now use a TYPEWRITER reveal (per-character + blinking
  cursor, Bahnschrift) instead of the old scale-pop, with a typewriter click
  SFX placed at the title reveal (whoosh already leads the chapter card).
- ALL ASS title burn-ins (chapter, location, person, keyword highlights) are
  now rendered in ALL CAPS.

### Episode length is consistent - the ending is never silently dropped

The shot-list builder capped at 120 shots while the TTS worker queued a clip
for EVERY flattened sentence (~170 for a default episode). So the episode's
ending was silently cut AND dozens of TTS clips were generated for sentences
that never appeared. New `MAX_SHOTS` (default 120) now trims the flattened
narration list to the same window before TTS + shot building, so narration,
TTS and shots stay in lock-step (raise MAX_SHOTS for longer episodes).


## [1.44.0] - 2026-08-12

### Episode 13 QC fixes (faster-whisper audit of ep013)

Audited ep13 end-to-end: transcribed the full 944s voice track with
faster-whisper (word timestamps), cross-referenced every shot image against
the narration at each minute mark, and found 47/120 shot images were MISSING
- codex generated valid PNGs but the pipeline never claimed them, so 35% of
the video rendered as the dark placeholder. Fixed the root causes so shots
never silently fall to black.

### Codex output-claiming reliability (root cause of black frames)

- **Poll for the reported output to appear on disk.** Codex prints `Saved at:`
  before Windows flushes the file (real-time Defender scan + async I/O), so a
  single `os.path.isfile()` returned False and the shot was marked failed even
  though the image existed. Now we poll up to `CODEX_FLUSH_WAIT` (default 15s)
  for the reported path before declaring a miss.
- **Deterministic new-uuid-dir fallback.** Codex creates a FRESH uuid dir under
  `~/.codex/generated_images/<uuid>/` per call. If the `Saved at:` line is
  mangled/absent but exactly ONE brand-new unclaimed uuid dir appeared since
  this call's snapshot, that image belongs to this call and is claimed. This is
  scoped to dirs that didn't exist before the call, so it can never grab a
  concurrently-finished sibling's output (the old wrong-filename bug). Only
  fires when there's exactly one candidate.
- **Broader rate-limit detection** (capacity / temporarily unavailable /
  overloaded / slow down / try again in) so a throttled codex run throttles
  instead of failing shots.

### Render / STT hardening

- `_build_audio_mix`: check returncodes on the voice_raw concat and voice_0db
  volume steps; a transient ffmpeg failure no longer crashes the whole episode
  render with `FileNotFoundError: ... voice_0db.wav`.
- `_ensure_voice_track`: if the padded voice concat fails (empty stderr on a
  long clip list), fall back to a simple unpadded concat so the whisper title
  pass still gets a voice track to time against.

### Pre-render image validation pass (self-healing, wired into fresh + resume)

- New `_regen_missing_images_before_render` runs right before FFmpeg: any shot
  or chapter card whose image is missing/invalid on disk (e.g. Joe deleted it)
  is regenerated in realtime via the active image backend, then the updated
  shot list is persisted back to resume state. The video never renders a
  deleted/broken frame, and only the deleted shots cost a regeneration.
- Also: character establishing shots now keep only the primary name when a
  location intro carries multiple comma-separated people; a `_KNOWN_PERSON_GENDER`
  override stops famous figures (e.g. Matt Damon) being mis-gendered by the
  small local LLM, and role-keyword archetypes of the wrong gender are vetoed.

## [1.41.4] - 2026-08-12

### Position-aware narration (opening / body / outro)

- `_build_narration_script` now tells the LLM which part of the episode it is
  writing (OPENING, BODY, or OUTRO) on every call, so it applies the right rules
  per section instead of assuming a fresh start. The intro already has its own
  dedicated sequence (context-aware); the body gets "vary every paragraph's
  ending"; the outro resolves triumphantly and ends cleanly; the opening never
  uses the twist-tease (rule 17).

## [1.41.3] - 2026-08-12

### Chapter cards show artwork (no black-out) + no repetitive paragraph endings

- **Chapter cards now show the generated ARTWORK with the title burned on top.**
  The old `_chapter_events` painted a full-frame black backdrop unconditionally,
  hiding the card image. Now `_deterministic_chapter_events` flags `has_artwork`
  per card via `_is_black_image(shot['image_path'])` and the ASS black backdrop is
  drawn ONLY for real black placeholders. Real artwork cards show the scene with
  the "CHAPTER N" kicker + title overlaid.
- **Narration: no more "except the story doesn't end there" + question on every
  paragraph.** Rule 11 caps rhetorical questions at 2-3 TOTAL per episode (never
  consecutive-paragraph endings); new rule 17 reserves the "...but the story
  doesn't end there" twist-tease for the intro sequence ONLY (at most once), never
  in body paragraphs; rule 1 cold-open updated to match. Fixes the ep12 repetitive
  feel.

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
