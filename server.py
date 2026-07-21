import os
import sys
import asyncio
import argparse
import hashlib
from typing import Optional
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
import additions.saves as saves
from additions.auth import BasicAuthMiddleware
from additions.cache import proxy_and_cache, get_local_file
from additions.packed import init_packed_archive, get_packed_file, is_initialized as packed_is_initialized

# Add utils path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'utils'))

parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, default=8001)
parser.add_argument("--custom_saves", action="store_true")
parser.add_argument("--login", type=str)
parser.add_argument("--password", type=str)
parser.add_argument("--re3sky_local", type=str, nargs='?', const='re3sky', default=None,
                    help="Serve re3sky from local directory instead of proxy. Optionally specify path (default: re3sky/)")
parser.add_argument("--re3br_local", type=str, nargs='?', const='re3br', default=None,
                    help="Serve re3br from local directory instead of proxy. Optionally specify path (default: re3br/)")
parser.add_argument("--re3sky_url", type=str, default="https://cdn.dos.zone/re3sky/", help="Custom re3sky proxy URL")
parser.add_argument("--re3br_url", type=str, default="https://br.cdn.dos.zone/re3sky/", help="Custom re3br proxy URL")
parser.add_argument("--re3sky_cache", action="store_true", help="Cache re3sky files locally.")
parser.add_argument("--re3br_cache", action="store_true", help="Cache re3br files locally.")
parser.add_argument("--packed", type=str, nargs='?', const='re3dos.bin', default=None,
                    help="Serve re3sky/ and re3br/ from packed archive. Can be a local file path or URL. "
                         "If no value specified, uses 're3dos.bin'.")
parser.add_argument("--unpacked", type=str, default=None,
                    help="Unpack archive to local folders and serve from there.")
parser.add_argument("--pack", type=str, default=None,
                    help="Pack a folder to {hash}.bin archive.")
args = parser.parse_args()


def _md5_hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


def _is_url(path: str) -> bool:
    return path.startswith("http://") or path.startswith("https://")


def _is_md5_hash(text: str) -> bool:
    if len(text) != 32:
        return False
    try:
        int(text, 16)
        return True
    except ValueError:
        return False


def _get_unpacked_dir(source: str) -> str:
    if _is_md5_hash(source):
        return os.path.join("unpacked", source.lower())
    source_hash = _md5_hash(source)
    return os.path.join("unpacked", source_hash)


def _check_unpacked_exists(unpacked_dir: str) -> bool:
    if not os.path.isdir(unpacked_dir):
        return False
    for subdir in ["re3sky", "re3br"]:
        subdir_path = os.path.join(unpacked_dir, subdir)
        if os.path.isdir(subdir_path):
            for root, dirs, files in os.walk(subdir_path):
                if files:
                    return True
    return False


async def _unpack_from_url(url: str, output_dir: str) -> bool:
    try:
        from utils.downloader_brotli import download_and_unpack_async
        print(f"Streaming and unpacking from URL: {url}")
        print(f"Output directory: {output_dir}")
        await download_and_unpack_async(url, output_dir)
        return True
    except Exception as e:
        print(f"Error unpacking from URL: {e}")
        return False


async def _unpack_from_file(file_path: str, output_dir: str) -> bool:
    try:
        from utils.packer_brotli import unpack_file
        print(f"Unpacking local file: {file_path}")
        print(f"Output directory: {output_dir}")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, unpack_file, file_path, output_dir)
        return True
    except Exception as e:
        print(f"Error unpacking file: {e}")
        return False


def pack_source(source: str) -> Optional[str]:
    from utils.packer_brotli import pack_folder, add_folder

    if _is_md5_hash(source):
        folder_path = os.path.join("unpacked", source.lower())
        output_hash = source.lower()
    else:
        folder_path = source.rstrip('/\\')
        output_hash = _md5_hash(os.path.basename(folder_path))

    if not os.path.isdir(folder_path):
        print(f"Error: Folder not found: {folder_path}")
        return None

    output_file = f"{output_hash}.bin"
    subdirs = sorted([d for d in os.listdir(folder_path)
                     if os.path.isdir(os.path.join(folder_path, d)) and not d.startswith('.')])

    if not subdirs:
        print(f"Error: No subdirectories found in {folder_path}")
        return None

    print(f"Packing {len(subdirs)} subfolders from {folder_path} to {output_file}")
    first_subdir = os.path.join(folder_path, subdirs[0])
    print(f"=== Creating archive from {subdirs[0]} ===")
    pack_folder(first_subdir, output_file)

    for subdir_name in subdirs[1:]:
        subdir_path = os.path.join(folder_path, subdir_name)
        print(f"\n=== Adding {subdir_name} ===")
        add_folder(output_file, subdir_path)

    final_size = os.path.getsize(output_file)
    print(f"\n=== Packing complete ===")
    print(f"Output: {output_file} ({final_size:,} bytes)")
    return output_file


async def setup_unpacked(source: str) -> tuple:
    unpacked_dir = _get_unpacked_dir(source)
    is_hash_only = _is_md5_hash(source)

    if _check_unpacked_exists(unpacked_dir):
        print(f"Using existing unpacked directory: {unpacked_dir}")
    elif is_hash_only:
        print(f"Error: Unpacked folder not found for hash: {source}")
        return None, None
    else:
        print(f"Unpacking to: {unpacked_dir}")
        os.makedirs(unpacked_dir, exist_ok=True)
        if _is_url(source):
            success = await _unpack_from_url(source, unpacked_dir)
        else:
            if not os.path.isfile(source):
                print(f"Error: Archive file not found: {source}")
                return None, None
            success = await _unpack_from_file(source, unpacked_dir)
        if not success:
            return None, None

    re3sky_path = None
    re3br_path = None

    re3sky_candidate = os.path.join(unpacked_dir, "re3sky")
    if os.path.isdir(re3sky_candidate):
        re3sky_path = re3sky_candidate
        print(f"  re3sky: {re3sky_path}")

    re3br_candidate = os.path.join(unpacked_dir, "re3br")
    if os.path.isdir(re3br_candidate):
        re3br_path = re3br_candidate
        print(f"  re3br: {re3br_path}")

    return re3sky_path, re3br_path


app = FastAPI()

@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

if args.login and args.password:
    app.add_middleware(BasicAuthMiddleware, username=args.login, password=args.password)

if args.custom_saves:
    app.include_router(saves.router)

from pydantic import BaseModel
class LogPayload(BaseModel):
    type: str
    message: str

@app.post("/log")
async def receive_log(payload: LogPayload):
    print(f"\n[BROWSER-{payload.type.upper()}] {payload.message}\n")
    return {"status": "ok"}

RE3SKY_BASE_URL = args.re3sky_url
RE3BR_BASE_URL = args.re3br_url

RE3SKY_LOCAL_PATH = args.re3sky_local
RE3BR_LOCAL_PATH = args.re3br_local


def request_to_url(request: Request, path: str, base_url: str):
    query_string = str(request.url.query) if request.url.query else ""
    url = f"{base_url}{path}"
    if query_string:
        url = f"{url}?{query_string}"
    return url


@app.api_route("/re3sky/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def re3_sky_proxy(request: Request, path: str):
    if args.packed and packed_is_initialized():
        packed_path = f"re3sky/{path}"
        if response := await get_packed_file(packed_path, request):
            return response

    if RE3SKY_LOCAL_PATH:
        local_path = os.path.join(RE3SKY_LOCAL_PATH, path)
        if response := get_local_file(local_path, request):
            return response
        if args.re3sky_local is not None or args.unpacked:
            raise HTTPException(status_code=404, detail="File not found")

    url = request_to_url(request, path, RE3SKY_BASE_URL)
    if args.re3sky_cache:
        cache_path = os.path.join("re3sky", path)
        return await proxy_and_cache(request, url, cache_path)
    return await proxy_and_cache(request, url, disable_cache=True)


@app.api_route("/re3br/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def re3_br_proxy(request: Request, path: str):
    if args.packed and packed_is_initialized():
        packed_path = f"re3br/{path}"
        if response := await get_packed_file(packed_path, request):
            return response

    if RE3BR_LOCAL_PATH:
        local_path = os.path.join(RE3BR_LOCAL_PATH, path)
        if response := get_local_file(local_path, request):
            return response
        if args.re3br_local is not None or args.unpacked:
            raise HTTPException(status_code=404, detail="File not found")

    url = request_to_url(request, path, RE3BR_BASE_URL)
    if args.re3br_cache:
        cache_path = os.path.join("re3br", path)
        return await proxy_and_cache(request, url, cache_path)
    return await proxy_and_cache(request, url, disable_cache=True)


@app.api_route("/", methods=["GET", "HEAD"])
async def read_index(request: Request = None):
    if os.path.exists("dist/index.html"):
        with open("dist/index.html", "r", encoding="utf-8") as f:
            content = f.read()

        custom_saves_val = "1" if args.custom_saves else "0"
        content = content.replace(
            'new URLSearchParams(window.location.search).get("custom_saves") === "1"',
            f'"{custom_saves_val}" === "1"'
        )

        return Response(content, media_type="text/html", headers={
            "Cross-Origin-Opener-Policy": "same-origin",
            "Cross-Origin-Embedder-Policy": "require-corp"
        })
    return Response("index.html not found", status_code=404)


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def root_fallback_proxy(request: Request, path: str):
    if not path or path == "":
        return await read_index(request)

    dist_path = os.path.join("dist", path)
    if response := get_local_file(dist_path, request):
        return response

    if RE3SKY_LOCAL_PATH:
        local_path = os.path.join(RE3SKY_LOCAL_PATH, path)
        if response := get_local_file(local_path, request):
            return response
        if args.re3sky_local is not None or args.unpacked:
            raise HTTPException(status_code=404, detail="File not found")

    url = request_to_url(request, path, RE3SKY_BASE_URL)
    if args.re3sky_cache:
        cache_path = os.path.join("re3sky", path)
        return await proxy_and_cache(request, url, cache_path)
    return await proxy_and_cache(request, url, disable_cache=True)


async def init_server():
    global RE3SKY_LOCAL_PATH, RE3BR_LOCAL_PATH

    if args.unpacked:
        re3sky_path, re3br_path = await setup_unpacked(args.unpacked)
        if re3sky_path:
            RE3SKY_LOCAL_PATH = re3sky_path
        if re3br_path:
            RE3BR_LOCAL_PATH = re3br_path

    if args.packed:
        result = await init_packed_archive(args.packed)
        if result is None:
            print(f"Warning: Failed to initialize packed archive from: {args.packed}")


def start_server(app=app, host="0.0.0.0", port=args.port):
    import uvicorn
    if args.packed or args.unpacked:
        asyncio.run(init_server())
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    if args.pack:
        print(f"Pack mode: {args.pack}")
        packed_file = pack_source(args.pack)
        if packed_file:
            print(f"\nUsing packed archive: {packed_file}")
            args.packed = packed_file
        else:
            print("Packing failed, exiting.")
            sys.exit(1)

    print(f"Starting re3DOS server on http://localhost:{args.port}")

    if args.unpacked:
        print(f"unpacked mode: {args.unpacked}")
    elif args.packed:
        print(f"packed: {args.packed}")
    else:
        re3sky_mode = 'local' if args.re3sky_local else 'proxy'
        re3br_mode = 'local' if args.re3br_local else 'proxy'
        re3sky_info = args.re3sky_local or RE3SKY_BASE_URL
        re3br_info = args.re3br_local or RE3BR_BASE_URL
        print(f"re3sky: {re3sky_mode} ({re3sky_info})")
        print(f"re3br: {re3br_mode} ({re3br_info})")

    start_server()
