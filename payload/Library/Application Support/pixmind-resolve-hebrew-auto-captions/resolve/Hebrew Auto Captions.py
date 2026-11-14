#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hebrew Auto Captions for DaVinci Resolve.

Run from:
  Workspace -> Scripts -> Edit -> Hebrew Auto Captions
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import traceback


PLUGIN_ROOT = "/Library/Application Support/pixmind-resolve-hebrew-auto-captions"
HELPER = os.path.join(PLUGIN_ROOT, "scripts", "transcribe.py")
MAX_WORDS = 3


def _get_resolve():
    try:
        return resolve
    except NameError:
        pass
    try:
        import DaVinciResolveScript as dvr_script
        return dvr_script.scriptapp("Resolve")
    except Exception:
        return None


def _get_fusion(resolve_app):
    try:
        return fusion
    except NameError:
        pass
    try:
        return resolve_app.Fusion()
    except Exception:
        return None


def _get_bmd():
    try:
        return bmd
    except NameError:
        pass
    try:
        import BlackmagicFusion as bmd_module
        return bmd_module
    except Exception:
        return None


RESOLVE = _get_resolve()
FUSION = _get_fusion(RESOLVE) if RESOLVE else None
BMD = _get_bmd()


def find_python():
    candidates = [
        "/Library/Frameworks/Python.framework/Versions/3.14/bin/python3",
        "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3",
        "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3",
        "/opt/homebrew/bin/python3",
        "/usr/local/bin/python3",
        "/usr/bin/python3",
        sys.executable,
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return "python3"


def parse_fps(value):
    try:
        return float(str(value).replace(",", "."))
    except Exception:
        return 25.0


def timecode_to_frames(timecode, fps):
    if not timecode:
        return 0
    parts = str(timecode).split(":")
    if len(parts) != 4:
        return 0
    h, m, s, f = [int(float(p)) for p in parts]
    return int(round((((h * 60 + m) * 60) + s) * fps + f))


def timeline_context():
    if not RESOLVE:
        raise RuntimeError("Could not connect to DaVinci Resolve scripting API.")

    pm = RESOLVE.GetProjectManager()
    project = pm.GetCurrentProject() if pm else None
    if not project:
        raise RuntimeError("No current Resolve project.")

    timeline = project.GetCurrentTimeline()
    if not timeline:
        raise RuntimeError("No current timeline.")

    item = timeline.GetCurrentVideoItem()
    if not item:
        raise RuntimeError("Move the playhead over the video clip you want to caption.")

    media_item = item.GetMediaPoolItem()
    if not media_item:
        raise RuntimeError("Current timeline item has no media pool source.")

    props = media_item.GetClipProperty() or {}
    source = props.get("File Path") or props.get("FilePath") or props.get("File Name") or ""
    if not source or not os.path.exists(source):
        raise RuntimeError("Could not resolve source file path for: " + item.GetName())

    fps = parse_fps(timeline.GetSetting("timelineFrameRate") or project.GetSetting("timelineFrameRate"))
    timeline_start = int(timeline.GetStartFrame() or 0)
    clip_start = int(round(item.GetStart(False)))
    clip_end = int(round(item.GetEnd(False)))
    source_start = int(item.GetSourceStartFrame() or 0)
    duration_frames = max(1, clip_end - clip_start)

    return {
        "project": project,
        "timeline": timeline,
        "media_pool": project.GetMediaPool(),
        "source": source,
        "fps": fps,
        "in_ms": int(round((source_start / fps) * 1000)),
        "out_ms": int(round(((source_start + duration_frames) / fps) * 1000)),
        "offset_ms": int(round(((clip_start - timeline_start) / fps) * 1000)),
        "clip_name": item.GetName(),
        "timeline_name": timeline.GetName(),
    }


def run_transcription(api_key, status_cb):
    if not api_key.strip():
        raise RuntimeError("Groq API key is required.")
    if not os.path.exists(HELPER):
        raise RuntimeError("Missing helper: " + HELPER)

    ctx = timeline_context()
    out_dir = os.path.join(os.path.expanduser("~/Movies"), "Resolve Hebrew Auto Captions")
    os.makedirs(out_dir, exist_ok=True)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    safe_name = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in ctx["clip_name"])[:60]
    json_path = os.path.join(out_dir, f"{safe_name}-{stamp}.captions.json")
    srt_path = os.path.join(out_dir, f"{safe_name}-{stamp}.srt")

    env = os.environ.copy()
    env["GROQ_API_KEY"] = api_key.strip()

    cmd = [
        find_python(),
        HELPER,
        ctx["source"],
        "--lang",
        "he",
        "--max-words",
        str(MAX_WORDS),
        "--offset-ms",
        str(ctx["offset_ms"]),
        "--in-ms",
        str(ctx["in_ms"]),
        "--out-ms",
        str(ctx["out_ms"]),
        "--out",
        json_path,
        "--srt-out",
        srt_path,
    ]

    status_cb("Transcribing with Groq...")
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=600)
    output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    if proc.returncode != 0:
        raise RuntimeError(output[-2400:] or f"transcribe.py failed with exit code {proc.returncode}")

    if not os.path.exists(srt_path):
        raise RuntimeError("SRT was not created.\n" + output[-1200:])

    imported = None
    try:
        imported = ctx["media_pool"].ImportMedia([srt_path]) if ctx["media_pool"] else None
    except Exception:
        imported = None

    return {
        "srt": srt_path,
        "json": json_path,
        "imported": bool(imported),
        "clip": ctx["clip_name"],
        "timeline": ctx["timeline_name"],
        "output": output,
    }


def run_ui():
    if not FUSION:
        print("Hebrew Auto Captions: Fusion UI Manager is unavailable.")
        return

    ui = FUSION.UIManager
    disp = BMD.UIDispatcher(ui) if BMD else FUSION.UIDispatcher(ui)

    win = disp.AddWindow(
        {
            "ID": "ResolveHebrewAutoCaptions",
            "WindowTitle": "Hebrew Auto Captions",
            "Geometry": [240, 220, 520, 310],
        },
        [
            ui.VGroup(
                {"Spacing": 8, "Margin": 14},
                [
                    ui.Label({"Text": "Hebrew Auto Captions", "StyleSheet": "font-size:20px;font-weight:700;"}),
                    ui.Label({"Text": "Playhead must be over the video clip to caption."}),
                    ui.Label({"Text": "Groq API Key"}),
                    ui.LineEdit({"ID": "ApiKey", "EchoMode": "Password", "PlaceholderText": "not saved to disk"}),
                    ui.HGroup(
                        {"Spacing": 8},
                        [
                            ui.Button({"ID": "Run", "Text": "Create SRT"}),
                            ui.Button({"ID": "Close", "Text": "Close"}),
                        ],
                    ),
                    ui.TextEdit({"ID": "Status", "ReadOnly": True, "Text": "Ready."}),
                ],
            )
        ],
    )

    items = win.GetItems()

    def set_status(text):
        items["Status"].Text = text

    def on_close(ev):
        disp.ExitLoop()

    def on_run(ev):
        try:
            items["Run"].Enabled = False
            key = items["ApiKey"].Text
            result = run_transcription(key, set_status)
            msg = [
                "Done.",
                "Clip: " + result["clip"],
                "SRT: " + result["srt"],
                "JSON: " + result["json"],
                "Imported to Media Pool: " + ("yes" if result["imported"] else "no"),
                "",
                "Drag the SRT from the Media Pool to a subtitle track.",
            ]
            set_status("\n".join(msg))
        except Exception as exc:
            set_status("ERROR:\n" + str(exc) + "\n\n" + traceback.format_exc(limit=2))
        finally:
            items["Run"].Enabled = True

    win.On.ResolveHebrewAutoCaptions.Close = on_close
    win.On.Close.Clicked = on_close
    win.On.Run.Clicked = on_run

    win.Show()
    disp.RunLoop()
    win.Hide()


if __name__ == "__main__":
    run_ui()
