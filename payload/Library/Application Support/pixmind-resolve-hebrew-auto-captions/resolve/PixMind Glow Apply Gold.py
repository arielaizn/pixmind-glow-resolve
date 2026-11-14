#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Apply the PixMind Gold Glow look to the current Text+ clip/tool.

Run from:
  Workspace -> Scripts -> Edit -> PixMind Glow Apply Gold
"""

import traceback


FONT_FAMILY = "PixMind Glow Hebrew"
GOLD = (1.0, 0.80, 0.32)


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


def _tool_reg_id(tool):
    try:
        attrs = tool.GetAttrs() or {}
        return attrs.get("TOOLS_RegID") or attrs.get("TOOLS_Name") or ""
    except Exception:
        return ""


def _is_text_plus(tool):
    reg_id = str(_tool_reg_id(tool))
    return reg_id == "TextPlus" or "TextPlus" in reg_id


def _connected_tool(input_obj):
    try:
        connected = input_obj.GetConnectedOutput()
        return connected.GetTool() if connected else None
    except Exception:
        return None


def current_comp():
    comp = None
    if FUSION:
        try:
            comp = FUSION.GetCurrentComp()
        except Exception:
            comp = None
    if comp:
        return comp

    if not RESOLVE:
        raise RuntimeError("Could not connect to DaVinci Resolve.")
    pm = RESOLVE.GetProjectManager()
    project = pm.GetCurrentProject() if pm else None
    timeline = project.GetCurrentTimeline() if project else None
    if not timeline:
        raise RuntimeError("Open a timeline first.")
    item = timeline.GetCurrentVideoItem()
    if not item:
        raise RuntimeError("Move the playhead over the Text/Text+ clip first.")

    count = int(item.GetFusionCompCount() or 0)
    if count > 0:
        return item.GetFusionCompByIndex(1)
    return item.AddFusionComp()


def find_text_tools(comp):
    selected = []
    try:
        selected = list((comp.GetToolList(True) or {}).values())
    except Exception:
        selected = []
    selected_text = [tool for tool in selected if _is_text_plus(tool)]
    if selected_text:
        return selected_text, "selected Text+ tool"

    try:
        all_tools = list((comp.GetToolList(False) or {}).values())
    except Exception:
        all_tools = []
    text_tools = [tool for tool in all_tools if _is_text_plus(tool)]
    return text_tools, "Text+ tools in current clip"


def style_text_tool(tool):
    r, g, b = GOLD
    tool.SetInput("Font", FONT_FAMILY)
    tool.SetInput("Style", "Regular")
    tool.SetInput("Red1", r)
    tool.SetInput("Green1", g)
    tool.SetInput("Blue1", b)
    tool.SetInput("EnabledExtentColor2", 1)
    tool.SetInput("Enabled2", 1)
    tool.SetInput("Type2", "Outline")
    tool.SetInput("Thickness2", 0.12)
    tool.SetInput("Red2", 0.0)
    tool.SetInput("Green2", 0.0)
    tool.SetInput("Blue2", 0.0)
    tool.SetInput("Alpha2", 1.0)
    tool.SetInput("Enabled3", 1)
    tool.SetInput("Type3", "Shadow")
    tool.SetInput("Offset3", [0.006, -0.006])
    tool.SetInput("Softness3", 3.0)
    tool.SetInput("Red3", 0.0)
    tool.SetInput("Green3", 0.0)
    tool.SetInput("Blue3", 0.0)
    tool.SetInput("Alpha3", 0.70)


def insert_glow_if_direct(comp, text_tool):
    media_out = comp.FindTool("MediaOut1")
    if not media_out:
        return False

    current_source = _connected_tool(media_out.Input)
    if not current_source or current_source.Name != text_tool.Name:
        return False

    glow = comp.AddTool("SoftGlow", -32768, -32768)
    try:
        glow.SetAttrs({"TOOLS_Name": "PixMindGoldGlow"})
    except Exception:
        pass
    glow.SetInput("Gain", 2.559)
    glow.SetInput("XGlowSize", 0.0)
    glow.SetInput("YGlowSize", 10.0)
    glow.ConnectInput("Input", text_tool)
    media_out.ConnectInput("Input", glow)
    return True


def apply_gold_glow():
    comp = current_comp()
    tools, scope = find_text_tools(comp)
    if not tools:
        raise RuntimeError("No Text+ tool found. Select a Text+ title or put the playhead over one.")

    comp.Lock()
    comp.StartUndo("PixMind Gold Glow")
    inserted_glow = False
    try:
        for tool in tools:
            style_text_tool(tool)
        if len(tools) == 1:
            inserted_glow = insert_glow_if_direct(comp, tools[0])
    finally:
        comp.EndUndo(True)
        comp.Unlock()

    return "Applied PixMind Gold Glow to %d %s.%s" % (
        len(tools),
        scope,
        " Inserted SoftGlow." if inserted_glow else "",
    )


def show_ui():
    if not FUSION:
        print(apply_gold_glow())
        return

    ui = FUSION.UIManager
    disp = BMD.UIDispatcher(ui) if BMD else FUSION.UIDispatcher(ui)
    win = disp.AddWindow(
        {
            "ID": "PixMindGlowApplyGold",
            "WindowTitle": "PixMind Glow Apply Gold",
            "Geometry": [300, 260, 460, 210],
        },
        [
            ui.VGroup(
                {"Spacing": 8, "Margin": 14},
                [
                    ui.Label({"Text": "PixMind Glow Apply Gold", "StyleSheet": "font-size:18px;font-weight:700;"}),
                    ui.Label({"Text": "Select a Text+ tool, or put the playhead over a Text/Text+ clip."}),
                    ui.HGroup(
                        {"Spacing": 8},
                        [
                            ui.Button({"ID": "Apply", "Text": "Apply Gold Glow"}),
                            ui.Button({"ID": "Close", "Text": "Close"}),
                        ],
                    ),
                    ui.TextEdit({"ID": "Status", "ReadOnly": True, "Text": "Ready."}),
                ],
            )
        ],
    )

    items = win.GetItems()

    def on_close(ev):
        disp.ExitLoop()

    def on_apply(ev):
        try:
            items["Apply"].Enabled = False
            items["Status"].Text = apply_gold_glow()
        except Exception as exc:
            items["Status"].Text = "ERROR:\n" + str(exc) + "\n\n" + traceback.format_exc(limit=2)
        finally:
            items["Apply"].Enabled = True

    win.On.PixMindGlowApplyGold.Close = on_close
    win.On.Close.Clicked = on_close
    win.On.Apply.Clicked = on_apply
    win.Show()
    disp.RunLoop()
    win.Hide()


if __name__ == "__main__":
    show_ui()
