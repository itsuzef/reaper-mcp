import base64
import logging
import os
import struct
import time
from pathlib import Path

import reapy
from reapy import reascript_api as RPR

from reaper_mcp.connection import get_project

logger = logging.getLogger("reaper_mcp.render_tools")

# REAPER RENDER_FORMAT codes
FORMAT_CODES = {
    "wav":  0,
    "mp3":  3,
    "ogg":  4,
    "flac": 5,
}

# REAPER RENDER_FORMAT2 codes for WAV bit depth
BIT_DEPTH_CODES = {
    16: 0,
    24: 2,
    32: 4,
}


def _set_render_settings(
    output_path: str,
    format: str,
    sample_rate: int,
    bit_depth: int,
    channels: int,
    bounds: int,
) -> None:
    """Configure REAPER's render settings. bounds: 0=entire project, 1=time selection."""
    fmt_code = FORMAT_CODES.get(format.lower(), 0)
    bdepth_code = BIT_DEPTH_CODES.get(bit_depth, 2)
    RPR.GetSetProjectInfo_String(0, "RENDER_FILE", output_path, True)
    RPR.GetSetProjectInfo(0, "RENDER_FORMAT", fmt_code, True)
    RPR.GetSetProjectInfo(0, "RENDER_FORMAT2", bdepth_code, True)
    RPR.GetSetProjectInfo(0, "RENDER_SRATE", float(sample_rate), True)
    RPR.GetSetProjectInfo(0, "RENDER_CHANNELS", float(channels), True)
    RPR.GetSetProjectInfo(0, "RENDER_BOUNDSFLAG", float(bounds), True)


def render_to_temp_file(sample_rate: int = 48000) -> str:
    """
    Render the current project to a temporary WAV file and return its path.
    Used by analysis and mastering tools. Caller is responsible for deleting the file.
    """
    import tempfile
    tmp = tempfile.mktemp(suffix=".wav")
    _set_render_settings(tmp, "wav", sample_rate, 24, 2, bounds=0)
    RPR.Main_OnCommand(41824, 0)
    return tmp


# ---------------------------------------------------------------------------
# Region rendering
#
# reapy's Region/Marker classes cannot be used for enumeration in reapy 0.10:
# Region exposes no `name` attribute, and Project.regions indexes into the
# combined marker+region list, so regions[0] can return a marker (with
# end == 0.0). EnumProjectMarkers2 is the reliable path.
# ---------------------------------------------------------------------------

BOUNDS_ALL_REGIONS = 3
BOUNDS_SELECTED_REGIONS = 5

RENDER_CURRENT_SETTINGS = 42230  # File: Render project, using the most recent settings

# RENDER_FORMAT is a base64-encoded, encoder-specific binary blob. The layout
# below was derived by inspecting blobs REAPER produced for known settings, and
# only applies to the AVFoundation encoder (FOURCC 'FVAX', i.e. 'XAVF'
# reversed). Other encoders lay their fields out differently, so every helper
# here refuses to touch a blob whose FOURCC does not match.
AVFOUNDATION_FOURCC = b"FVAX"
_AVF_FIELDS = {
    "video_bitrate_kbps": (12, "<i"),
    "audio_bitrate_kbps": (20, "<i"),
    "width":              (24, "<i"),
    "height":             (28, "<i"),
    "fps":                (32, "<f"),
}


def _decode_render_format(blob: str) -> dict:
    """Best-effort decode of RENDER_FORMAT. Reports the encoder either way."""
    raw = base64.b64decode(blob)
    decoded = {"encoder": raw[:4].decode("ascii", "replace")}
    if raw[:4] == AVFOUNDATION_FOURCC:
        for name, (offset, fmt) in _AVF_FIELDS.items():
            decoded[name] = struct.unpack_from(fmt, raw, offset)[0]
    return decoded


def _patch_render_format(blob: str, **fields) -> str:
    """Return blob with the named fields replaced. Non-AVFoundation blobs raise."""
    raw = bytearray(base64.b64decode(blob))
    if raw[:4] != AVFOUNDATION_FOURCC:
        raise ValueError(
            f"render format is {bytes(raw[:4])!r}, not AVFoundation "
            f"({AVFOUNDATION_FOURCC!r}); its byte layout is different, so these "
            "settings cannot be applied. Configure them in REAPER instead."
        )
    for name, value in fields.items():
        if value is None:
            continue
        offset, fmt = _AVF_FIELDS[name]
        struct.pack_into(fmt, raw, offset, float(value) if fmt == "<f" else int(value))
    return base64.b64encode(bytes(raw)).decode()


def _get_str(key: str) -> str:
    result = RPR.GetSetProjectInfo_String(0, key, "", False)
    return result[3] if isinstance(result, (tuple, list)) else result


def _set_str(key: str, value: str) -> None:
    RPR.GetSetProjectInfo_String(0, key, value, True)


def _parse_render_targets(raw: str, directory: str | None = None) -> list:
    """Split REAPER's semicolon-separated RENDER_TARGETS into paths.

    Region names may themselves contain ';', which would corrupt a naive split.
    When the output directory is known, split on the ';' that immediately
    precedes it instead, so only real separators are matched.
    """
    if not raw or not raw.strip():
        return []
    raw = raw.strip().rstrip(";")
    if directory:
        chunks = raw.split(";" + directory)
        parts = [chunks[0]] + [directory + chunk for chunk in chunks[1:]]
    else:
        parts = raw.split(";")
    return [part.strip() for part in parts if part.strip()]


def _conflicting_targets(targets: list) -> list:
    """Targets that already exist on disk.

    These matter because REAPER neither overwrites them nor reports the clash:
    RENDER_TARGETS still names `foo.mp4` when `foo.mp4` exists, and REAPER then
    writes `foo-001.mp4`. Left unhandled, a repeat render "succeeds" against the
    previous run's files while the new output hides under a suffixed name.
    """
    return [t for t in targets if os.path.exists(t)]


def _enum_regions() -> list:
    """Every region as {index, start, end, length}, via EnumProjectMarkers2.

    Region *names* are intentionally absent. Over reapy's distant API the name
    out-parameter comes back unfilled at any buffer size, even though REAPER
    resolves $region correctly server-side. Take names from RENDER_TARGETS,
    which does carry them.
    """
    count = RPR.CountProjectMarkers(0, 0, 0)
    total = count[0] if isinstance(count, (tuple, list)) else count
    regions = []
    for i in range(int(total)):
        marker = RPR.EnumProjectMarkers2(0, i, 0, 0.0, 0.0, "", 0)
        if not marker or marker[0] == 0:
            break
        _, _, _, is_region, position, region_end, _, number = marker
        if is_region:
            regions.append({"index": int(number), "start": position,
                            "end": region_end, "length": region_end - position})
    return regions


def _render_in_flight(directory: str) -> bool:
    """True while REAPER has a scratch file open in the directory.

    REAPER writes each output into `<name>.sb-<hash>` and renames it on
    completion, so the presence of one means a render is still open even if no
    bytes happened to land during the last poll. Stalling on that would restore
    the project's render settings underneath a running render.

    Observed directly mid-render: `halicali .mp4.sb-c78f8bee-k7rct1`.
    """
    if not directory or not os.path.isdir(directory):
        return False
    for entry in os.scandir(directory):
        try:
            if entry.is_file() and ".sb-" in entry.name:
                return True
        except OSError:
            continue
    return False


def _directory_activity(directory: str) -> tuple:
    """(file count, total bytes) for a directory, scratch files included.

    Any byte written anywhere under the output directory changes this, which is
    what distinguishes "still rendering" from "stopped".
    """
    if not directory or not os.path.isdir(directory):
        return (0, 0)
    count = total = 0
    for entry in os.scandir(directory):
        try:
            if entry.is_file():
                count += 1
                total += entry.stat().st_size
        except OSError:
            continue
    return (count, total)


def _await_render(targets: list, stall_timeout: float = 120.0,
                  timeout: float = 3600.0, poll_interval: float = 1.0,
                  scratch_grace: float | None = None) -> tuple:
    """Wait for a render to finish. Returns (files, status).

    status is "complete", "stalled" or "timeout".

    RENDER_CURRENT_SETTINGS is not reliably synchronous and REAPER exposes no
    "am I rendering" flag, so progress has to be inferred from the filesystem.

    Completion requires every expected target to exist at a stable non-zero
    size. Waiting on the known target list, rather than globbing the directory,
    keeps REAPER's `<name>.sb-<hash>` scratch files from being counted as
    output and stops the gap between two regions being read as completion.

    Progress, separately, is measured across the whole directory *including*
    those scratch files, because that is where bytes land while a file is being
    written. A render that fails, errors or is cancelled stops producing bytes,
    so it trips stall_timeout instead of blocking for the full timeout.

    Stalling is deliberately conservative, because giving up restores the
    project's render settings: while a scratch file is present the render is
    still open, so quiet time is tolerated up to scratch_grace (3x
    stall_timeout by default) rather than stall_timeout.

    Measured against a real aborted render (dialog closed 10s in): REAPER
    removes its own scratch file on cancel and leaves no partial output at all,
    since bytes go to the scratch and it is renamed only on success. So a
    user-cancelled render is caught by stall_timeout, not scratch_grace - it
    returned "stalled" 10.5s after the abort with stall_timeout=10, and zero
    files. scratch_grace therefore only covers a hard crash that orphans a
    scratch file, which is the rarer case.

    The 120s default is not a guess. Measured on a full-resolution region
    render (1728x3072 @ 50fps, 40 Mbps, 7 regions, 1.2 GB written in 117s),
    the longest interval between writes was under 0.25s - the sampling floor,
    i.e. bytes landed on every sample. The default is ~500x that, so a false
    stall on a healthy render is not a realistic risk.
    """
    def collect():
        return [{"path": t, "size_bytes": os.path.getsize(t)}
                for t in targets if os.path.exists(t)]

    if not targets:
        return [], "complete"

    directory = os.path.dirname(targets[0])
    if scratch_grace is None:
        scratch_grace = stall_timeout * 3
    deadline = time.time() + timeout
    last_activity = time.time()
    activity = _directory_activity(directory)
    previous, stable = None, 0

    while time.time() < deadline:
        current = _directory_activity(directory)
        if current != activity:
            activity, last_activity = current, time.time()

        sizes = {t: os.path.getsize(t) for t in targets if os.path.exists(t)}
        finished = len(sizes) == len(targets) and all(size > 0 for size in sizes.values())
        if finished and sizes == previous:
            stable += 1
            if stable >= 3:
                return collect(), "complete"
        else:
            stable = 0
        previous = sizes

        quiet = time.time() - last_activity
        limit = scratch_grace if _render_in_flight(directory) else stall_timeout
        if quiet > limit:
            return collect(), "stalled"
        time.sleep(poll_interval)
    return collect(), "timeout"


def register_tools(mcp):

    @mcp.tool()
    def render_project(
        output_path: str,
        format: str = "wav",
        sample_rate: int = 48000,
        bit_depth: int = 24,
        channels: int = 2,
    ) -> dict:
        """
        Render the entire project to a file.
        format: wav, flac, mp3 (requires LAME), ogg.
        sample_rate: e.g. 44100, 48000, 96000.
        bit_depth: 16, 24, or 32 (WAV only; ignored for mp3/ogg/flac).
        channels: 1 (mono) or 2 (stereo).
        """
        try:
            output_path = str(Path(output_path).expanduser().resolve())
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            _set_render_settings(output_path, format, sample_rate, bit_depth, channels, bounds=0)
            RPR.Main_OnCommand(41824, 0)  # File: Render project to disk (no dialog)
            if not os.path.exists(output_path):
                return {"success": False, "error": "Render command completed but output file not found"}
            return {
                "success": True,
                "output_path": output_path,
                "format": format,
                "sample_rate": sample_rate,
                "bit_depth": bit_depth,
                "channels": channels,
                "file_size_bytes": os.path.getsize(output_path),
            }
        except Exception as e:
            logger.error(f"render_project failed: {e}")
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def render_time_selection(
        output_path: str,
        start: float,
        end: float,
        format: str = "wav",
        sample_rate: int = 48000,
        bit_depth: int = 24,
        channels: int = 2,
    ) -> dict:
        """Render a specific time range of the project to a file."""
        try:
            output_path = str(Path(output_path).expanduser().resolve())
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            project = get_project()
            project.time_selection = (start, end)
            _set_render_settings(output_path, format, sample_rate, bit_depth, channels, bounds=1)
            RPR.Main_OnCommand(41824, 0)
            if not os.path.exists(output_path):
                return {"success": False, "error": "Render completed but output file not found"}
            return {
                "success": True,
                "output_path": output_path,
                "start": start,
                "end": end,
                "format": format,
                "file_size_bytes": os.path.getsize(output_path),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def render_stems(
        output_directory: str,
        track_indices: list = None,
        format: str = "wav",
        sample_rate: int = 48000,
        bit_depth: int = 24,
    ) -> dict:
        """
        Render each track as a separate stem file by soloing each track individually.
        track_indices: list of track indices, or null to render all tracks.
        Files are named after the track names in the output directory.
        """
        try:
            output_directory = str(Path(output_directory).expanduser().resolve())
            os.makedirs(output_directory, exist_ok=True)
            project = get_project()
            indices = track_indices if track_indices is not None else list(range(project.n_tracks))
            rendered = []

            for idx in indices:
                track = project.tracks[idx]
                track_name = track.name or f"Track_{idx}"
                # Solo this track exclusively
                for j in range(project.n_tracks):
                    project.tracks[j].solo = (j == idx)
                # Sanitize filename
                safe_name = "".join(c if c.isalnum() or c in " _-" else "_" for c in track_name)
                stem_path = os.path.join(output_directory, f"{safe_name}.{format}")
                _set_render_settings(stem_path, format, sample_rate, bit_depth, 2, bounds=0)
                RPR.Main_OnCommand(41824, 0)
                rendered.append({
                    "track_index": idx,
                    "track_name": track_name,
                    "output_path": stem_path,
                    "exists": os.path.exists(stem_path),
                })

            # Unsolo all tracks
            for j in range(project.n_tracks):
                project.tracks[j].solo = False

            return {
                "success": True,
                "output_directory": output_directory,
                "stems": rendered,
            }
        except Exception as e:
            # Always unsolo on error
            try:
                proj = get_project()
                for j in range(proj.n_tracks):
                    proj.tracks[j].solo = False
            except Exception:
                pass
            logger.error(f"render_stems failed: {e}")
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def render_regions(
        output_directory: str,
        pattern: str = "$region",
        selected_only: bool = False,
        dry_run: bool = False,
        video_bitrate_kbps: int | None = None,
        audio_bitrate_kbps: int | None = None,
        width: int | None = None,
        height: int | None = None,
        fps: float | None = None,
        stall_timeout_seconds: float = 120.0,
        timeout_seconds: float = 3600.0,
    ) -> dict:
        """
        Render every region in the project to its own file, named by region.

        Use this for video, and for any per-region export. The other render_*
        tools are audio-only and cannot address regions.

        output_directory: where files are written.
        pattern: filename pattern. "$region" names each file after its region;
            $regionnumber, $project and $track are also available.
        selected_only: render only the selected regions rather than all of them.
        dry_run: return the regions and the exact filenames REAPER would write,
            without rendering. Cheap — worth calling before a long render.

        If any output file already exists the call fails before rendering and
        lists the offenders. REAPER neither overwrites nor reports such a
        clash - it writes `<name>-001.<ext>` instead - so a repeat render would
        otherwise report success while the caller reads the previous run's
        files. Move or delete them yourself, or render somewhere else: this
        tool never deletes anything.

        Encoding is inherited from the project's own render settings unless
        overridden. The optional video_bitrate_kbps, audio_bitrate_kbps, width,
        height and fps arguments require REAPER's AVFoundation encoder and fail
        cleanly on any other; omitting them is the recommended path.

        This call BLOCKS until the render finishes, which for a long project
        can be many minutes. That is not incidental: the project's render
        settings have to stay in place until REAPER is done with them, and are
        restored on return. Bound the wait with stall_timeout_seconds (how long
        with no bytes written before giving up, when REAPER has no scratch file
        open) and timeout_seconds (the hard ceiling). The result reports status
        "complete", "stalled" or "timeout" along with whatever was written.

        REAPER shows a "Rendering to file..." progress window for the duration.
        Closing that window cancels the render: the tool then reports status
        "stalled" and no files, because REAPER discards its scratch file rather
        than leaving partial output. Worth knowing if a person is at the
        machine while an agent drives this.
        """
        saved_strings, saved_numbers = {}, {}
        try:
            output_directory = str(Path(output_directory).expanduser().resolve())
            os.makedirs(output_directory, exist_ok=True)

            for key in ("RENDER_FILE", "RENDER_PATTERN", "RENDER_FORMAT"):
                saved_strings[key] = _get_str(key)
            saved_numbers["RENDER_BOUNDSFLAG"] = RPR.GetSetProjectInfo(
                0, "RENDER_BOUNDSFLAG", 0, False)

            regions = _enum_regions()
            if not regions:
                return {"success": False,
                        "error": "no regions are defined in the current project"}

            overrides = {"video_bitrate_kbps": video_bitrate_kbps,
                         "audio_bitrate_kbps": audio_bitrate_kbps,
                         "width": width, "height": height, "fps": fps}
            if any(value is not None for value in overrides.values()):
                try:
                    _set_str("RENDER_FORMAT",
                             _patch_render_format(saved_strings["RENDER_FORMAT"], **overrides))
                except ValueError as e:
                    return {"success": False, "error": str(e)}

            _set_str("RENDER_FILE", output_directory)
            _set_str("RENDER_PATTERN", pattern)
            RPR.GetSetProjectInfo(0, "RENDER_BOUNDSFLAG", float(
                BOUNDS_SELECTED_REGIONS if selected_only else BOUNDS_ALL_REGIONS), True)

            targets = _parse_render_targets(_get_str("RENDER_TARGETS"), output_directory)
            if not targets:
                return {"success": False,
                        "error": "REAPER reported no render targets; if selected_only "
                                 "is set, check that regions are actually selected"}

            clashes = _conflicting_targets(targets)

            if dry_run:
                return {"success": True, "dry_run": True,
                        "already_exist": clashes,
                        "output_directory": output_directory,
                        "region_count": len(regions), "regions": regions,
                        "would_write": targets,
                        "settings": _decode_render_format(_get_str("RENDER_FORMAT"))}

            settings = _decode_render_format(_get_str("RENDER_FORMAT"))
            if clashes:
                return {"success": False,
                        "error": f"{len(clashes)} output file(s) already exist. REAPER "
                                 "would not overwrite them - it would write '<name>-001' "
                                 "instead and still report the originals as the targets, so "
                                 "this would look like a success against stale files. Move "
                                 "or delete them, or render into an empty directory.",
                        "already_exist": clashes}

            started = time.time()
            RPR.Main_OnCommand(RENDER_CURRENT_SETTINGS, 0)
            written, status = _await_render(
                targets, stall_timeout=stall_timeout_seconds, timeout=timeout_seconds)
            complete = status == "complete"

            result = {"success": complete,
                       "output_directory": output_directory,
                       "region_count": len(regions),
                       "files_written": len(written),
                       "files": written,
                       "expected": targets,
                       "complete": complete,
                       "status": status,
                       "settings": settings,
                       "elapsed_seconds": round(time.time() - started, 1)}
            if not complete:
                result["error"] = (
                    f"render did not finish ({status}): wrote {len(written)} of "
                    f"{len(targets)} expected files")
            return result
        except Exception as e:
            logger.error(f"render_regions failed: {e}")
            return {"success": False, "error": str(e)}
        finally:
            for key, value in saved_strings.items():
                _set_str(key, value)
            for key, value in saved_numbers.items():
                RPR.GetSetProjectInfo(0, key, value, True)
