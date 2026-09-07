# REAPER MCP Server

A Model Context Protocol (MCP) server that enables AI agents to control REAPER DAW — 58 tools covering project management, tracks, MIDI, FX, mixing, mastering, rendering, and audio analysis.

## Requirements

- [REAPER](https://www.reaper.fm/) DAW installed and running
- Python 3.10+
- REAPER's distant API enabled (see [Setup](#setting-up-reaper))

## Installation

```bash
pip install reaper-mcp-server
```

Or install from source:

```bash
git clone https://github.com/bonfire-systems/reaper-mcp.git
cd reaper-mcp
pip install -e .
```

## Setting Up REAPER

The server communicates with REAPER via [python-reapy](https://github.com/RomeoDespres/reapy), which requires REAPER's distant API to be enabled.

1. Open REAPER
2. Go to Actions > Run ReaScript
3. Select `scripts/enable_reapy.py` from this repo (or create a new script with the contents below)
   ```python
   import reapy
   reapy.config.enable_dist_api()
   ```
4. Restart REAPER

The bundled `scripts/enable_reapy.py` adds the project's virtual-environment
packages before importing `reapy`, because REAPER's embedded Python does not
inherit the normal shell environment. If REAPER does not define `__file__` for
the script, the helper uses `REAPER_MCP_ROOT` or this default installation
path:

```bash
export REAPER_MCP_ROOT="$PWD"
```

### Troubleshooting the distant API

- `ModuleNotFoundError: No module named 'reapy'`: run the bundled helper from
  this repository. Do not rely on REAPER's embedded Python to find the MCP
  virtual environment automatically.
- Python 3.14 may fail while `reapy.config.configure_reaper()` writes
  `reaper.ini` because of a `configparser` compatibility issue. Use a Python
  3.12 environment for `python-reapy` configuration and keep REAPER pointed at
  the matching Python 3.12 dylib.
- `OSError: [Errno 48] Address already in use` on port 2306 means the reapy
  command server is already running. Do not launch
  `activate_reapy_server.py` a second time; fully quit and reopen REAPER if a
  stale server must be cleared.
- If the web interface on port 2307 is listening but port 2306 is not, trigger
  the registered `activate_reapy_server.py` action once from REAPER's action
  list. After activation, test the bridge from the same environment used by
  the MCP server.
- If configuration fails, restore `reaper.ini` from the `.bak` file created by
  reapy before retrying. Verify that it still contains the `[reaper]` section,
  `reascript=1`, the Python 3.12 library settings, and the HTTP web interface
  on port 2307.

## Usage

### With Claude Desktop

Add to your Claude Desktop config (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "reaper": {
      "command": "reaper-mcp-server",
      "args": []
    }
  }
}
```

### With Claude Code

```bash
claude mcp add reaper -- reaper-mcp-server
```

### Standalone

```bash
reaper-mcp-server          # start the server
reaper-mcp-server --debug  # with debug logging
```

## Tools (58)

### Project Management
`create_project` `load_project` `save_project` `get_project_info` `set_tempo` `set_time_signature` `set_cursor_position` `play_project` `stop_transport`

### Tracks
`create_track` `delete_track` `rename_track` `list_tracks` `get_track_info` `set_track_color` `create_bus` `create_send` `remove_send` `list_sends`

### MIDI
`create_midi_item` `add_midi_note` `create_chord_progression` `create_drum_pattern`

### FX & Instruments
`add_fx` `remove_fx` `bypass_fx` `list_track_fx` `get_fx_parameters` `set_fx_parameter` `load_fx_preset` `add_master_fx` `list_master_fx` `set_master_fx_parameter`

### Audio
`import_audio_file` `edit_audio_item` `start_recording` `adjust_pitch` `adjust_playback_rate`

### Mixing
`set_track_volume` `set_track_pan` `set_track_mute` `set_track_solo` `set_send_volume` `set_master_volume` `add_volume_automation` `add_pan_automation`

### Rendering
`render_project` `render_stems` `render_time_selection`

### Mastering
`apply_mastering_chain` `apply_limiter` `normalize_project`

### Analysis
`analyze_loudness` `analyze_dynamics` `analyze_frequency_spectrum` `analyze_stereo_field` `analyze_transients` `detect_clipping`

## Configuration

The server stores its configuration in your platform's config directory:

- macOS: `~/Library/Application Support/reaper-mcp/config.json`
- Linux: `~/.config/reaper-mcp/config.json`
- Windows: `%APPDATA%\reaper-mcp\config.json`

## License

MIT
