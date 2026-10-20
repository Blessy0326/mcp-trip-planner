# Weather-Aware Trip Planner

A small learning project for **MCP (Model Context Protocol) orchestration**, running fully locally and free of cost with **Ollama**.

## Idea

You ask something like *"Plan my Saturday in Munich. If it rains, pick indoor stuff, and put it in my calendar."*

A local LLM then works through it by calling tools from three separate MCP servers:

- **weather**: gets the forecast for a city and day from the free Open-Meteo API
- **places**: finds indoor or outdoor things to do from a local list (`data/places.json`)
- **calendar**: reads and writes events in a local file (`data/calendar.json`) and rejects overlapping bookings

An orchestrator connects to all three servers, collects their tools, gives them to the LLM, and runs the tool calls the LLM asks for.

## How it works

1. **Startup**: `mcp_hub.py` starts each server as its own process, connects to it over MCP, and asks for its list of tools. Tool names are prefixed with the server name (for example `calendar__add_event`) so the hub knows where each call belongs.
2. **Request**: `orchestrator.py` sends your message, a system prompt, and the list of all tools to the LLM running in Ollama.
3. **Tool call**: the LLM does not run anything itself. It replies with the tool it wants and the arguments.
4. **Routing**: the hub sends the call to the right server, which runs the Python function and returns the result.
5. **Feedback**: the result (or an error, such as a calendar overlap) is added to the conversation and sent back to the LLM, so it can decide the next step or correct itself.
6. **Finish**: steps 3 to 5 repeat until the LLM replies with plain text instead of a tool call. That reply is the final plan.

## Project structure

```
trip-planner-mcp/
├── servers/
│   ├── weather_server.py
│   ├── places_server.py
│   └── calendar_server.py
├── data/
│   ├── places.json
│   └── calendar.json
├── mcp_hub.py          # connects to all servers, merges and routes tools
├── orchestrator.py     # the LLM loop, talks to Ollama
├── explore.py          # call the tools by hand, without an LLM
├── servers.json        # list of servers to start
└── requirements.txt
```

## Requirements

- Python 3.10 or newer
- Ollama with a model that supports tool calling, for example `qwen2.5:3b` (works on 8 GB RAM) or `qwen2.5:7b-instruct` (needs about 16 GB RAM)
- Internet access for live weather (optional, see mock mode)
- Node.js, only if you want to use the MCP Inspector (optional)

## Setup on Windows (PowerShell)

1. Install Ollama from https://ollama.com or with:
   ```powershell
   winget install Ollama.Ollama
   ```
   Close and reopen PowerShell afterwards.
2. Download a model:
   ```powershell
   ollama pull qwen2.5:3b
   ```
3. Clone the project:
   ```powershell
   git clone https://github.com/<your-username>/trip-planner-mcp.git
   cd trip-planner-mcp
   ```
4. Create and activate a virtual environment:
   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   ```
   If you get "running scripts is disabled on this system", run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once and try again.
5. Install the dependencies:
   ```powershell
   pip install -r requirements.txt
   ```

## Setup on Linux (bash)

1. Install Ollama:
   ```bash
   curl -fsSL https://ollama.com/install.sh | sh
   ```
2. Download a model:
   ```bash
   ollama pull qwen2.5:3b
   ```
3. Clone the project:
   ```bash
   git clone https://github.com/<your-username>/trip-planner-mcp.git
   cd trip-planner-mcp
   ```
4. Create and activate a virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
5. Install the dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Running the project

Before running, make sure Ollama is running (open the Ollama app on Windows, or run `ollama serve` in a separate terminal on Linux) and the virtual environment is active.

### Step 1: Try the tools without an LLM

These commands are the same on Windows and Linux:

```bash
python explore.py
python explore.py demo
python explore.py call places__find_places city=Munich setting=indoor
python explore.py call calendar__list_events day=2026-10-24
```

- The first command lists all tools from all three servers.
- `demo` runs a fixed flow by hand: weather, then places, then calendar.
- `call` runs a single tool with `key=value` arguments.

### Step 2: Inspect one server (optional)

```bash
npx @modelcontextprotocol/inspector python servers/places_server.py
```

Open the URL it prints, click **Connect**, and try the tools under **Tools**.

### Step 3: Let the LLM orchestrate

Windows (PowerShell):

```powershell
$env:LLM_MODEL = "qwen2.5:3b"
python orchestrator.py
```

Linux (bash):

```bash
export LLM_MODEL=qwen2.5:3b
python orchestrator.py
```

Type a request at the `you>` prompt, for example:

- `Plan my Saturday in Munich. If it rains, pick indoor stuff, and put it in my calendar.`
- `Compare Saturday weather in Munich and Nuremberg and plan a day in the better one.`
- `Plan a day in Berlin.` (there is no data for Berlin, so you can see how errors are handled)

Every tool call and result is printed, so you can follow what the LLM is doing. Type `quit` to exit.

## Configuration

Set these as environment variables before running (`$env:NAME = "value"` in PowerShell, `export NAME=value` in bash):

- `LLM_MODEL`: the Ollama model to use, exactly as shown by `ollama list`
- `LLM_BASE_URL`: the API address (default `http://localhost:11434/v1`, which is Ollama)
- `WEATHER_MOCK=1`: use fake weather instead of the live API, useful offline

To add more places, edit `data/places.json`. To add another MCP server, create it in `servers/` and add it to `servers.json`. The orchestrator picks up its tools automatically.

## Troubleshooting

- **`source` not recognized on Windows**: use `.venv\Scripts\Activate.ps1` instead.
- **`npx` not recognized**: install Node.js and reopen the terminal. This is only needed for the Inspector.
- **Connection refused**: Ollama is not running. Start the Ollama app or run `ollama serve`.
- **Model not found**: run `ollama list` and set `LLM_MODEL` to an exact name from the list.
- **"failed to allocate buffer"**: not enough free RAM. Run `ollama ps`, unload other models with `ollama stop <model>`, close heavy apps, or use a smaller model.
- **"Weather service unreachable"**: no internet connection. Use `WEATHER_MOCK=1`.
- **A server misbehaves**: check its log file in the `logs/` folder.

## Tech stack

Python, FastMCP, Ollama, OpenAI Python client (for Ollama's OpenAI-compatible API), httpx, Open-Meteo API.