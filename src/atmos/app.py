"""ATMOS app entry point.

V5 ambient experience:
  - Day/night lighting state derived from WeatherState.
  - Scene changes use SceneTransition (fade over ~2.5s).
  - Stars, moon, sun arc (in Clear / PartlyCloudy scenes).
  - Shooting stars (02-04 local time, clear skies).

Production keys (V4/V5):
  F   forecast mode
  L   location search
  M   minimal mode toggle
  Space pause
  R   refresh weather
  H   help
  Q   quit
  + - FPS up / down

The renderer never imports from atmos.weather.* — only WeatherState and
ForecastDay flow through app.main().
"""

from __future__ import annotations

import enum
import sys
import time

from atmos import __version__
from atmos.config import Config, update_resolved_location
from atmos.engine.animation import AnimationLoop
from atmos.engine.companion import WeatherCompanion
from atmos.engine.frame_buffer import FrameBuffer
from atmos.engine.input import (
    InputManager,
    KeyEvent,
    action_for_char,
    is_action_char,
)
from atmos.engine.layout import LayoutManager
from atmos.engine.lighting import LightingState, compute_lighting
from atmos.engine.terminal import TerminalContext
from atmos.engine.transition import SceneTransition, blend_intensity
from atmos.scenes.clear import ClearScene
from atmos.scenes.cloudy import CloudyScene
from atmos.scenes.fog import FogScene
from atmos.scenes.heavy_rain import HeavyRainScene
from atmos.scenes.partly_cloudy import PartlyCloudyScene
from atmos.scenes.rain import RainScene
from atmos.scenes.snow import SnowScene
from atmos.scenes.storm import StormScene
from atmos.scenes.wind import WindScene
from atmos.ui.forecast import draw_forecast
from atmos.ui.help import draw_help
from atmos.ui.location_search import (
    LocationSearchState,
    draw_location_search,
    max_results,
)
from atmos.ui.mock_weather import MOCK
from atmos.ui.overlay import draw_header, draw_info, draw_status
from atmos.utils.time import local_now
from atmos.weather.cache import read_forecast_for, read_for_location
from atmos.weather.client import WeatherError
from atmos.weather.geocode import first_location, resolve_location
from atmos.weather.geocode_async import GeocodeWorker
from atmos.weather.location import Location
from atmos.weather.models import WeatherState
from atmos.weather.open_meteo import OpenMeteoProvider
from atmos.weather.refresher import RefreshResult, WeatherRefresher


class Mode(enum.Enum):
    AMBIENT = "ambient"
    FORECAST = "forecast"
    HELP = "help"
    LOCATION = "location"


SCENE_MAP = {
    "clear": ClearScene,
    "cloudy": CloudyScene,
    "partly_cloudy": PartlyCloudyScene,
    "rain": RainScene,
    "heavy_rain": HeavyRainScene,
    "storm": StormScene,
    "snow": SnowScene,
    "fog": FogScene,
    "wind": WindScene,
}


def select_scene_name(weather: WeatherState) -> str:
    cond = weather.condition
    if cond == "rain" and weather.precipitation >= 5.0:
        return "storm"
    return cond


def _resolve_initial(
    cfg: Config,
    *,
    location_override: str | None,
    provider: OpenMeteoProvider,
) -> tuple[WeatherState | None, list[ForecastDay], Location | None, str | None]:
    """Resolve the initial weather state.

    Order of attempts:
      1. Live fetch — geocode the label, hit the weather API, hit the
         forecast endpoint.
      2. Cache the live-resolved location.
      3. Cache the saved `cfg.last_location` (lets a previously selected
         city render with cached data even when the geocoder is down).
      4. Return `state is None` — caller renders the no-data message.

    Never invents a fake WeatherState. If no real data is available,
    returns state=None.
    """
    label_query = location_override or cfg.location
    offline_reason: str | None = None
    location_obj: Location | None = None
    state: WeatherState | None = None
    forecast: list[ForecastDay] = []

    def _try_cache(loc: Location) -> tuple[WeatherState | None, list[ForecastDay], str]:
        cached_state = read_for_location(loc)
        if cached_state is None:
            return None, [], f"no cache for {loc.label}"
        return cached_state, read_forecast_for(loc), "no network"

    # 1. Live: geocode → current → forecast.
    try:
        location_obj = first_location(label_query)
    except (ValueError, Exception) as exc:  # noqa: BLE001
        location_obj = None
        offline_reason = f"location error: {exc}"
    else:
        try:
            state = provider.current(location_obj)
            try:
                forecast = provider.forecast(location_obj, days=5)
            except WeatherError as exc:
                offline_reason = f"forecast error: {exc}"
                forecast = read_forecast_for(location_obj)
        except WeatherError as exc:
            offline_reason = str(exc)
            # 2. Cache the just-resolved location.
            cached_state, cached_forecast, reason = _try_cache(location_obj)
            if cached_state is not None:
                state = cached_state
                forecast = cached_forecast
                offline_reason = offline_reason or reason

    # 3. Fall back to cfg.last_location if live and the geocoded cache
    #    both failed.
    if state is None and (location_obj is None or location_obj.name != cfg.location):
        if cfg.last_location is not None and (
            location_override is None  # only auto-fallback when no explicit override
        ):
            cached_state, cached_forecast, reason = _try_cache(
                Location(
                    name=cfg.last_location.name,
                    country=cfg.last_location.country,
                    latitude=cfg.last_location.latitude,
                    longitude=cfg.last_location.longitude,
                    timezone=cfg.last_location.timezone,
                )
            )
            if cached_state is not None:
                state = cached_state
                forecast = cached_forecast
                location_obj = Location(
                    name=cfg.last_location.name,
                    country=cfg.last_location.country,
                    latitude=cfg.last_location.latitude,
                    longitude=cfg.last_location.longitude,
                    timezone=cfg.last_location.timezone,
                )
                offline_reason = offline_reason or reason

    # 4. No state → no fake fallback. Caller handles the empty path.
    return state, forecast, location_obj, offline_reason


def _fps_hud(buf: FrameBuffer, lay, fps: float, scene_name: str, offline: bool) -> None:
    txt = f"{fps:>4.0f}fps  [{scene_name}]"
    if offline:
        txt += "  ·offline"
    buf.write_line(0, max(0, lay.width - len(txt) - 10), txt, "240")


def _draw_minimal_status(buf: FrameBuffer, lay, state: WeatherState) -> None:
    buf.write_centered(lay.status_y, state.location_name, "240")


def _handle_global(
    key: KeyEvent | None,
    *,
    loop: AnimationLoop,
    refresher: WeatherRefresher,
    allow_network: bool = True,
) -> bool:
    if key is None:
        return False
    action = key.action
    if action == "char" and key.char is not None:
        action = action_for_char(key.char.lower())

    if action == "quit":
        loop.stop()
        return True
    if action == "plus":
        loop.target_fps = min(60, loop.target_fps + 5)
    elif action == "minus":
        loop.target_fps = max(5, loop.target_fps - 5)
    elif action == "refresh" and allow_network:
        refresher.request_refresh()
    return False


def _activate_location_search(search: LocationSearchState, *, demo: bool) -> bool:
    """Open location search unless the local, network-free demo is active."""
    if demo:
        return False
    search.active = True
    search.last_input_at = time.monotonic()
    search.results = []
    return True


def main(argv: list[str] | None = None) -> int:
    # Force UTF-8 on the terminal's stdout/stderr. Some Windows consoles
    # default to a code page that cannot encode box-drawing characters
    # (e.g. cp874 when LANG is set to Thai). This must run before any
    # frame buffer write, otherwise the first non-ASCII character kills
    # the app. PyInstaller binaries inherit the host's code page.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    from atmos.cli import parse as parse_cli
    from atmos.utils.logging_setup import setup_log
    args = parse_cli(argv)
    cfg: Config = args.config
    log = setup_log("atmos")
    log.info("starting atmos version=%s location=%s fps=%s", __version__, args.location_override or cfg.location, cfg.fps)
    provider = OpenMeteoProvider()
    forecast: list[ForecastDay]
    location: Location | None
    offline_reason: str | None
    try:
        if args.demo_condition is not None:
            demo_condition = args.demo_condition
            state = MOCK[demo_condition].model_copy(
                update={"location_name": f"DEMO / {demo_condition.upper()}"}
            )
            forecast = []
            location = Location(
                name="Demo",
                country="ATMOS",
                latitude=13.7563,
                longitude=100.5018,
                timezone="Asia/Bangkok",
            )
            offline_reason = None
            log.info("starting local demo condition=%s", demo_condition)
        else:
            state, forecast, location, offline_reason = _resolve_initial(
                cfg,
                location_override=args.location_override,
                provider=provider,
            )
        if state is None or location is None:
            log.warning(
                "no weather available; entering retry loop. last_reason=%s",
                offline_reason,
            )
        else:
            log.info(
                "resolved location=%s condition=%s temp=%.1f offline=%s",
                location.name,
                state.condition,
                state.temperature,
                offline_reason is not None,
            )
    except Exception as exc:  # noqa: BLE001
        log.exception("fatal init error")
        sys.stderr.write(f"atmos: fatal init error: {exc}\n")
        provider.close()
        return 1
    with TerminalContext() as ctx:
        if not ctx.ok or ctx.term is None:
            provider.close()
            return 1
        term = ctx.term

        if state is None or location is None:
            return _run_no_data_loop(
                term, provider, cfg, log, offline_reason
            )

        return _run_ambient_loop(
            term,
            provider,
            cfg,
            log,
            state,
            forecast,
            location,
            offline_reason,
            demo=args.demo_condition is not None,
        )
def _run_ambient_loop(
    term,
    provider: OpenMeteoProvider,
    cfg: Config,
    log,
    state: WeatherState,
    forecast: list[ForecastDay],
    location: Location,
    offline_reason: str | None,
    *,
    demo: bool = False,
) -> int:

    inp = InputManager(term)
    loop = AnimationLoop(target_fps=cfg.fps)
    offline = offline_reason is not None
    current_state = state
    current_forecast = forecast
    current_location = location
    last_offline_msg = offline_reason
    current_lighting = compute_lighting(state)

    scene_name = select_scene_name(state)
    scene = SCENE_MAP[scene_name]()
    scene.enter(state)
    prev_buf: FrameBuffer | None = None

    mode = Mode.AMBIENT
    paused = False
    minimal = cfg.minimal
    search = LocationSearchState()
    layout_mgr = LayoutManager(term)
    geocode_worker = GeocodeWorker()
    transition = SceneTransition(duration_s=2.5)
    companion = WeatherCompanion(x=-8.0)


    refresher = WeatherRefresher(
        provider,
        location,
        interval_s=float(cfg.refresh_minutes) * 60.0,
        forecast_days=5,
    )
    if not demo:
        refresher.start()

    try:
        def step(dt: float) -> None:
            nonlocal scene_name, scene, offline, current_state, current_forecast
            nonlocal current_location, last_offline_msg, current_lighting
            nonlocal mode, paused, minimal, prev_buf, transition, search
            key = inp.read(dt)

            if key is not None:
                if _handle_global(
                    key,
                    loop=loop,
                    refresher=refresher,
                    allow_network=not demo,
                ):
                    return
                elif key.action == "space":
                    if mode != Mode.LOCATION:
                        paused = not paused

            if mode == Mode.AMBIENT:
                if key is not None and key.action == "char" and key.char is not None:
                    ch = key.char.lower()
                    if ch == "f":
                        mode = Mode.FORECAST
                    elif ch == "h":
                        mode = Mode.HELP
                    elif ch == "l":
                        if _activate_location_search(search, demo=demo):
                            mode = Mode.LOCATION
                    elif ch == "m":
                        minimal = not minimal

            elif mode == Mode.FORECAST:
                if key is not None and (
                    (key.action == "char" and (key.char or "").lower() == "f")
                    or key.action == "esc"
                ):
                    mode = Mode.AMBIENT

            elif mode == Mode.HELP:
                if key is not None:
                    mode = Mode.AMBIENT
                    if key.action == "char" and key.char is not None:
                        ch = key.char.lower()
                        if ch == "f":
                            mode = Mode.FORECAST
                        elif ch == "l":
                            if _activate_location_search(search, demo=demo):
                                mode = Mode.LOCATION
                        elif ch == "m":
                            minimal = not minimal

            elif mode == Mode.LOCATION:
                if key is None:
                    pass
                elif key.action == "esc":
                    mode = Mode.AMBIENT
                elif key.action == "enter":
                    if not demo and search.results:
                        idx = max(0, min(len(search.results) - 1, search.highlight))
                        new_loc = search.results[idx]
                        update_resolved_location(new_loc)
                        refresher.update_location(new_loc)
                        refresher.request_refresh()
                        # Mark the new city as "fetching"; the existing
                        # refresher thread will deliver the new state.
                        # Until then, show a "·fetching" tag at the header.
                        current_location = new_loc
                        offline = True
                        last_offline_msg = "fetching"
                    mode = Mode.AMBIENT
                elif key.action == "up":
                    search.highlight = max(0, search.highlight - 1)
                elif key.action == "down":
                    if search.results:
                        search.highlight = min(len(search.results) - 1, search.highlight + 1)
                elif key.action == "backspace":
                    search.query = search.query[:-1]
                    search.last_input_at = time.monotonic()
                elif key.action == "char" and key.char:
                    ch = key.char
                    if ch.isalnum() or ch in " -_.,'":
                        search.query += ch
                        search.last_input_at = time.monotonic()

            result: RefreshResult | None = refresher.drain_newest()
            if result is not None:
                current_state = result.state
                offline = result.offline
                last_offline_msg = result.error
                if result.forecast is not None:
                    current_forecast = result.forecast

                new_scene = select_scene_name(current_state)
                if new_scene != scene_name and mode == Mode.AMBIENT:
                    old = scene
                    new = SCENE_MAP[new_scene]()
                    new.enter(current_state)
                    transition.from_scene = old
                    transition.to_scene = new
                    transition.elapsed_s = 0.0
                    transition.duration_s = 2.5
                    scene = new
                    scene_name = new_scene

            lay = layout_mgr.update()
            # Derive a continuously-updating local time so the rendered
            # clock advances even between weather refreshes.
            effective_state = current_state.model_copy(
                update={"local_time": local_now(current_location)}
            )
            current_lighting = compute_lighting(effective_state)
            companion.update(
                dt,
                lay.width,
                effective_state.condition,
                paused=paused or mode != Mode.AMBIENT,
            )
            if transition.active:
                if transition.from_scene is not None and transition.to_scene is not None:
                    transition.from_scene.update(
                        dt, effective_state, lay.width, lay.height, current_lighting
                    )
                    transition.to_scene.update(
                        dt, effective_state, lay.width, lay.height, current_lighting
                    )
            transition.advance(dt)
            if lay.too_small:
                buf = FrameBuffer.empty(max(1, lay.width), max(1, lay.height))
                buf.write_line(0, 0, "terminal too small", "bright_red")
                buf.write_line(1, 0, "resize to at least 60 x 20", "red")
                buf.render_diff(prev_buf, term)
                prev_buf = buf
                return

            buf = FrameBuffer.empty(lay.width, lay.height)

            if mode == Mode.AMBIENT:
                if not paused:
                    scene.update(
                        dt, effective_state, lay.width, lay.height, current_lighting
                    )
                draw_header(buf, lay, effective_state)
                if transition.active and transition.from_scene is not None and transition.to_scene is not None:
                    from_w, to_w = blend_intensity(transition.progress)
                    transition.from_scene.draw(buf, current_lighting, dim=from_w)
                    transition.to_scene.draw(buf, current_lighting, dim=to_w)
                else:
                    scene.draw(buf, current_lighting, dim=1.0)
                if not minimal and lay.height >= 21:
                    companion.draw(buf, floor_y=lay.status_y - 2)
                draw_info(buf, lay, effective_state)
                if not minimal:
                    draw_status(buf, lay, effective_state)
                else:
                    _draw_minimal_status(buf, lay, effective_state)
                _fps_hud(buf, lay, 1.0 / dt if dt > 0 else 0.0, scene_name, offline)
                if offline and last_offline_msg:
                    tag = " \u00b7 offline"
                    buf.write_line(0, len(effective_state.location_name) + 1, tag, "240")
                if paused:
                    buf.write_line(0, 0, "PAUSED", "bright_yellow")
            elif mode == Mode.FORECAST:
                draw_header(buf, lay, effective_state)
                draw_forecast(
                    buf,
                    lay,
                    location_name=effective_state.location_name,
                    days=current_forecast,
                    offline=offline,
                )
            elif mode == Mode.HELP:
                draw_header(buf, lay, effective_state)
                draw_help(buf, lay)
            elif mode == Mode.LOCATION:
                now = time.monotonic()
                # Debounce: only submit a new request after the user
                # has been quiet for `search.debounce_s` seconds.
                if (
                    search.query
                    and now - search.last_input_at >= search.debounce_s
                    and search.last_input_at < now + 1e6
                ):
                    if not search.pending:
                        req = geocode_worker.submit(search.query)
                        search.request_id = req.id
                        search.pending = True
                        search.error = None
                    # Stop the debounce latch from firing again.
                    search.last_input_at = now + 1e9
                elif not search.query:
                    search.results = []
                    search.pending = False
                # Poll for results (non-blocking).
                result = geocode_worker.poll()
                if result is not None:
                    search.pending = False
                    search.results = result.locations
                    search.error = result.error
                    search.highlight = min(
                        search.highlight, max(0, len(search.results) - 1)
                    )
                draw_header(buf, lay, effective_state)
                draw_location_search(buf, lay, search)

            buf.render_diff(prev_buf, term)
            prev_buf = buf


        loop.run(step)
    except KeyboardInterrupt:
        loop.stop()
    finally:
        try:
            scene.exit()
        except Exception:  # noqa: BLE001
            pass
        if transition.from_scene is not None:
            try:
                transition.from_scene.exit()
            except Exception:  # noqa: BLE001
                pass
        refresher.stop()
    return 0


def _run_no_data_loop(
    term,
    provider: OpenMeteoProvider,
    cfg: Config,
    log,
    offline_reason: str | None,
) -> int:
    """Render the no-data screen until the user retries or quits.

    Listens for `R` (refresh) and `Q` (quit) only. On R, attempts a
    one-shot resolve via `_resolve_initial`; on success, swaps to the
    ambient loop in-place by calling `_run_ambient_loop` recursively.
    On failure, redraws the message with the latest reason.
    """
    inp = InputManager(term)
    layout_mgr = LayoutManager(term)
    prev_buf: FrameBuffer | None = None
    last_reason = offline_reason or "no data"
    log.warning("no-data screen active: %s", last_reason)

    while True:
        lay = layout_mgr.update()
        buf = FrameBuffer.empty(lay.width, lay.height)
        if lay.too_small:
            buf.write_line(0, 0, "terminal too small", "bright_red")
            buf.write_line(1, 0, "resize to at least 60 x 20", "red")
            buf.render_diff(prev_buf, term)
            prev_buf = buf
            return 1
        title = "unable to load weather"
        sub = f"{last_reason} - press R to retry, Q to quit"
        buf.write_centered(lay.height // 2 - 1, title, "bright_yellow")
        buf.write_centered(lay.height // 2 + 1, sub, "240")
        buf.render_diff(prev_buf, term)
        prev_buf = buf

        key = inp.read(0.05)
        if key is None:
            continue
        action = key.action
        if action == "char" and key.char is not None:
            action = action_for_char(key.char.lower())
        if action == "quit":
            return 0
        if action == "refresh":
            state, forecast, location, reason = _resolve_initial(
                cfg,
                location_override=None,
                provider=provider,
            )
            if state is not None and location is not None:
                log.info("retry succeeded; entering ambient loop")
                try:
                    return _run_ambient_loop(
                        term,
                        provider,
                        cfg,
                        log,
                        state,
                        forecast,
                        location,
                        reason,
                    )
                finally:
                    pass
            last_reason = reason or "still no data"
            log.warning("retry failed: %s", last_reason)






if __name__ == "__main__":
    sys.exit(main())
