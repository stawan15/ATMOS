# Contributing to ATMOS

ATMOS — by Estellez

Thanks for your interest. This guide is the long form. The
README has the short version; it links here for detail.

## Welcome

ATMOS is a calm ambient terminal weather application. It is
intentionally small: a frame buffer, a particle engine, a
handful of weather scenes, a thin Open-Meteo client, and a
keyboard-driven input loop. Most contributions are small and
focused — a new particle pattern, a real terminal capture,
a documented keystroke, a Windows fix. Before opening a PR for
anything beyond a typo or a one-line fix, **open an Issue** so
the approach can be discussed first.

## Development setup

Tested on Windows 10+, Linux, and macOS. Python 3.12 or newer
is required.

Cross-platform block:


```bash
# Clone
git clone https://github.com/L4ncelotz/ATMOS
cd ATMOS

# Virtualenv (cross-platform)
python -m venv .venv
source .venv/bin/activate

# Install with dev + build extras
pip install -e ".[dev,build]"

# Smoke test
atmos
# or
python -m atmos
```

Windows (PowerShell or cmd) only — replace the `source` line
above with the line below in its own fence:

```powershell
.venv\Scripts\activate
```
You should see a weather scene within a couple of seconds. If
nothing renders, your terminal probably does not support the
alt-screen escape; see [README § Known Limitations](./README.md#known-limitations).

## Project architecture

```
ATMOS/
├── src/
│   └── atmos/
│       ├── app.py            # entry point, mode dispatch, animation loop
│       ├── cli.py            # argparse wrapper
│       ├── config.py         # TOML config + last_location persistence
│       ├── engine/           # terminal, frame buffer, layout, lighting, etc.
│       ├── scenes/           # clear, cloudy, rain, snow, fog, wind, storm, ...
│       ├── ui/               # overlay, help, forecast, location_search
│       ├── utils/            # logging, local time helpers
│       └── weather/          # Open-Meteo, geocoding, cache, refresher
├── tests/                    # pytest regression suite
├── build.py                  # PyInstaller wrapper
├── pyproject.toml            # packaging + optional-dependency metadata
└── .github/
    ├── workflows/            # ci.yml, release.yml, labels.yml
    └── ISSUE_TEMPLATE/       # bug_report.md, feature_request.md
```

The architectural rule, repeated because it matters:

> External weather-provider responses must never be consumed
> directly by the rendering system. Provider payloads always
> flow through `atmos/weather/mapper.py` into a canonical
> `WeatherState` model before any scene code sees them.

Adding a new weather source means a new `WeatherProvider`
subclass plus an extension to `mapper.py`. It does **not**
mean touching the scene code.

## Workflow

ATMOS follows a `develop`-based workflow. The `main` branch is reserved for stable releases; normal feature and bugfix work targets `develop`.

1. Fork ATMOS
2. Sync your fork
3. Create a feature/fix branch from `develop`
4. Make a focused change
5. Run tests
6. Push the branch
7. Open a Pull Request targeting `develop`
8. Maintainers review and merge

Urgent hotfixes for the current stable release branch off `main`, merge to `main` via PR, and are then synced back into `develop`.

## Branch naming

Branch off `develop`. `main` is reserved for stable releases. One branch per Issue. Use the matching
Conventional Commit prefix so the branch name reads as the
title of the work:

| Prefix      | Use for                                                |
|-------------|--------------------------------------------------------|
| `feat/`     | new user-visible behavior, new scene, new feature     |
| `fix/`      | bug fix, regression fix                                |
| `perf/`     | performance improvement (terminal I/O, particle count) |
| `docs/`     | documentation only (README, CONTRIBUTING, this file)   |
| `test/`     | tests only                                             |
| `refactor/` | internal restructure with no user-visible change      |
| `build/`    | packaging, build script, PyInstaller, CI matrix       |
| `ci/`       | CI workflow changes                                    |

Examples from this repo's plan:

- `docs/demo-preview` — record and embed a real `demo.gif`.
- `feat/mac-build` — add `macos-latest` to the release matrix.
- `fix/readme-rendering` — fix README rendering bugs.

Branch names stay lowercase, hyphenated, and short. Topic
branches are deleted after merge; do not keep them around.

## Commit convention

Conventional Commits, lightly enforced. Use one of the eight
prefixes above, followed by a short imperative-mood subject:

```
feat: add fog density cap at 8 layers
fix: preserve location during offline startup
perf: reduce framebuffer terminal writes 4x
docs: add real ATMOS terminal preview
test: cover weather cache fallback
refactor: isolate scene selection logic
build: add macOS release target
ci: test against Python 3.12 and 3.13
```

Rules:

- One logical change per commit.
- Imperative mood ("add", not "added" or "adds").
- Subject line under 72 characters.
- No period at the end of the subject.
- Body explains **why**, not what; the diff shows what.

Anti-patterns (a maintainer will ask for a rebase if any of
these appear in a PR):

- `update`, `fix2`, `done`, `final`, `final-final`, `testtt`, `aaa`
- "WIP" commits left in the branch history
- One mega-commit that does 30 unrelated things

If a PR is "docs: improve README", it should usually be 2-5
focused commits, not one giant commit.

## Running tests

```bash
# All tests
pytest

# A single test
pytest tests/test_atmos.py::test_letter_keys_parsed_as_char

# Verbose
pytest -v
```

The test suite pins the user-reported bugs from the V1 roadmap:
night-phase progression, location-typing, config load, no-mock
fallback, async geocode, frame-buffer coalescing, heavy-rain
cap, and the entry-point import surface. Add a test in
`tests/test_atmos.py` for any new bug fix.

The CI workflow (`.github/workflows/ci.yml`) runs the same
`pytest` on `ubuntu-latest` and `windows-latest` for every
push to `main` or `develop` and every PR.

The standalone binary build is also tested in CI via
`python build.py && ./dist/atmos.exe --version`. Run it
locally before opening a PR that touches `build.py`,
`pyproject.toml`, or any module imported by it.

## Adding a Scene

`src/atmos/scenes/clear.py` is the minimal reference. To add
a new scene:

1. Create `src/atmos/scenes/<name>.py` with a class that
   subclasses `SceneBase`. Implement `enter`, `update`, `draw`
   (and `exit` if you have resources to release). The `draw`
   method receives `buf: FrameBuffer`, `lighting`, and the
   optional `dim: float = 1.0` keyword for transition blending.
2. Register the class in `SCENE_MAP` in `src/atmos/app.py`:
   ```python
   from atmos.scenes.myscenefile import MyScene
   SCENE_MAP["mycondition"] = MyScene
   ```
3. If the scene needs a new normalized condition string, add
   the WMO-code mapping in `atmos/weather/mapper.py`
   (`_WMO_TABLE`) and the corresponding `select_scene_name`
   branch in `src/atmos/app.py`.
4. Write a test in `tests/test_atmos.py` that constructs the
   scene, calls `update` with a sample `WeatherState` for a
   few frames, and asserts the expected particle count or
   visual output.
5. Document the new scene in `README.md` under "Features →
   Scenes".

Keep the scene class small and self-contained. Particle
spawning and physics live in the scene; the engine has no
opinion about what a scene looks like.

## Adding a WeatherProvider

The renderer never sees the provider's raw response. To add a
new source:

1. Subclass the `WeatherProvider` Protocol in
   `atmos/weather/client.py`:
   ```python
   class MyProvider:
       def current(self, location: Location) -> WeatherState: ...
       def forecast(self, location: Location, days: int = 5) -> list[ForecastDay]: ...
   ```
2. Add a `to_weather_state` (or equivalent) function in
   `atmos/weather/mapper.py` that turns the provider's payload
   into a `WeatherState`. The renderer's rule is non-negotiable:
   the scene code must only see `WeatherState`.
3. Wire the provider into `WeatherRefresher` in
   `atmos/weather/refresher.py`. The refresher is the only
   component allowed to call provider methods.
4. Mock-test it in `tests/test_atmos.py`:
   ```python
   class FakeProvider:
       def current(self, loc): raise WeatherError("offline")
       ...
   state, forecast, location, reason = app._resolve_initial(
       Config(), location_override="X", provider=FakeProvider()
   )
   assert state is None  # the no-mock guarantee
   ```
5. Document the provider and any rate limits or required API
   keys in `README.md` under "Tech Stack" and "Configuration".

Do not add a new pip dependency for a provider without
justifying it in the PR. A new HTTP client or SDK is a long-term
maintenance cost.

## Submitting a PR

Checklist before opening a PR:

- [ ] `pytest` passes locally.
- [ ] `python build.py && ./dist/atmos.exe --version` works
      (when `build.py` or anything it bundles is touched).
- [ ] No new dependency without justification in the PR body.
- [ ] New behavior has a test in `tests/test_atmos.py`.
- [ ] `README.md` updated if user-visible behavior changed.
- [ ] `CHANGELOG.md` updated under `[Unreleased]` if the
      change is user-visible.
- [ ] No secrets, no local paths, no generated build
      artifacts (`dist/`, `build/`, `__pycache__/`) in the
      diff.
- [ ] Branch is up to date with `develop` (rebase, do not merge).

Open the PR against `develop`. The CI workflow will run; the
release workflow only runs on tag push from `main`. A maintainer review
follows; the branch is squash-merged and deleted.

## Code of conduct

Be kind. Critique ideas, not people. The project is small and
the maintainer reads every PR; thoughtful discussion is
welcome, hostility is not.
