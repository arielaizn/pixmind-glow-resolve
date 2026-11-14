#!/usr/bin/env python3
"""
Hebrew Auto Captions for After Effects
======================================
Video/audio -> Groq transcription -> captions JSON.

Rules:
  - one line per caption
  - up to 3 words per caption
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import subprocess
import sys
import tempfile
import shutil

GROQ_TRANSCRIPTIONS_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
DEFAULT_MODEL = "whisper-large-v3-turbo"
ENDERS = (".", "?", "!", "…", ":", "؟", "。", "؛")
GROQ_SUPPORTED_EXTENSIONS = {".flac", ".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".ogg", ".opus", ".wav", ".webm"}
GROQ_CONTENT_TYPES = {
    ".flac": "audio/flac",
    ".mp3": "audio/mpeg",
    ".mp4": "video/mp4",
    ".mpeg": "video/mpeg",
    ".mpga": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".opus": "audio/opus",
    ".wav": "audio/wav",
    ".webm": "audio/webm",
}


def die(msg: str, code: int = 1) -> None:
    print("ERROR: " + msg, file=sys.stderr)
    sys.exit(code)


def curl_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def find_ffmpeg() -> str:
    candidates = (
        os.environ.get("FFMPEG_PATH", ""),
        "/opt/homebrew/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
        "/opt/homebrew/opt/ffmpeg/bin/ffmpeg",
        "/usr/local/opt/ffmpeg/bin/ffmpeg",
        "ffmpeg",
    )
    for candidate in candidates:
        if not candidate:
            continue
        if os.path.isabs(candidate) and os.path.exists(candidate):
            return candidate
        if not os.path.isabs(candidate):
            path = shutil.which(candidate)
            if path:
                return path
    die("ffmpeg not found. Install with: brew install ffmpeg, or set FFMPEG_PATH=/path/to/ffmpeg")


def extract_audio(source: str, audio_path: str, in_ms: int, out_ms: int) -> None:
    cmd = [find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y"]
    if in_ms > 0:
        cmd += ["-ss", f"{in_ms / 1000.0:.3f}"]
    cmd += ["-i", source]
    if out_ms > in_ms:
        cmd += ["-t", f"{(out_ms - max(in_ms, 0)) / 1000.0:.3f}"]
    cmd += ["-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000", "-c:a", "aac", "-b:a", "48k", audio_path]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        die("audio extraction failed: " + detail[-1200:])
    if not os.path.exists(audio_path) or os.path.getsize(audio_path) == 0:
        die("audio extraction failed: empty output file")


def groq_upload_metadata(path: str) -> tuple[str, str]:
    base = os.path.basename(path)
    stem, ext = os.path.splitext(base)
    ext = ext.lower()

    if ext in GROQ_SUPPORTED_EXTENSIONS:
        return base, GROQ_CONTENT_TYPES.get(ext) or mimetypes.guess_type(path)[0] or "application/octet-stream"

    # Groq validates the multipart filename extension. Common AE/iPhone .mov
    # files are QuickTime/MP4-family containers, so submit them as .mp4 without
    # changing the local source file.
    safe_stem = stem or "audio"
    return safe_stem + ".mp4", "video/mp4"


def groq_transcribe(audio_path: str, api_key: str, model: str, lang: str) -> dict:
    curl = "/usr/bin/curl" if os.path.exists("/usr/bin/curl") else "curl"
    upload_name, content_type = groq_upload_metadata(audio_path)
    config = "\n".join(
        [
            "silent",
            "show-error",
            "fail-with-body",
            "location",
            "request = " + curl_quote("POST"),
            "url = " + curl_quote(GROQ_TRANSCRIPTIONS_URL),
            "header = " + curl_quote("Authorization: Bearer " + api_key),
            "header = " + curl_quote("User-Agent: HebrewAutoCaptions/1.8.0"),
            "form = " + curl_quote(f"file=@{audio_path};filename={upload_name};type={content_type}"),
            "form = " + curl_quote(f"model={model}"),
            "form = " + curl_quote(f"language={lang}"),
            "form = " + curl_quote("response_format=verbose_json"),
            "form = " + curl_quote("temperature=0"),
            "form = " + curl_quote("timestamp_granularities[]=word"),
            "max-time = 300",
        ]
    )

    proc = subprocess.run(
        [curl, "--config", "-"],
        input=config,
        capture_output=True,
        text=True,
        timeout=330,
    )
    body = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()

    if proc.returncode != 0:
        detail = body or stderr or f"curl exited with code {proc.returncode}"
        die("Groq API request failed: " + detail[-1600:])

    try:
        return json.loads(body)
    except json.JSONDecodeError:
        die("Groq API returned non-JSON response: " + body[-1600:])


def words_from_groq(data: dict) -> list[tuple[str, int, int]]:
    words: list[tuple[str, int, int]] = []

    for item in data.get("words") or []:
        text = str(item.get("word") or item.get("text") or "").strip()
        if not text:
            continue
        start = int(float(item.get("start", 0)) * 1000)
        end = int(float(item.get("end", 0)) * 1000)
        words.append((text, start, max(end, start + 250)))

    if words:
        return words

    for segment in data.get("segments") or []:
        text = str(segment.get("text") or "").strip()
        parts = [p for p in text.split() if p]
        if not parts:
            continue
        start_ms = int(float(segment.get("start", 0)) * 1000)
        end_ms = int(float(segment.get("end", 0)) * 1000)
        span = max(end_ms - start_ms, len(parts) * 300)
        for i, part in enumerate(parts):
            w_start = start_ms + int(span * (i / len(parts)))
            w_end = start_ms + int(span * ((i + 1) / len(parts)))
            words.append((part, w_start, max(w_end, w_start + 250)))

    if words:
        return words

    text = str(data.get("text") or "").strip()
    parts = [p for p in text.split() if p]
    if not parts:
        die("Groq returned no transcript text.")
    for i, part in enumerate(parts):
        words.append((part, i * 350, (i + 1) * 350))
    return words


def filter_words_to_source_range(
    words: list[tuple[str, int, int]],
    in_ms: int,
    out_ms: int,
) -> list[tuple[str, int, int]]:
    if in_ms <= 0 and out_ms <= in_ms:
        return words

    filtered: list[tuple[str, int, int]] = []
    for text, start, end in words:
        if out_ms > in_ms and start >= out_ms:
            continue
        if end <= in_ms:
            continue
        filtered.append((text, max(start, in_ms), end if out_ms <= in_ms else min(end, out_ms)))
    return filtered


def group_words(words: list[tuple[str, int, int]], max_words: int, gap_ms: int) -> list[dict]:
    chunks: list[list[tuple[str, int, int]]] = []
    current: list[tuple[str, int, int]] = []

    for i, (text, start, end) in enumerate(words):
        current.append((text, start, end))
        should_break = len(current) >= max_words or text.endswith(ENDERS)
        if not should_break and i + 1 < len(words):
            if words[i + 1][1] - end > gap_ms:
                should_break = True
        if should_break:
            chunks.append(current)
            current = []

    if current:
        chunks.append(current)

    captions: list[dict] = []
    for chunk in chunks:
        parts = [w[0].replace("\n", " ").strip() for w in chunk if w[0].strip()]
        if not parts:
            continue
        start_ms = chunk[0][1]
        end_ms = max(chunk[-1][2], start_ms + 250)
        captions.append({"text": " ".join(parts[:max_words]), "start_ms": start_ms, "end_ms": end_ms})

    for i in range(1, len(captions)):
        if captions[i]["start_ms"] < captions[i - 1]["end_ms"]:
            captions[i]["start_ms"] = captions[i - 1]["end_ms"]
        if captions[i]["end_ms"] <= captions[i]["start_ms"]:
            captions[i]["end_ms"] = captions[i]["start_ms"] + 250

    return [c for c in captions if c["text"]]


def apply_offset(captions: list[dict], offset_ms: int) -> list[dict]:
    return [
        {"text": cap["text"], "start_ms": cap["start_ms"] + offset_ms, "end_ms": cap["end_ms"] + offset_ms}
        for cap in captions
    ]


def srt_time(ms: int) -> str:
    ms = max(0, int(ms))
    hours, rem = divmod(ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    seconds, millis = divmod(rem, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"


def write_srt(path: str, captions: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for idx, cap in enumerate(captions, start=1):
            f.write(str(idx) + "\n")
            f.write(f"{srt_time(cap['start_ms'])} --> {srt_time(cap['end_ms'])}\n")
            f.write(str(cap["text"]).replace("\n", " ").strip() + "\n\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Hebrew auto-captions transcription for AE using Groq")
    parser.add_argument("source", help="Video or audio file path")
    parser.add_argument("--lang", default="he")
    parser.add_argument("--max-words", type=int, default=3)
    parser.add_argument("--gap-ms", type=int, default=700)
    parser.add_argument("--out", default=None)
    parser.add_argument("--srt-out", default=None)
    parser.add_argument("--groq-model", default=DEFAULT_MODEL)
    parser.add_argument("--offset-ms", type=int, default=0, help="Add to all times (layer start)")
    parser.add_argument("--in-ms", type=int, default=0, help="Trim source from this ms")
    parser.add_argument("--out-ms", type=int, default=-1, help="Trim source until this ms (-1=end)")
    parser.add_argument("--keep-work", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if not os.path.exists(args.source):
        die("source not found: " + args.source)
    if args.max_words < 1 or args.max_words > 3:
        die("--max-words must be between 1 and 3")

    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        die("GROQ_API_KEY is missing. Enter it in the panel or set the environment variable.")

    print(f"[transcribe] provider=groq/curl model={args.groq_model} lang={args.lang} max_words={args.max_words}")

    workdir = tempfile.mkdtemp(prefix="ae_he_caps_")
    try:
        audio = os.path.join(workdir, "audio.m4a")
        print("[transcribe] extracting audio with ffmpeg")
        extract_audio(args.source, audio, args.in_ms, args.out_ms)
        print(f"[transcribe] uploading audio={os.path.getsize(audio)} bytes")
        data = groq_transcribe(audio, api_key, args.groq_model, args.lang)
        words = words_from_groq(data)
        if args.in_ms > 0:
            words = [(text, start + args.in_ms, end + args.in_ms) for text, start, end in words]
        captions = apply_offset(group_words(words, args.max_words, args.gap_ms), args.offset_ms)
    finally:
        if not args.keep_work:
            shutil.rmtree(workdir, ignore_errors=True)

    out_path = args.out or (os.path.splitext(os.path.abspath(args.source))[0] + ".captions.json")
    payload = {
        "source": os.path.abspath(args.source),
        "provider": "groq",
        "model": args.groq_model,
        "lang": args.lang,
        "max_words": args.max_words,
        "offset_ms": args.offset_ms,
        "captions": captions,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    if args.srt_out:
        write_srt(args.srt_out, captions)

    print(f"[transcribe] {len(captions)} captions (<= {args.max_words} words, 1 line each)")
    print(out_path)
    if args.srt_out:
        print(args.srt_out)


if __name__ == "__main__":
    main()
