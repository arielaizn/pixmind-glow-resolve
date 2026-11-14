#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Turn native Resolve SRT subtitle items into exact PixMind Glow Fusion title clips.

Run from:
  Workspace -> Scripts -> Edit -> PixMind Glow Caption Styler
"""

import json
import os
import sys
import time
import traceback


PLUGIN_ROOT = "/Library/Application Support/pixmind-resolve-hebrew-auto-captions"
USER_PLUGIN_ROOT = os.path.expanduser("~/Library/Application Support/pixmind-resolve-hebrew-auto-captions")
FFMPEG_CANDIDATES = [
    os.environ.get("FFMPEG_PATH"),
    "/opt/homebrew/bin/ffmpeg",
    "/usr/local/bin/ffmpeg",
    "/usr/bin/ffmpeg",
]
TEMPLATE_ROOTS = [
    os.path.expanduser("~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Templates/Edit/Titles"),
    "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Templates/Edit/Titles",
]


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


def find_ffmpeg():
    for candidate in FFMPEG_CANDIDATES:
        if candidate and os.path.exists(candidate):
            return candidate
    raise RuntimeError("ffmpeg not found. Install with: brew install ffmpeg")


def templates():
    found = []
    seen = set()
    for root in TEMPLATE_ROOTS:
        if not os.path.isdir(root):
            continue
        for base, _dirs, files in os.walk(root):
            for filename in files:
                if not filename.endswith(".setting"):
                    continue
                path = os.path.join(base, filename)
                rel = os.path.relpath(path, root)
                if rel in seen:
                    continue
                seen.add(rel)
                found.append((rel[:-8], path))
    found.sort(key=lambda item: (0 if item[0].startswith("PixMind Glow/") else 1, item[0].lower()))
    return found


def parse_fps(value):
    try:
        return float(str(value).replace(",", "."))
    except Exception:
        return 25.0


def parse_tc_to_frames(timecode, fps):
    parts = str(timecode or "00:00:00:00").replace(";", ":").split(":")
    if len(parts) != 4:
        return 0
    h, m, s, f = [int(float(part)) for part in parts]
    rate = int(round(fps))
    return (((h * 60 + m) * 60) + s) * rate + f


def project_context():
    if not RESOLVE:
        raise RuntimeError("Could not connect to DaVinci Resolve.")
    pm = RESOLVE.GetProjectManager()
    project = pm.GetCurrentProject() if pm else None
    if not project:
        raise RuntimeError("No current Resolve project.")
    timeline = project.GetCurrentTimeline()
    if not timeline:
        raise RuntimeError("No current timeline.")
    media_pool = project.GetMediaPool()
    if not media_pool:
        raise RuntimeError("Could not access Media Pool.")
    fps = parse_fps(timeline.GetSetting("timelineFrameRate") or project.GetSetting("timelineFrameRate"))
    width = int(timeline.GetSetting("timelineResolutionWidth") or project.GetSetting("timelineResolutionWidth") or 1080)
    height = int(timeline.GetSetting("timelineResolutionHeight") or project.GetSetting("timelineResolutionHeight") or 1920)
    start_frame = int(timeline.GetStartFrame() or 0)
    return project, timeline, media_pool, fps, width, height, start_frame


def selected_subtitles(timeline, fps, start_frame, subtitle_track, mode):
    items = timeline.GetItemListInTrack("subtitle", subtitle_track) or []
    if not items:
        raise RuntimeError("No subtitles found on subtitle track %d." % subtitle_track)

    if mode == "Current subtitle":
        current_abs = parse_tc_to_frames(timeline.GetCurrentTimecode(), fps)
        selected = [item for item in items if int(item.GetStart(False)) <= current_abs < int(item.GetEnd(False))]
    elif mode == "Marked range":
        marks = timeline.GetMarkInOut() or {}
        video_mark = marks.get("video") or marks.get("all") or {}
        mark_in = video_mark.get("in") or video_mark.get("markIn") or video_mark.get("In")
        mark_out = video_mark.get("out") or video_mark.get("markOut") or video_mark.get("Out")
        if mark_in is None or mark_out is None:
            selected = items
        else:
            abs_in = start_frame + int(mark_in)
            abs_out = start_frame + int(mark_out)
            selected = [item for item in items if int(item.GetEnd(False)) > abs_in and int(item.GetStart(False)) < abs_out]
    else:
        selected = items

    if not selected:
        raise RuntimeError("No subtitle items matched the selected range.")

    return [
        {
            "text": item.GetName(),
            "start": int(item.GetStart(False)),
            "end": int(item.GetEnd(False)),
        }
        for item in selected
    ]


def ranges_overlap(a_start, a_end, b_start, b_end):
    return int(a_end) > int(b_start) and int(a_start) < int(b_end)


def track_overlaps_cues(timeline, track_index, cues):
    items = timeline.GetItemListInTrack("video", track_index) or []
    for item in items:
        try:
            item_start = int(item.GetStart(False))
            item_end = int(item.GetEnd(False))
        except Exception:
            continue
        for cue in cues:
            if ranges_overlap(item_start, item_end, int(cue["start"]), int(cue["end"])):
                return True
    return False


def ensure_video_track(timeline, requested_track, cues):
    candidate = max(1, int(requested_track))
    limit = candidate + 50
    while candidate <= limit:
        while timeline.GetTrackCount("video") < candidate:
            if not timeline.AddTrack("video"):
                raise RuntimeError("Could not create video track %d." % candidate)
        if not track_overlaps_cues(timeline, candidate, cues):
            return candidate
        candidate += 1
    raise RuntimeError("Could not find a free video track for the selected subtitle range.")


def active_tool_name(template_text):
    marker = 'ActiveTool = "'
    start = template_text.rfind(marker)
    if start >= 0:
        start += len(marker)
        end = template_text.find('"', start)
        if end > start:
            return template_text[start:end]
    marker = "\t\t"
    start = template_text.find(marker)
    if start >= 0:
        rest = template_text[start + len(marker) :]
        return rest.split("=", 1)[0].strip()
    raise RuntimeError("Could not detect active tool in template.")


def lua_escape(value):
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def make_fusion_comp(template_path, text, width, height, start_frame, end_frame, out_path):
    with open(template_path, "r", encoding="utf-8", errors="ignore") as handle:
        content = handle.read()
    group = active_tool_name(content)
    first_frame = int(start_frame)
    last_frame = max(first_frame, int(end_frame) - 1)
    content = content.replace(
        'GlobalOut = Input { Value = 1000, }',
        'GlobalIn = Input { Value = %d, },\n\t\t\t\t\t\tGlobalOut = Input { Value = %d, }' % (first_frame, last_frame),
    )
    content = content.replace('Width = Input { Value = 1920, }', 'Width = Input { Value = %d, }' % int(width))
    content = content.replace('Height = Input { Value = 1080, }', 'Height = Input { Value = %d, }' % int(height))
    content = content.replace(
        'StyledText = Input { Value = "Sample Text", }',
        'StyledText = Input { Value = "%s", }' % lua_escape(text),
        1,
    )
    media_out = '''\t\tMediaOut1 = MediaOut {
\t\t\tInputs = {
\t\t\t\tIndex = Input { Value = "0", },
\t\t\t\tInput = Input { SourceOp = "%s", Source = "MainOutput1", }
\t\t\t},
\t\t\tViewInfo = OperatorInfo { Pos = { 440, 0 } },
\t\t},
''' % group
    content = content.replace('\t},\n\tActiveTool = "%s"' % group, media_out + '\t},\n\tActiveTool = "%s"' % group)
    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write(content)


def create_blank_movie(width, height, fps, frames, out_path):
    ffmpeg = find_ffmpeg()
    duration = max(float(frames) / float(fps), 0.05)
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=black@0.0:s=%dx%d:r=%s" % (int(width), int(height), fps),
        "-t",
        "%.6f" % duration,
        "-an",
        "-c:v",
        "prores_ks",
        "-profile:v",
        "4444",
        "-pix_fmt",
        "yuva444p10le",
        out_path,
    ]
    import subprocess

    subprocess.run(cmd, check=True)


def create_exact_fusion_clips(data, template_path):
    out_root = os.path.join(os.path.expanduser("~/Movies"), "PixMind Glow Caption Styler")
    os.makedirs(out_root, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = os.path.join(out_root, stamp)
    os.makedirs(out_dir, exist_ok=True)
    comp_dir = os.path.join(out_dir, "fusion-comps")
    os.makedirs(comp_dir, exist_ok=True)
    input_path = os.path.join(out_dir, "captions-input.json")
    manifest_path = os.path.join(out_dir, "manifest.json")
    with open(input_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    captions = data.get("captions") or []
    if not captions:
        raise RuntimeError("No captions to convert.")
    max_frames = max(max(1, int(cue["end"]) - int(cue["start"])) for cue in captions)
    blank_path = os.path.join(out_dir, "pixmind-transparent-base.mov")
    create_blank_movie(data["width"], data["height"], data["fps"], max_frames, blank_path)
    items = []
    for index, cue in enumerate(captions, start=1):
        frames = max(1, int(cue["end"]) - int(cue["start"]))
        comp_path = os.path.join(comp_dir, "caption-%04d.comp" % index)
        make_fusion_comp(template_path, cue["text"], data["width"], data["height"], cue["start"], cue["end"], comp_path)
        item = dict(cue)
        item["frames"] = frames
        item["comp"] = comp_path
        items.append(item)
    manifest = {
        "template": template_path,
        "width": data["width"],
        "height": data["height"],
        "fps": data["fps"],
        "blank_media": blank_path,
        "items": items,
    }
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
    return manifest, out_dir


def import_and_place(media_pool, timeline, manifest, target_track):
    placed = []
    imported_blank = media_pool.ImportMedia([manifest["blank_media"]])
    if not imported_blank:
        raise RuntimeError("Could not import transparent base media.")
    media_item = imported_blank[0]
    for entry in manifest.get("items") or []:
        start = int(entry["start"])
        end = int(entry["end"])
        duration = max(1, end - start)
        clip_info = {
            "mediaPoolItem": media_item,
            "startFrame": 0,
            "endFrame": duration - 1,
            "recordFrame": start,
            "trackIndex": target_track,
            "mediaType": 1,
        }
        result = media_pool.AppendToTimeline([clip_info])
        if not result or not result[0]:
            raise RuntimeError("Could not append rendered caption at frame %d." % start)

        item = result[0]
        try:
            item_start = item.GetStart(False)
            item_end = item.GetEnd(False)
        except Exception:
            item_start = None
            item_end = None
        if item_start is None or item_end is None:
            raise RuntimeError(
                "Resolve returned an invalid timeline item at frame %d. "
                "Choose an empty output video track and try again." % start
            )

        imported_comp = item.ImportFusionComp(entry["comp"])
        if not imported_comp:
            time.sleep(0.1)
            imported_comp = item.ImportFusionComp(entry["comp"])
        if not imported_comp:
            raise RuntimeError("Could not import Fusion comp: " + entry["comp"])

        comp = imported_comp
        if not hasattr(comp, "SetAttrs"):
            try:
                comp = item.GetFusionCompByIndex(item.GetFusionCompCount())
            except Exception:
                comp = None
        if comp and hasattr(comp, "SetAttrs"):
            comp.SetAttrs(
                {
                    "COMPN_GlobalStart": start,
                    "COMPN_GlobalEnd": end - 1,
                    "COMPN_RenderStart": start,
                    "COMPN_RenderEnd": end - 1,
                    "COMPN_CurrentTime": start,
                }
            )
        placed.append(item)
    return placed


def apply_template(template_path, mode, subtitle_track, target_track, disable_original, status_cb):
    project, timeline, media_pool, fps, width, height, start_frame = project_context()
    cues = selected_subtitles(timeline, fps, start_frame, subtitle_track, mode)
    target_track = ensure_video_track(timeline, target_track, cues)
    data = {
        "fps": fps,
        "width": width,
        "height": height,
        "timeline_start_frame": start_frame,
        "captions": cues,
    }
    status_cb("Building %d exact Fusion title clips from the selected template..." % len(cues))
    manifest, out_dir = create_exact_fusion_clips(data, template_path)
    status_cb("Importing exact PixMind Glow clips to video track %d..." % target_track)
    placed = import_and_place(media_pool, timeline, manifest, target_track)
    if disable_original:
        timeline.SetTrackEnable("subtitle", subtitle_track, False)
    return {
        "count": len(placed),
        "out_dir": out_dir,
        "track": target_track,
        "template": template_path,
    }


def run_ui():
    if not FUSION:
        print("PixMind Glow Caption Styler: Fusion UI Manager is unavailable.")
        return

    template_list = templates()
    if not template_list:
        print("No Resolve title templates found.")
        return

    ui = FUSION.UIManager
    disp = BMD.UIDispatcher(ui) if BMD else FUSION.UIDispatcher(ui)
    win = disp.AddWindow(
        {
            "ID": "PixMindGlowCaptionStyler",
            "WindowTitle": "PixMind Glow Caption Styler",
            "Geometry": [240, 220, 620, 390],
        },
        [
            ui.VGroup(
                {"Spacing": 8, "Margin": 14},
                [
                    ui.Label({"Text": "PixMind Glow Caption Styler", "StyleSheet": "font-size:20px;font-weight:700;"}),
                    ui.Label({"Text": "Choose a Resolve title template and convert SRT subtitles to exact Fusion title clips."}),
                    ui.Label({"Text": "Template"}),
                    ui.ComboBox({"ID": "Template"}),
                    ui.HGroup(
                        {"Spacing": 8},
                        [
                            ui.VGroup([ui.Label({"Text": "Apply To"}), ui.ComboBox({"ID": "Mode"})]),
                            ui.VGroup([ui.Label({"Text": "Subtitle Track"}), ui.LineEdit({"ID": "SubtitleTrack", "Text": "1"})]),
                            ui.VGroup([ui.Label({"Text": "Output Video Track"}), ui.LineEdit({"ID": "TargetTrack", "Text": "2"})]),
                        ],
                    ),
                    ui.CheckBox({"ID": "DisableOriginal", "Text": "Disable original subtitle track after creating styled overlays", "Checked": False}),
                    ui.HGroup(
                        {"Spacing": 8},
                        [
                            ui.Button({"ID": "Apply", "Text": "Apply Template"}),
                            ui.Button({"ID": "Close", "Text": "Close"}),
                        ],
                    ),
                    ui.TextEdit({"ID": "Status", "ReadOnly": True, "Text": "Ready."}),
                ],
            )
        ],
    )
    items = win.GetItems()

    for label, _path in template_list:
        items["Template"].AddItem(label)
    for mode in ["All subtitles on track", "Marked range", "Current subtitle"]:
        items["Mode"].AddItem(mode)

    def status(text):
        items["Status"].Text = text

    def on_close(ev):
        disp.ExitLoop()

    def on_apply(ev):
        try:
            items["Apply"].Enabled = False
            template_index = int(items["Template"].CurrentIndex)
            template_path = template_list[template_index][1]
            mode = items["Mode"].CurrentText
            subtitle_track = int(items["SubtitleTrack"].Text or "1")
            target_track = int(items["TargetTrack"].Text or "2")
            disable_original = bool(items["DisableOriginal"].Checked)
            result = apply_template(template_path, mode, subtitle_track, target_track, disable_original, status)
            status(
                "\n".join(
                    [
                        "Done.",
                        "Created overlays: %d" % result["count"],
                        "Output video track: V%d" % result["track"],
                        "Template: " + os.path.basename(result["template"]),
                        "Files: " + result["out_dir"],
                    ]
                )
            )
        except Exception as exc:
            status("ERROR:\n" + str(exc) + "\n\n" + traceback.format_exc(limit=2))
        finally:
            items["Apply"].Enabled = True

    win.On.PixMindGlowCaptionStyler.Close = on_close
    win.On.Close.Clicked = on_close
    win.On.Apply.Clicked = on_apply
    win.Show()
    disp.RunLoop()
    win.Hide()


if __name__ == "__main__":
    run_ui()
