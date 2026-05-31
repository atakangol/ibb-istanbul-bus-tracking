# Raspberry Pi logger

Separate from `examples/log_lines.py`: uses its own SQLite file and runs until you stop it.

| | Desktop (`examples/log_lines.py`) | Pi (`pi/log_observations.py`) |
|--|-----------------------------------|-------------------------------|
| Database | `cache/iett.sqlite` | `pi/data/iett_pi.sqlite` |
| Stop condition | `--until` / `--duration` optional | Ctrl+C or SIGTERM only |
| Lines file | `observation_lines.txt` (project root) | `pi/observation_lines.txt` |

## Setup (Pi Zero W)

On the Pi, from a copy of this repo:

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip git
cd ~/IBB_bus
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Optional: copy `.env` if you use İETT credentials.

Edit lines to watch:

```bash
nano pi/observation_lines.txt
```

## Run manually

```bash
cd ~/IBB_bus
source .venv/bin/activate
python pi/log_observations.py
```

Runs forever (one poll per line per minute) until Ctrl+C. Logs go to stdout; data goes to `pi/data/iett_pi.sqlite`.

## Run on boot (systemd)

Adjust paths in `pi/iett-pi-logger.service` if your user or repo path differs, then:

```bash
sudo cp pi/iett-pi-logger.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now iett-pi-logger
sudo systemctl status iett-pi-logger
```

Logs: `journalctl -u iett-pi-logger -f`

## Copy DB to your PC

```bash
# From your PC
scp pi@raspberrypi.local:~/IBB_bus/pi/data/iett_pi.sqlite ./pi/data/
```

## Merge into main database (on your PC)

```bash
python pi/merge_to_main.py
python examples/analyze_delays.py --line 15B
```

`merge_to_main.py` appends `vehicle_polls` and uses `INSERT OR IGNORE` for `stop_passage_events` (skips duplicates). Run `--dry-run` first to see counts.

## Pi Zero notes

- Keep `--interval 60` (default); shorter intervals stress the slow CPU and Wi‑Fi.
- First start downloads line stop lists into the Pi DB (same schema as the main cache).
- If Wi‑Fi drops, the logger logs a warning and retries next round; systemd `Restart=on-failure` covers crashes.
