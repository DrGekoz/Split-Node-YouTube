voice_map.json - per-character quote voices for Split Node episodes
===================================================================

Drop a voice-clone reference WAV here (project voice_refs/ folder, like
split_node.wav) and map it to a character name. Any narration shot whose
character name matches gets spoken by that clone instead of the narrator.

Example voice_map.json:

{
  "Stefan Mandel": "voice_refs/stefan.wav",
  "Jessy Irwin": "voice_refs/jessy.wav"
}

Rules:
- Keys are the canonical character names from the story (case-insensitive match).
- Values are WAV paths relative to the project root (or absolute).
- Reference WAVs: clean single-speaker clip, 10-30s, 24kHz mono, loudnorm'd
  (same rules as the narrator clone - see tts-voice-cloning skill).
- Missing mappings fall back to the narrator voice (split_node.wav) silently.
- Create clones with pocket-tts: export-voice from a clip, then point the map
  at the clip WAV (the API needs the audio reference, not the .pt).

To clone a new character voice:
  1. Get a clean 10-30s clip of the person speaking (yt-dlp + energy extract).
  2. loudnorm it to 0dB, 24kHz mono WAV.
  3. Save as voice_refs/<name>.wav and add the mapping above.
