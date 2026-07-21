# re3DOS Build Guide

A self-hosted browser port of **GTA III**, powered by [re3](https://github.com/halisker/re3) compiled to WebAssembly.

---

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Git | Any | `brew install git` |
| CMake | 3.20+ | `brew install cmake` |
| Python 3.11+ | Any | `brew install python@3.14` |
| Node.js | 18+ | `brew install node` *(optional, for localtunnel)* |

You do **not** need to install Emscripten manually — the build script does it.

---

## Build Steps

### 1. Set up Python venv & install server deps

```bash
cd /Volumes/SSD/re3DOS
python3.14 -m venv .venv
./.venv/bin/python -m ensurepip --default-pip
./.venv/bin/python -m pip install -r requirements.txt
```

### 2. Provide GTA III game files

You need a **legal PC copy** of GTA III (not the Definitive Edition). Copy these folders into `build/gta3-assets/`:

```
build/gta3-assets/
  models/
    gta3.img
    gta3.dir
    *.txd
    *.dff
    ...
  audio/
    sfx.raw
    ...
  data/
    default.dat
    gta3.dat
    ...
  text/
    english.gxt
    ...
```

### 3. Run the build script

```bash
chmod +x build/build.sh
./build/build.sh
```

**What it does:**
1. Clones and installs Emscripten SDK 3.1.56 into `build/emsdk/`
2. Clones and compiles **librw** (rendering library) to WASM/WebGL2
3. Clones and compiles **re3** to WebAssembly with game assets embedded
4. Outputs `game.wasm`, `game.js`, and `game.data` into `re3sky/`

**Time:** ~20–40 min on first run (mostly downloading + compiling).

**Options:**
```bash
./build/build.sh --skip-emsdk     # Don't reinstall Emscripten
./build/build.sh --skip-clone     # Don't re-clone re3
./build/build.sh --assets /path   # Custom game assets path
```

### 4. Start the server

```bash
./.venv/bin/python server.py --re3sky_local re3sky --custom_saves --port 8001
```

Open **http://localhost:8001**

---

## Serving with packed archive

After building, you can pack everything into a single `.bin` file for efficient serving:

```bash
# Pack re3sky/ folder into re3dos.bin
./.venv/bin/python server.py --pack re3sky

# Then serve from packed archive
./.venv/bin/python server.py --packed re3dos.bin --custom_saves
```

---

## Server options

| Flag | Description |
|------|-------------|
| `--port 8001` | Change port (default: 8001) |
| `--re3sky_local re3sky` | Serve from local `re3sky/` folder |
| `--packed re3dos.bin` | Serve from packed archive |
| `--custom_saves` | Enable local cloud saves |
| `--re3sky_cache` | Cache proxied files locally |
| `--login user --password pass` | Password protect the server |

---

## Troubleshooting

**`emcc: command not found`** — The build script didn't source the emsdk env. Run:
```bash
source build/emsdk/emsdk_env.sh
```

**Link errors about missing symbols** — Check that librw was built with the same Emscripten version as re3. Run with `--skip-emsdk` and `--skip-librw=0` to rebuild librw only.

**`PTHREAD_POOL_SIZE` error in browser** — Your server needs these HTTP headers (already set by server.py):
- `Cross-Origin-Opener-Policy: same-origin`
- `Cross-Origin-Embedder-Policy: require-corp`

**Black screen / no audio** — The game assets may not be correctly placed. Check that `build/gta3-assets/models/gta3.img` exists before building.

**Memory error (OOM)** — Increase memory in `build.sh`: change `512 * 1024 * 1024` to `768 * 1024 * 1024`.

---

## Architecture

```
re3DOS/
├── server.py          ← FastAPI server (proxies/serves re3sky assets)
├── additions/         ← Auth, caching, packed archive, saves middleware
├── utils/             ← Packer/unpacker tools (Brotli)
├── dist/              ← Frontend (HTML/JS UI)
│   ├── index.html     ← Start screen + config panel
│   └── cover.jpg      ← Background art
├── re3sky/            ← WASM output (game.wasm, game.js, game.data)
│   └── ...            ← Created by build.sh
└── build/             ← Build pipeline
    ├── build.sh       ← Main build script
    ├── README.md      ← This file
    ├── emsdk/         ← Emscripten SDK (auto-cloned)
    ├── re3/           ← re3 source (auto-cloned)
    ├── librw/         ← librw source (auto-cloned)
    └── gta3-assets/   ← Your game files (you provide these)
```

---

## Legal

- The **re3 engine** is open source (reverse-engineered) and does not contain any Rockstar Games code
- **Game assets** (models, audio, textures) from GTA III are copyrighted by Rockstar/Take-Two
- You must own the original game to use your own assets
- re3DOS does **not** distribute any copyrighted assets
