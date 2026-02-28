# dg-dictate

A Linux system tray dictation tool powered by [Deepgram](https://deepgram.com/). Press **F4** to start/stop recording — spoken words are transcribed in real time and typed into whatever app has focus.

## How it works

- Sits in the system tray with a **red dot** (idle) or **green dot** (recording)
- Press **F4** to toggle recording on/off
- You can also click the tray icon or use its right-click menu
- Transcribed text is typed at the cursor via `xdotool`
- Uses Deepgram's Nova-2 model for live, streaming transcription

## Requirements

- Linux with X11
- Python 3.10+
- `xdotool` installed (`sudo apt install xdotool`)
- A [Deepgram API key](https://console.deepgram.com/)
- A system tray (e.g. GNOME with AppIndicator extension, XFCE panel, etc.)

## Setup

```bash
# Clone the repo
git clone https://github.com/TrevorSpane/dg-dictate.git
cd dg-dictate

# Create a virtual environment and install dependencies
python3 -m venv venv
source venv/bin/activate
pip install deepgram-sdk pyaudio pynput pystray Pillow

# Copy the run script template and add your API key
cp run.sh.example run.sh
chmod +x run.sh
# Edit run.sh and replace 'your_api_key_here' with your Deepgram API key
```

## Running

```bash
./run.sh
```

To run it automatically at login, add `run.sh` to your desktop environment's autostart settings.

## Notes

- On X11, the system tray manager may take a few seconds to be ready after login. The app retries automatically — the icon will appear once the tray is available, no interaction needed.
- `pynput` requires access to X input. If you run into permission errors, make sure your user is in the `input` group or run under your normal desktop session.
