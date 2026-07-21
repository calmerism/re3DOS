#!/usr/bin/env bash
# re3DOS build script
# Compiles re3 (GTA III open-source engine) to WebAssembly using Emscripten
# then packages everything for the server.
#
# Usage: ./build/build.sh [options]
#   --skip-emsdk     Don't reinstall Emscripten (use existing)
#   --skip-clone     Don't re-clone re3 (use existing in build/re3/)
#   --skip-librw     Don't re-clone librw (use existing in build/librw/)
#   --assets PATH    Path to your GTA III game files (default: build/gta3-assets/)

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

# ── Colours ──────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${CYAN}[re3DOS]${NC} $*"; }
success() { echo -e "${GREEN}[re3DOS]${NC} $*"; }
warn()    { echo -e "${YELLOW}[re3DOS]${NC} $*"; }
error()   { echo -e "${RED}[re3DOS]${NC} $*"; exit 1; }

# ── Args ─────────────────────────────────────────────────
SKIP_EMSDK=0; SKIP_CLONE=0; SKIP_LIBRW=0
ASSETS_PATH="$SCRIPT_DIR/gta3-assets"

while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-emsdk) SKIP_EMSDK=1 ;;
        --skip-clone) SKIP_CLONE=1 ;;
        --skip-librw) SKIP_LIBRW=1 ;;
        --assets) ASSETS_PATH="$2"; shift ;;
        *) warn "Unknown option: $1" ;;
    esac
    shift
done

# ── Paths ────────────────────────────────────────────────
EMSDK_DIR="$SCRIPT_DIR/emsdk"
RE3_DIR="$SCRIPT_DIR/re3"
LIBRW_DIR="$SCRIPT_DIR/librw"
BUILD_DIR="$SCRIPT_DIR/wasm-build"
OUT_DIR="$ROOT_DIR/re3sky"

EMSDK_VERSION="3.1.56"
RE3_REPO="https://github.com/SugaryHull/re3.git"
LIBRW_REPO="https://github.com/aap/librw.git"

mkdir -p "$BUILD_DIR" "$OUT_DIR" "$ASSETS_PATH"

info "=== re3DOS Build System ==="
info "Root:   $ROOT_DIR"
info "Output: $OUT_DIR"

# ── Step 1: Emscripten ───────────────────────────────────
if [[ $SKIP_EMSDK -eq 0 ]]; then
    if [[ ! -d "$EMSDK_DIR" ]]; then
        info "Cloning Emscripten SDK..."
        git clone https://github.com/emscripten-core/emsdk.git "$EMSDK_DIR"
    fi
    info "Installing Emscripten $EMSDK_VERSION..."
    cd "$EMSDK_DIR"
    ./emsdk install  "$EMSDK_VERSION"
    ./emsdk activate "$EMSDK_VERSION"
fi

EMSDK_ENV="$EMSDK_DIR/emsdk_env.sh"
[[ -f "$EMSDK_ENV" ]] || error "emsdk_env.sh not found at $EMSDK_ENV"
source "$EMSDK_ENV"

EMCC_VER=$(emcc --version 2>&1 | head -1)
success "Emscripten ready: $EMCC_VER"

# ── Step 2: Clone librw ──────────────────────────────────
if [[ $SKIP_LIBRW -eq 0 ]]; then
    if [[ -d "$LIBRW_DIR" ]]; then
        info "Updating librw..."
        cd "$LIBRW_DIR" && git pull --ff-only || warn "librw pull failed, using existing"
    else
        info "Cloning librw..."
        git clone "$LIBRW_REPO" "$LIBRW_DIR"
    fi
fi

# Build librw for WASM
info "Building librw (WebGL3/GLES2 target)..."
mkdir -p "$LIBRW_DIR/build-wasm"
cd "$LIBRW_DIR/build-wasm"
emcmake cmake .. \
    -DCMAKE_BUILD_TYPE=Release \
    -DLIBRW_PLATFORM=GL3 \
    -DLIBRW_GL3_GFXLIB=SDL2 \
    -DCMAKE_C_FLAGS="-sUSE_SDL=2 -DRW_GLES3" \
    -DCMAKE_CXX_FLAGS="-sUSE_SDL=2 -DRW_GLES3" \
    -DCMAKE_INSTALL_PREFIX="$BUILD_DIR/librw-install"
emmake make -j$(nproc 2>/dev/null || sysctl -n hw.logicalcpu 2>/dev/null || echo 4)
emmake make install
success "librw built"

# ── Step 3: Clone re3 ────────────────────────────────────
if [[ $SKIP_CLONE -eq 0 ]]; then
    if [[ -d "$RE3_DIR" ]]; then
        info "Updating re3..."
        cd "$RE3_DIR" && git pull --ff-only || warn "re3 pull failed, using existing"
    else
        info "Cloning re3 (GTA III master branch)..."
        git clone "$RE3_REPO" "$RE3_DIR"
    fi
fi

# Stage optional re3 files that the engine probes at startup. Keep the user's
# original assets intact; only fill in missing files from re3/gamefiles.
if [[ -d "$RE3_DIR/gamefiles" ]]; then
    mkdir -p "$ASSETS_PATH/neo" "$ASSETS_PATH/models" "$ASSETS_PATH/text"
    cp -n "$RE3_DIR/gamefiles/neo/"* "$ASSETS_PATH/neo/" 2>/dev/null || true
    cp -n "$RE3_DIR/gamefiles/models/"* "$ASSETS_PATH/models/" 2>/dev/null || true
    cp -n "$RE3_DIR/gamefiles/TEXT/"*.gxt "$ASSETS_PATH/text/" 2>/dev/null || true
    [[ -f "$ASSETS_PATH/text/JAPANESE.gxt" && ! -f "$ASSETS_PATH/text/japanese.gxt" ]] && \
        cp -n "$ASSETS_PATH/text/JAPANESE.gxt" "$ASSETS_PATH/text/japanese.gxt"
fi

# ── Step 4: Compile re3 → WASM ───────────────────────────
info "Compiling re3 to WebAssembly..."
mkdir -p "$RE3_DIR/build-wasm"
cd "$RE3_DIR/build-wasm"

# Determine available memory. The full browser asset pack needs enough room
# for Emscripten's filesystem plus re3's streaming buffers.
WASM_MEM=$((768 * 1024 * 1024))

emcmake cmake .. \
    -DCMAKE_BUILD_TYPE=Release \
    -DLIBRW_PLATFORM=GL3 \
    -DLIBRW_GL3_GFXLIB=SDL2 \
    -DCMAKE_C_FLAGS="-sUSE_SDL=2 -DRW_GLES3" \
    -DCMAKE_CXX_FLAGS="-sUSE_SDL=2 -DRW_GLES3" \
    -DCMAKE_EXE_LINKER_FLAGS="\
        -s INITIAL_MEMORY=$WASM_MEM \
        -s ALLOW_MEMORY_GROWTH=1 \
        -s MAX_WEBGL_VERSION=2 \
        -s MIN_WEBGL_VERSION=2 \
        -s USE_WEBGL2=1 \
        -s FULL_ES3=1 \
        -s USE_SDL=2 \
        -s ASYNCIFY=1 \
        -s EXPORTED_RUNTIME_METHODS=['ccall','cwrap','FS'] \
        -s FORCE_FILESYSTEM=1 \
        -lidbfs.js \
        --preload-file $ASSETS_PATH@/gamefiles \
        -o $OUT_DIR/game.html"

emmake make -j$(nproc 2>/dev/null || sysctl -n hw.logicalcpu 2>/dev/null || echo 4)

# Copy outputs
cp "$RE3_DIR/build-wasm/src/re3.wasm" "$OUT_DIR/game.wasm" 2>/dev/null || cp "$RE3_DIR/build-wasm"/*.wasm "$OUT_DIR/game.wasm" 2>/dev/null || true
cp "$RE3_DIR/build-wasm/src/re3.js"   "$OUT_DIR/game.js"   2>/dev/null || cp "$RE3_DIR/build-wasm"/*.js   "$OUT_DIR/game.js"   2>/dev/null || true
cp "$RE3_DIR/build-wasm/src/re3.data" "$OUT_DIR/game.data" 2>/dev/null || cp "$RE3_DIR/build-wasm"/*.data "$OUT_DIR/"           2>/dev/null || true
cp "$RE3_DIR/build-wasm/src/re3.worker.js" "$OUT_DIR/re3.worker.js" 2>/dev/null || true

# The generated Emscripten loader still references the original target names.
# Keep the public re3DOS filenames stable for dist/index.html.
if [[ -f "$OUT_DIR/game.js" ]]; then
    perl -0pi -e 's/re3\.wasm/game.wasm/g; s/re3\.data/game.data/g' "$OUT_DIR/game.js"
fi

success "re3 compiled!"

# ── Step 5: Package re3sky folder ────────────────────────
info "Packaging re3sky assets..."
# Copy any remaining static assets
find "$RE3_DIR" -name "*.txd" -o -name "*.col" -o -name "*.dff" 2>/dev/null | head -5 | while read f; do
    cp "$f" "$OUT_DIR/" 2>/dev/null || true
done

success "=== Build complete ==="
echo ""
echo -e "${GREEN}re3sky output:${NC} $OUT_DIR"
echo -e "${GREEN}Start server:${NC}"
echo -e "  cd $ROOT_DIR"
echo -e "  ./.venv/bin/python server.py --re3sky_local re3sky --custom_saves --port 8001"
echo -e "${GREEN}Then open:${NC} http://localhost:8001"
