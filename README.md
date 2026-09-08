# ATMOS

**by Estellez**

> Ambient weather for your terminal.

Real weather drives the animation: precipitation controls rain
density, wind affects particle velocity, cloud coverage shapes the
sky, and local time controls the day/night cycle.

ATMOS is not another weather CLI. It is a calm ambient experience
that lives in your terminal.

---

## Preview

<img src="assets/demo.gif" alt="ATMOS — four scenes (rain, clear night, storm, snow)" width="800">


```text
BANGKOK                                       21:42

             │            │
      │                     │
                 │
          │            │

                    29°
                    rain

humidity 78%                        wind 14 km/h
```

---

## What is ATMOS?

ATMOS fetches a live forecast, normalizes it into an internal
`WeatherState`, and feeds the relevant values into a particle
simulator and a small scene engine. The scene engine renders into a
2D character grid; the grid is diffed against the previous frame and
emitted as ANSI cursor moves so the terminal itself looks like it
has weather.

The terminal stays calm even when the weather outside isn't.

---

## Features

### Weather

- Current temperature
- Feels-like temperature
- Humidity
- Precipitation (mm in the last hour)
- Wind speed and direction
- Cloud coverage
- Sunrise / sunset
- 5-day forecast

### Scenes

- Clear
- Partly Cloudy
- Cloudy
- Rain
- Heavy Rain
- Thunderstorm (with randomized lightning)
- Snow
- Fog
- Wind

### Simulation

Real values drive the scene:

| Weather value    | Drives                                       |
|------------------|----------------------------------------------|
| Precipitation     | rain density and fall speed                  |
| Wind speed       | particle horizontal velocity                 |
| Wind direction   | particle drift direction                     |
| Cloud coverage   | cloud band count and width                   |
| Visibility       | fog layer density                            |
| Local time       | day/night phase, sun arc, stars, moon        |

### Interaction

| Key     | Action                                |
|---------|---------------------------------------|
| `F`     | forecast (next 5 days)                |
| `L`     | search / change location              |
| `M`     | toggle minimal mode                   |
| `Space` | pause / resume animation              |
| `R`     | refresh weather                       |
| `H`     | help overlay                          |
| `Q`     | quit (Ctrl+C also works)              |
| `+` / `-` | target FPS up / down                 |

The first launch hits the network for live weather. If the network
fails, ATMOS falls back to the last cached snapshot and shows a
small `·offline` tag at the top. If no cache exists and the network
is still down, ATMOS shows "unable to load weather / press R to
retry" and never invents data.

---

## Tech Stack

| Technology    | Purpose                                            |
|---------------|----------------------------------------------------|
| Python 3.12+  | Core application                                   |
| Rich          | Terminal styling and text rendering                |
| Blessed       | Terminal capabilities and keyboard input           |
| HTTPX         | Weather and geocoding HTTP requests                |
| Pydantic      | Internal weather models and validation             |
| Open-Meteo    | Weather and geocoding provider (no API key)         |
| platformdirs  | Cross-platform config, cache, and log paths        |
| PyInstaller   | Standalone executables                              |
| GitHub Actions| Build, test, and release automation               |

---

## Architecture

External weather-provider responses are never consumed directly by
the rendering system. Provider payloads always flow through
`atmos/weather/mapper.py` into a canonical `WeatherState` model
before any scene code sees them. This keeps the renderer independent
of Open-Meteo and lets new providers slot in without touching the
scene code.

```text
                    ┌───────────────┐
                    │  Open-Meteo   │
                    └───────┬───────┘
                            │
                            ▼
                    WeatherProvider
                            │
                            ▼
                      WeatherState
                            │
             ┌──────────────┼──────────────┐
             ▼              ▼              ▼
        Scene Mapper      Forecast        Cache
             │
             ▼
         Scene Engine
             │
      ┌──────┼────────┐
      ▼      ▼        ▼
 Particle  Layout  Transition
  Engine   Engine    Engine
      │      │        │
      └──────┴────┬───┘
                  ▼
             Frame Buffer
                  │
                  ▼
               Terminal
```

The rule:

> External weather-provider responses must never be consumed
> directly by the rendering system. Provider data must first be
> normalized into internal models such as `WeatherState`.


## Installation

### From source

Cross-platform — same instructions on every OS. The
Windows-only line is shown in its own block so Markdown
renderers do not split the backslash.

```bash
git clone https://github.com/L4ncelotz/ATMOS
cd ATMOS
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
atmos
```

Windows (PowerShell or cmd):

```powershell
.venv\Scripts\activate
```

### Standalone binary

The GitHub Actions release workflow builds a onefile binary per
tag. Download the artifact for your platform from the
[Releases page](https://github.com/L4ncelotz/ATMOS/releases), drop it
somewhere on your `PATH`, and run it. No Python install required.

| Platform    | File                              |
|-------------|-----------------------------------|
| Windows     | `atmos-windows-x86_64.exe`        |
| Linux x86_64| `atmos-linux-x86_64`              |

macOS is not part of the CI matrix; build it locally with
`python build.py` on a Mac.

### Local binary build

```bash
pip install -e ".[build]"
python build.py
# -> dist/atmos.exe (Windows) or dist/atmos (POSIX, +x)
```

---

## Usage

```bash
atmos                       # last used or configured location
atmos Bangkok               # one-off location query
atmos Tokyo --minimal       # start in minimal mode
atmos --fps 20              # target animation frame rate
atmos --demo rain           # local visual demo (no network)
atmos --version             # print version and exit
atmos --help                # full flag list
```

`--forecast` was removed; forecast is accessible in-app via `F`.

For scene development or screenshots, `--demo` accepts `clear`,
`partly_cloudy`, `cloudy`, `rain`, `heavy_rain`, `storm`, `snow`, `fog`,
or `wind`. Demo mode uses deterministic local weather and does not contact
Open-Meteo.

---

## Configuration

Configuration, weather cache, and logs use `platformdirs` for
cross-platform paths:

| Platform | Config                                       | Cache                                       | Logs                                              |
|----------|----------------------------------------------|---------------------------------------------|---------------------------------------------------|
| Windows  | `%LOCALAPPDATA%\atmos\config.toml`          | `%LOCALAPPDATA%\atmos\weather_cache.json`   | `%LOCALAPPDATA%\atmos\Logs\atmos.log`             |
| Linux    | `~/.config/atmos/config.toml`                | `~/.cache/atmos/weather_cache.json`         | `~/.local/state/atmos/atmos.log`                  |
| macOS    | `~/Library/Application Support/atmos/...`   | `~/Library/Caches/atmos/weather_cache.json` | `~/Library/Logs/atmos/atmos.log`                  |

Example `config.toml`:

```toml
location = "Bangkok"
fps = 30
minimal = false
sound = false
units = "metric"
refresh_minutes = 15

[last_location]
name = "Bangkok"
country = "Thailand"
latitude = 13.75398
longitude = 100.50144
timezone = "Asia/Bangkok"
```

`[last_location]` is written automatically when a city is selected
or weather is fetched, so the next launch can recover from cache
without contacting the geocoder.

Set `ATMOS_DEBUG=1` to mirror INFO+ output to stderr.

---

## Offline Behavior

```text
request weather
       ↓
   success ─────────────→ update cache
       │
       fail
       ↓
   cached weather available?
       │
   yes │              no
       ↓               ↓
  show cached      show retry state
  weather          (R to retry, Q to quit)
```

ATMOS never invents weather. If both the network and the cache are
unavailable, the screen shows the retry prompt until a fetch
succeeds.

---

## Performance

Targets — these are design goals, not benchmarked ceilings:

- 30 FPS
- Low terminal flicker
- < 100 MB typical memory
- Fast startup (< 2 s excluding network)
- Minimal CPU on ordinary laptops

The frame buffer is diffed against the previous frame and written
with one cursor-position escape per (row, style-change), not per
cell. Heavy rain is capped at 300 particles to keep terminal I/O
within practical bounds.

---

## Project Philosophy

ATMOS should:

- Remain minimal
- Prioritize atmosphere over information density
- Use terminal-native visuals (box-drawing characters, not emoji)
- Keep animation subtle
- Be keyboard-first
- Avoid dashboard-style interfaces

ATMOS should not become:

- A dashboard full of cards
- A weather website inside a terminal
- A fake Matrix / hacker UI
- An analytics application
- An AI weather assistant

---

## Roadmap

```text
[x] Terminal rendering engine
[x] Particle system
[x] Core weather scenes (9)
[x] Weather provider abstraction
[x] Open-Meteo integration
[x] Forecast mode
[x] Config and cache system
[x] Continuous local time
[x] Async geocoding
[x] Scene transition blending
[x] Core test suite
[ ] macOS binary in CI
[ ] Optional sound (disabled by default)
```

---

## Known Limitations

- Terminal compatibility varies; the alt-screen + cursor-hide
  sequences work in Windows Terminal, iTerm2, gnome-terminal,
  Alacritty, and most modern hosts. cmd.exe is not supported.
- The first-launch experience requires network. Subsequent
  launches with no network fall back to the last cache.
- Sound is not implemented.
- macOS binaries are not produced by CI; build locally.
- UTF-8 must be available in the host's code page. The app
  reconfigures stdout/stderr to UTF-8 on launch.

---

## Development

Install dev dependencies:

```bash
pip install -e ".[dev]"
```

Run from source:

```bash
atmos
# or
python -m atmos
```

Run tests:

```bash
pytest
```

Build a binary:

```bash
pip install -e ".[build]"
python build.py
```

---

## Building Executables

```bash
python build.py
```

Output: `dist/atmos.exe` on Windows, `dist/atmos` (with the
executable bit set) on Linux. The script is a thin wrapper around
`PyInstaller.__main__.run` with the right flags for a TUI app:
`--onefile`, `--console`, `--collect-all=blessed`. The resulting
binary prints `atmos <version>` and runs without a Python
interpreter.

---

## Contributing

ATMOS uses a `develop`-based branching workflow:

```text
main     → stable / release
develop  → next-release integration
feat/*   → individual changes
```

Normal development PRs target `develop`. See [`CONTRIBUTING.md`](./CONTRIBUTING.md) for full instructions and branch guidelines.
---

## License

MIT. See [`LICENSE`](./LICENSE).

---

## Credits

- [Open-Meteo](https://open-meteo.com/) for free weather and
  geocoding APIs with no key requirement.
- [Rich](https://github.com/Textualize/rich) and
  [Blessed](https://github.com/jquast/blessed) for terminal
  capabilities.
- [Pydantic](https://docs.pydantic.dev/) for runtime model
  validation.
- [HTTPX](https://www.python-httpx.org/) for HTTP.
- [PyInstaller](https://pyinstaller.org/) for the standalone
  binary.

---

ATMOS — by Estellez
