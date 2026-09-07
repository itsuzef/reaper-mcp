import os
import time
import logging
from pathlib import Path

import reapy
from reapy import reascript_api as RPR

from reaper_mcp.connection import get_project

logger = logging.getLogger("reaper_mcp.project_tools")


def _project_time_signature(project, position=0.0):
    """Return the native REAPER time signature at a project position."""
    _, _, numerator, denominator, _ = RPR.TimeMap_GetTimeSigAtTime(
        project.id, position, 0, 0, 0.0
    )
    return numerator, denominator


def register_tools(mcp):

    @mcp.tool()
    def create_project(tempo: float = 120.0, time_signature: str = "4/4", name: str = "") -> dict:
        """Create a new REAPER project with the given tempo and time signature."""
        try:
            RPR.Main_OnCommand(41929, 0)  # File: New project
            project = get_project()
            project.bpm = tempo
            if time_signature:
                num, denom = map(int, time_signature.split("/"))
                RPR.SetTempoTimeSigMarker(
                    project.id,
                    -1,
                    0,
                    0,
                    0.0,
                    tempo,
                    num,
                    denom,
                    False,
                )
            actual_num, actual_denom = _project_time_signature(project)
            return {
                "success": True,
                "name": name or f"New Project {time.strftime('%Y-%m-%d %H-%M-%S')}",
                "tempo": project.bpm,
                "time_signature": f"{actual_num}/{actual_denom}",
            }
        except Exception as e:
            logger.error(f"create_project failed: {e}")
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def save_project(project_path: str = "") -> dict:
        """Save the current project. If no path is given, saves to ~/Documents/REAPER Projects."""
        try:
            project = get_project()
            if not project_path:
                proj_name = project.name or f"Project {time.strftime('%Y-%m-%d %H-%M-%S')}"
                default_dir = Path.home() / "Documents" / "REAPER Projects"
                os.makedirs(default_dir, exist_ok=True)
                project_path = str(default_dir / f"{proj_name}.rpp")
            os.makedirs(os.path.dirname(os.path.abspath(project_path)), exist_ok=True)
            RPR.Main_SaveProjectEx(project.id, project_path, 0)
            return {"success": True, "project_path": project_path}
        except Exception as e:
            logger.error(f"save_project failed: {e}")
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def load_project(project_path: str) -> dict:
        """Load a REAPER project (.rpp) from the given file path."""
        try:
            if not os.path.exists(project_path):
                return {"success": False, "error": f"File not found: {project_path}"}
            RPR.Main_openProject(project_path)
            project = get_project()
            numerator, denominator = _project_time_signature(project)
            return {
                "success": True,
                "name": project.name,
                "tempo": project.bpm,
                "time_signature": f"{numerator}/{denominator}",
                "project_path": project_path,
            }
        except Exception as e:
            logger.error(f"load_project failed: {e}")
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def get_project_info() -> dict:
        """Get information about the current project: name, path, tempo, tracks, length."""
        try:
            project = get_project()
            numerator, denominator = _project_time_signature(project)
            markers = []
            try:
                for i in range(project.n_markers):
                    m = project.markers[i]
                    markers.append({"index": i, "name": m.name, "position": m.position})
            except Exception:
                pass

            regions = []
            try:
                for i in range(project.n_regions):
                    r = project.regions[i]
                    regions.append({"index": i, "name": r.name, "start": r.start, "end": r.end})
            except Exception:
                pass

            return {
                "success": True,
                "name": project.name,
                "path": project.path,
                "tempo": project.bpm,
                "time_signature": f"{numerator}/{denominator}",
                "length": project.length,
                "track_count": project.n_tracks,
                "markers": markers,
                "regions": regions,
            }
        except Exception as e:
            logger.error(f"get_project_info failed: {e}")
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_tempo(bpm: float) -> dict:
        """Set the project tempo in BPM."""
        try:
            project = get_project()
            project.bpm = bpm
            return {"success": True, "tempo": project.bpm}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_time_signature(numerator: int, denominator: int) -> dict:
        """Set the project time signature, e.g. 4/4, 3/4, 6/8."""
        try:
            project = get_project()
            RPR.SetTempoTimeSigMarker(
                project.id,
                -1,
                project.cursor_position,
                0,
                0.0,
                project.bpm,
                numerator,
                denominator,
                False,
            )
            actual_num, actual_denom = _project_time_signature(project, project.cursor_position)
            return {"success": True, "time_signature": f"{actual_num}/{actual_denom}"}
        except Exception as e:
            return {"success": False, "error": str(e)}
