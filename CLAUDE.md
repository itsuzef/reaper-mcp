# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

reaper-mcp is a Python MCP server that connects Claude (and other AI assistants) to the REAPER DAW. It supports two communication backends — ReaScript (via `reapy`) and OSC (via `python-osc`) — and exposes tools for project management, track operations, MIDI composition, mixing, analysis, and mastering.

## Setup & Running

Requires Python 3.8+ and REAPER running.

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -e .
pip install -e ".[dev]"         # includes pytest, black, isort
```

**Start the server:**
```bash
# Recommended: use the startup script (auto-selects OSC mode)
./start_reaper_mcp.sh           # macOS/Linux
scripts/start_reaper_mcp_server.bat    # Windows CMD
scripts/start_reaper_mcp_server.ps1   # Windows PowerShell

# Or run directly
python simple_mcp_server.py     # simplest entry point
python osc_mcp_server.py        # OSC mode
python -m reaper_mcp            # ReaScript mode via src/ package
```

**Run tests:**
```bash
pytest                          # from repo root
```

**Lint/format:**
```bash
black src/
isort src/
```

## Architecture: Two Communication Backends

### ReaScript mode (`src/reaper_mcp/`)
Uses `reapy` (Python bindings for REAPER's ReaScript API) to control REAPER directly. More capable but requires ReaScript to be enabled in REAPER preferences. Falls back to OSC mode on connection failure.

- Entry: `src/reaper_mcp/server.py` → `ReaperMCPServer`
- Connects via `reapy.connect()` on startup
- Tools in `server.py` call `reapy.Project()`, `track.add_item()`, etc. directly

### OSC mode (`src/reaper_mcp/osc_server.py`, `osc_mcp_server.py`)
Uses `python-osc` to send OSC messages to REAPER's built-in OSC listener. More reliable when ReaScript API is unavailable. Sends commands to REAPER's OSC port and receives state updates via a background listener thread.

- Default send port: **8000** (REAPER listens)
- Default receive port: **9000** (server listens for REAPER responses)
- REAPER action IDs are used to trigger operations (e.g. `40023` = new project, `40001` = insert track)
- OSC state is maintained in `self.current_project` dict since REAPER doesn't respond synchronously

**REAPER OSC setup:** Preferences > Control/OSC/web > Add > OSC, set send/receive ports to match.

## Key Files

| File | Purpose |
|------|---------|
| `simple_mcp_server.py` | Minimal single-file MCP server (good starting point) |
| `osc_mcp_server.py` | Standalone OSC-mode MCP server |
| `windsurf_mcp_server.py` | Windsurf-compatible variant |
| `src/reaper_mcp/server.py` | Full ReaScript-mode server (`ReaperMCPServer` class) |
| `src/reaper_mcp/osc_server.py` | Full OSC-mode server (`ReaperOSCServer` class) |
| `src/reaper_mcp/config.py` | Config loader; reads/writes `config.json`; `DEFAULT_CONFIG` has all defaults |
| `config.json` | Runtime config (project dir, VST dirs, tempo, mastering presets) |

## Tool Domain Modules (`src/reaper_mcp/`)

Each module is a class that receives the config dict and implements a group of MCP tools registered in `server.py`:

- `project_tools.py` — create/save/render projects
- `track_tools.py` — create/route/configure tracks
- `midi_tools.py` — MIDI item and note operations
- `audio_tools.py` — audio recording and import
- `fx_tools.py` — VST/plugin management
- `mixing_tools.py` — EQ presets, automation, bus routing
- `mastering_tools.py` — mastering chains, loudness, limiting, normalization
- `analysis_tools.py` — frequency spectrum, clipping, stereo field, dynamics

## Configuration (`config.json`)

Generated automatically on first run from `DEFAULT_CONFIG`. Key fields:

- `default_project_directory` — where new projects are saved
- `default_tempo`, `default_time_signature`, `default_sample_rate`, `default_bit_depth`
- `mastering_presets` — named chains of ReaPlugs FX with params (`default`, `loud`, `gentle`)
- `vst_directories`, `sample_libraries` — paths for asset discovery

## Workflows & Examples

- `workflows/` — markdown prompt templates for common AI-assisted tasks (mix critique, mastering QC, vocal processing, release prep, etc.)
- `examples/` — Python scripts demonstrating MCP tool usage (drum patterns, track creation, OSC testing)
