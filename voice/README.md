# FRIDAY voice client

FRIDAY is an optional Windows voice client for the FINESSE API. It can wait for a
configured wake phrase, transcribe speech locally with `faster-whisper`, submit
the transcript to FINESSE, and speak the response.

## How it works

```text
clap/wake detection -> local speech transcription -> authenticated FINESSE API
                    -> browser/server agent response -> text-to-speech
```

- The FINESSE server must be running first.
- Speech recognition uses a local Whisper model after it is downloaded.
- TTS can use an online Edge voice or the optional offline `pyttsx3` fallback.
- All options are in a local `friday.json`, copied from `config.example.json`.
- The local config must contain credentials for a FINESSE account. No credentials
  are included in the repository.

## Setup (PowerShell)

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r voice\requirements-voice.txt
Copy-Item voice\config.example.json voice\friday.json
```

Edit `voice\friday.json` locally: set `account_email` and `account_password`
for a dedicated, least-privilege FINESSE account. Keep this file private; it is
excluded from Git. Alternatively set `FINESSE_EMAIL` and `FINESSE_PASSWORD` in
the process environment. Leave `auto_start_backend` off unless you deliberately
configure the backend paths for your own machine.

Run the client:

```powershell
python voice\friday.py
```

The first run downloads the configured Whisper model. Audio devices and wake
thresholds should be tested on the target Windows machine.

## Optional executable

`build_exe.ps1` packages the client for Windows. Review the script and its
startup behavior before use. Do not distribute an executable bundled with a
personal `friday.json`; keep account credentials local.
