import logging
import math

import reapy
from reapy import reascript_api as RPR

from reaper_mcp.connection import get_project

logger = logging.getLogger("reaper_mcp.track_tools")


def _track_volume_db(track):
    """Return a track's volume in dB using REAPER's native linear value."""
    linear = RPR.GetMediaTrackInfo_Value(track.id, "D_VOL")
    if linear <= 0:
        return -150.0
    return 20.0 * math.log10(linear)


def _set_track_volume_db(track, volume_db):
    """Set a track's volume from dB using REAPER's native linear value."""
    linear = 10.0 ** (volume_db / 20.0)
    RPR.SetMediaTrackInfo_Value(track.id, "D_VOL", linear)


def _track_pan(track):
    """Return a track's pan using REAPER's native value."""
    return RPR.GetMediaTrackInfo_Value(track.id, "D_PAN")


def _set_track_pan(track, pan):
    """Set a track's pan using REAPER's native value."""
    RPR.SetMediaTrackInfo_Value(track.id, "D_PAN", pan)


def _track_muted(track):
    """Return whether a track is muted using REAPER's native value."""
    return bool(RPR.GetMediaTrackInfo_Value(track.id, "B_MUTE"))


def _set_track_muted(track, muted):
    """Set whether a track is muted using REAPER's native value."""
    RPR.SetMediaTrackInfo_Value(track.id, "B_MUTE", 1.0 if muted else 0.0)


def _track_soloed(track):
    """Return whether a track is soloed using REAPER's native value."""
    return RPR.GetMediaTrackInfo_Value(track.id, "I_SOLO") != 0


def _set_track_soloed(track, soloed):
    """Set whether a track is soloed using REAPER's native value."""
    RPR.SetMediaTrackInfo_Value(track.id, "I_SOLO", 1.0 if soloed else 0.0)


def register_tools(mcp):

    @mcp.tool()
    def create_track(name: str, track_type: str = "audio") -> dict:
        """
        Create a new track at the end of the project.
        track_type: audio, midi, instrument, folder
        """
        try:
            project = get_project()
            idx = project.n_tracks
            project.add_track(idx, name)
            track = project.tracks[idx]

            if track_type in ("midi", "instrument"):
                RPR.SetMediaTrackInfo_Value(track.id, "I_RECINPUT", 4096)  # All MIDI inputs
            elif track_type == "folder":
                RPR.SetMediaTrackInfo_Value(track.id, "I_FOLDERDEPTH", 1)

            return {
                "success": True,
                "track_index": idx,
                "name": track.name,
                "type": track_type,
            }
        except Exception as e:
            logger.error(f"create_track failed: {e}")
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def delete_track(track_index: int) -> dict:
        """Delete a track by its index."""
        try:
            project = get_project()
            track = project.tracks[track_index]
            RPR.DeleteTrack(track.id)
            return {"success": True, "deleted_index": track_index}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def rename_track(track_index: int, name: str) -> dict:
        """Rename a track."""
        try:
            project = get_project()
            track = project.tracks[track_index]
            track.name = name
            return {"success": True, "track_index": track_index, "name": track.name}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_track_volume(track_index: int, volume_db: float) -> dict:
        """Set track volume in dB. Range: roughly -150 to +12 dB."""
        try:
            project = get_project()
            track = project.tracks[track_index]
            _set_track_volume_db(track, volume_db)
            return {"success": True, "track_index": track_index, "volume_db": _track_volume_db(track)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_track_pan(track_index: int, pan: float) -> dict:
        """Set track pan. -1.0 = full left, 0.0 = center, 1.0 = full right."""
        try:
            project = get_project()
            track = project.tracks[track_index]
            _set_track_pan(track, pan)
            return {"success": True, "track_index": track_index, "pan": _track_pan(track)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_track_mute(track_index: int, muted: bool) -> dict:
        """Mute or unmute a track."""
        try:
            project = get_project()
            track = project.tracks[track_index]
            _set_track_muted(track, muted)
            return {"success": True, "track_index": track_index, "muted": _track_muted(track)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_track_solo(track_index: int, soloed: bool) -> dict:
        """Solo or unsolo a track."""
        try:
            project = get_project()
            track = project.tracks[track_index]
            _set_track_soloed(track, soloed)
            return {"success": True, "track_index": track_index, "soloed": _track_soloed(track)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def get_track_info(track_index: int) -> dict:
        """Get detailed information about a track including FX and items."""
        try:
            project = get_project()
            track = project.tracks[track_index]

            fx_list = []
            for i in range(track.n_fxs):
                fx = track.fxs[i]
                fx_list.append({"index": i, "name": fx.name, "enabled": fx.is_enabled})

            items = []
            for i in range(track.n_items):
                item = track.items[i]
                items.append({
                    "index": i,
                    "position": item.position,
                    "length": item.length,
                    "name": item.name,
                })

            return {
                "success": True,
                "track_index": track_index,
                "name": track.name,
                "volume_db": _track_volume_db(track),
                "pan": _track_pan(track),
                "muted": _track_muted(track),
                "soloed": _track_soloed(track),
                "fx_count": track.n_fxs,
                "fx": fx_list,
                "item_count": track.n_items,
                "items": items,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def list_tracks() -> dict:
        """List all tracks in the current project with their basic parameters."""
        try:
            project = get_project()
            tracks = []
            for i in range(project.n_tracks):
                track = project.tracks[i]
                tracks.append({
                    "index": i,
                    "name": track.name,
                    "volume_db": _track_volume_db(track),
                    "pan": _track_pan(track),
                    "muted": _track_muted(track),
                    "soloed": _track_soloed(track),
                    "fx_count": track.n_fxs,
                    "item_count": track.n_items,
                })
            return {"success": True, "count": len(tracks), "tracks": tracks}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_track_color(track_index: int, r: int, g: int, b: int) -> dict:
        """Set track color using RGB values (0–255 each)."""
        try:
            project = get_project()
            track = project.tracks[track_index]
            color = RPR.ColorToNative(r, g, b) | 0x1000000
            RPR.SetMediaTrackInfo_Value(track.id, "I_CUSTOMCOLOR", color)
            return {"success": True, "track_index": track_index, "r": r, "g": g, "b": b}
        except Exception as e:
            return {"success": False, "error": str(e)}
