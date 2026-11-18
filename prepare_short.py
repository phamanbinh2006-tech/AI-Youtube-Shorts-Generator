"""Export a timestamped transcript using the Shorts repo, without an LLM API.

Place beside main.py. Run with the repo's .venv Python.
Default source is a NASA educational video, for PRIVATE pipeline testing.
Its credited third-party music is NOT cleared for republication.
An optional local video path can replace the default source.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import urllib.request

SOURCE_PAGE = "https://svs.gsfc.nasa.gov/14938/"
SOURCE_URL = "https://svs.gsfc.nasa.gov/vis/a010000/a014900/a014938/14938_Artemis_Sci_Wright_A2Sim_720.mp4"


def download(url, destination):
    if destination.is_file() and destination.stat().st_size > 0:
        print("Using existing video:", destination, flush=True)
        return
    partial = destination.with_suffix(".download")
    request = urllib.request.Request(url, headers={"User-Agent": "ShortsLocalDemo/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            total = int(response.headers.get("Content-Length", "0"))
            count, last_report = 0, -1
            with partial.open("wb") as output:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    count += len(chunk)
                    mb = count // (1024 * 1024)
                    if mb // 10 != last_report:
                        last_report = mb // 10
                        print(f"Downloaded {mb} MB", flush=True)
            if not count or (total and count != total):
                raise RuntimeError("Incomplete download. Run this command again.")
        partial.replace(destination)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", nargs="?", help="Optional existing local video")
    parser.add_argument("--language", default=None, help="en, vi; default auto-detect")
    parser.add_argument("--model", choices=["tiny", "base", "small", "medium"], default="base")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    if not (root / "shorts_generator" / "local" / "transcriber.py").is_file():
        raise RuntimeError("Put prepare_short.py in the repo folder, beside main.py.")
    workspace = root.parent
    cache = workspace / "Cache"
    temp = workspace / "Temp"
    for path in [cache, temp, root / "input", root / "output"]:
        path.mkdir(parents=True, exist_ok=True)
    for key, value in {
        "TEMP": temp, "TMP": temp, "TMPDIR": temp,
        "HF_HOME": cache / "huggingface",
        "HF_HUB_CACHE": cache / "huggingface" / "hub",
        "XDG_CACHE_HOME": cache, "PIP_CACHE_DIR": cache / "pip",
        "TORCH_HOME": cache / "torch",
    }.items():
        os.environ[key] = str(value)
    os.environ["LOCAL_WHISPER_DEVICE"] = "cpu"
    os.environ["LOCAL_WHISPER_MODEL"] = args.model
    os.environ["LOCAL_WHISPER_VAD_FILTER"] = "false"
    if not shutil.which("ffmpeg"):
        raise RuntimeError("FFmpeg not found. Reopen PowerShell after installing it.")
    if args.video:
        media = Path(args.video).expanduser().resolve()
        if not media.is_file():
            raise FileNotFoundError(media)
    else:
        media = root / "input" / "nasa_lunar_flyby_720.mp4"
        print("NASA source: private pipeline test; original music not cleared for posting.", flush=True)
        download(SOURCE_URL, media)
    stat = media.stat()
    identity = f"{media}|{stat.st_size}|{stat.st_mtime_ns}|{args.model}|{args.language}"
    tag = hashlib.sha256(identity.encode()).hexdigest()[:12]
    output = root / "output" / ("transcript_" + tag)
    output.mkdir(parents=True, exist_ok=True)
    os.environ["LOCAL_OUTPUT_DIR"] = str(output)
    os.chdir(root)
    print("Transcribing on CPU. First run downloads the Whisper model to:", cache, flush=True)
    print("Processing may take several minutes; the repo reports when finished.", flush=True)
    from shorts_generator.local.transcriber import transcribe_local
    transcript = transcribe_local(str(media), language=args.language or ("en" if not args.video else None))
    if not transcript.get("segments"):
        raise RuntimeError("No speech detected. No usable transcript was produced.")
    document = {
        "source_file": str(media),
        "source_page": SOURCE_PAGE if not args.video else None,
        "usage_note": "Private test. Original third-party music not cleared for posting." if not args.video else "User-supplied video; verify reuse rights before posting.",
        "whisper_model": args.model,
        **transcript,
    }
    target = output / "transcript_for_chat.json"
    target.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nDONE. Upload this file to the chat:\n" + str(target), flush=True)
    print("No paid LLM API was called. No video was posted.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped. Run again when ready.", file=sys.stderr)
        sys.exit(130)
    except Exception as error:
        print(f"\nERROR: {error}", file=sys.stderr)
        sys.exit(1)
