# Frame TV Art Rotator

Automatically rotates artwork on your Samsung Frame TV on a schedule. Pulls images from local folders, NASA's Astronomy Picture of the Day, the Metropolitan Museum of Art, and the Art Institute of Chicago.

The idea is for this to run on a home server or something on a cron job.

Yes, this thing was very much vibe coded.

---

## Requirements

- Python 3.10 or newer
- Your Frame TV must be on the same local network as the machine running this script
- The TV's IP address (ideally a static/reserved one in your router settings)

To check your Python version:
```bash
python3 --version
```

If it says 3.10 or higher, you're good. If not, install Python from [python.org](https://www.python.org/downloads/).

---

## Setup

### 1. Clone or copy the project onto your NAS

```bash
cd /path/to/where/you/want/it
# If you have git:
git clone <repo-url> frame-tv-art
cd frame-tv-art

# Or just copy the folder there manually and cd into it
cd frame-tv-art
```

### 2. Create a virtual environment

A virtual environment is an isolated box for this project's dependencies — it keeps them from interfering with anything else on your system.

```bash
python3 -m venv venv
```

This creates a `venv/` folder inside the project. You only do this once.

### 3. Activate the virtual environment

```bash
source venv/bin/activate
```

Your terminal prompt will change to show `(venv)` at the start. **You need to do this every time you open a new terminal session to work with the project.** (The cron job handles this automatically — see step 7.)

### 4. Install dependencies

```bash
pip install -r requirements.txt
```

This downloads and installs all the libraries the script needs. It may take a minute or two.

> **Note:** If `pip` is not found, try `pip3` instead.

### 5. Create your config file

Copy the example config and open it in a text editor:

```bash
cp config.example.json config.json
```

The minimum you need to change:

```json
"tv": {
  "host": "192.168.1.42"   ← change this to your TV's IP address
}
```

And set at least one source under `"sources"`. For a local folder:

```json
"my_photos": {
  "type": "local",
  "paths": ["/mnt/media/MyArt"],
  "recursive": true,
  "extensions": ["jpg", "jpeg", "png"],
  "expires": false
}
```

And reference it in your default schedule:

```json
{
  "name": "default",
  "source": "my_photos",
  "mode": "random",
  "interval_minutes": 60
}
```

See `config.example.json` for the full list of options and examples of every schedule type.

---

## First Run (TV Pairing)

The first time you connect, your TV will display a pairing prompt on screen. Run the script once manually to trigger it:

```bash
python3 run.py
```

**On your TV:** A notification will appear asking you to allow the connection. Accept it.

The script saves an authentication token to `data/tv_token.txt` automatically. All future runs use that token — you won't need to pair again unless you delete the file or reset the TV.

---

## Running manually

Make sure the virtual environment is active (`source venv/bin/activate`), then:

```bash
python3 run.py
```

To use a different config file:

```bash
python3 run.py --config /path/to/other-config.json
```

Logs print to the terminal so you can see what it's doing.

---

## Setting up the cron job (automatic scheduling)

Cron is a Linux built-in scheduler. This runs the script every 30 minutes automatically, even after reboots.

### 1. Find the full path to your Python

```bash
which python3
```

It will print something like `/usr/bin/python3`. If you're using the virtual environment (recommended), it's:

```bash
which venv/bin/python3
```

Write down whatever it prints — you'll need it in the next step.

### 2. Open the cron editor

```bash
crontab -e
```

This opens a text editor. If it asks which editor to use, pick `nano` (easiest for beginners).

### 3. Add the cron line

Add this line at the bottom (adjust the paths to match where you put the project):

```
*/30 * * * * cd /path/to/frame-tv-art && /path/to/frame-tv-art/venv/bin/python3 run.py >> /var/log/frametv.log 2>&1
```

**Example** if your project is at `/home/user/frame-tv-art`:
```
*/30 * * * * cd /home/user/frame-tv-art && /home/user/frame-tv-art/venv/bin/python3 run.py >> /var/log/frametv.log 2>&1
```

`*/30 * * * *` means "every 30 minutes". Change `30` to `15` for every 15 minutes, etc. Note that this sets the *check* frequency — the script only actually changes the art when the rule's `interval_minutes` has elapsed.

### 4. Save and exit

In nano: press `Ctrl+O` to save, then `Ctrl+X` to exit. Cron will pick up the change immediately.

### 5. Check the logs

After 30 minutes, check that it ran:

```bash
tail -50 /var/log/frametv.log
```

---

## Troubleshooting

**"TV unavailable, skipping"** — The script couldn't reach the TV. Check:
- TV is on and not in a screensaver/sleep mode that disables network
- IP address in config.json is correct
- TV and NAS are on the same network/VLAN

**"No module named X"** — The virtual environment isn't active, or dependencies weren't installed into it. Run:
```bash
source venv/bin/activate
pip install aiohttp pillow
```

**Art isn't changing** — Check the log. Common causes:
- `interval_minutes` hasn't elapsed yet since the last change
- The source folder is empty or the path is wrong
- TV was off when the cron job ran (it will try again next run)

**Delete `data/state.json`** to reset all history and force a fresh start on the next run.

---

## NASA API Key (optional)

The default `"DEMO_KEY"` works at low volume (30 requests/hour). If you use NASA APOD heavily, get a free personal key at [api.nasa.gov](https://api.nasa.gov/) — no credit card needed, just an email address.

Set it in `config.json`:
```json
"nasa_api_key": "your-key-here"
```
