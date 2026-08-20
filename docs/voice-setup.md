# Voice notes for the Telegram bridge — one-time setup

Send Nao a Telegram voice memo and it gets transcribed **locally on the
mini** (whisper.cpp — audio never leaves the machine), echoed back as
"🎤 <transcript>", and then handled exactly like a typed message —
continuity, model prefixes, builtins, everything.

Until this setup is done, voice notes get a polite "transcription isn't
set up" reply. Nothing else breaks.

## Setup (on the Mac mini)

```bash
brew install ffmpeg whisper-cpp

# Model (~148 MB, English). base.en is the speed/accuracy sweet spot for
# voice memos; use small.en if transcripts come out sloppy.
mkdir -p ~/Nao/models
curl -L -o ~/Nao/models/ggml-base.en.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin

# Verify the binary name (homebrew ships whisper-cli; older builds used
# whisper-cpp — the bridge looks for both):
which whisper-cli || which whisper-cpp

# Restart the bridge so it sees the tools:
launchctl unload ~/Library/LaunchAgents/com.nao.telegram-bridge.plist
launchctl load   ~/Library/LaunchAgents/com.nao.telegram-bridge.plist
```

Then send the bot a short voice note. Expect the 🎤 echo within a few
seconds (base.en transcribes ~10x realtime on Apple silicon).

## Config knobs (.env)

| Var | Default | Meaning |
|---|---|---|
| `NAO_WHISPER_MODEL` | `~/Nao/models/ggml-base.en.bin` | Path to the ggml model |
| `NAO_VOICE_MAX_SECONDS` | `300` | Refuse longer notes (CPU guard) |
| `NAO_TRANSCRIBE_CMD` | unset | Full override: shell command with `{file}` placeholder that prints the transcript to stdout. Replaces the ffmpeg+whisper pipeline entirely. |

## Notes

- Transcripts are echoed back before Nao acts, so a mishearing is visible
  immediately — `reset` clears the thread if it went into the transcript
  wrong.
- The audio file is deleted after transcription either way.
- `models/` is gitignored; the model file stays on the mini.
