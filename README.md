# PixMind Glow Captions for DaVinci Resolve

Hebrew auto captions plus the full PixMind Glow title pack, shipped as one macOS installer.

## Download

Grab `PixMindGlowCaptions-1.5.0.pkg` from the [Releases](../../releases) page, or from `dist/` in this repo.

The package is unsigned. On first run: right-click the file, choose Open, then confirm.
After installing, restart DaVinci Resolve.

## What the installer puts on your Mac

| Component | Location |
|---|---|
| 3 Resolve scripts (Hebrew Auto Captions, PixMind Glow Caption Styler, PixMind Glow Apply Gold) | `Workspace -> Scripts -> Edit` |
| 27 PixMind Glow titles (25 colors, Custom Color, Signature Original) | `Effects Library -> Titles -> PixMind Glow` |
| PixMind Glow Custom Color macro | Fusion `Macros` |
| PixMind Glow Hebrew font | `~/Library/Fonts` |
| Helper scripts (`transcribe.py`, `render_caption_overlays.py`) | `/Library/Application Support/pixmind-resolve-hebrew-auto-captions` |

## Build from source

```bash
./build-pkg.sh
```

Output: `dist/PixMindGlowCaptions-1.5.0.pkg`. The payload lives in `payload/`, the installer logic in `scripts/postinstall`.

## What It Does

1. Reads the current timeline and the video clip under the playhead.
2. Extracts that clip range to a temporary `m4a` file with `ffmpeg`.
3. Sends only the audio file to Groq Speech-to-Text.
4. Creates:
   - `captions.json`
   - `captions.srt`
5. Imports the SRT into the Resolve Media Pool.

Captions are one line only, up to 3 words per caption.

The package also installs PixMind Glow extras:

- All 27 `PixMind Glow` title templates in the Resolve Effects Library.
- `Workspace -> Scripts -> Edit -> PixMind Glow Apply Gold`, which applies the gold glow look to an existing Text+ clip/tool while keeping the current text.
- `Workspace -> Scripts -> Edit -> PixMind Glow Caption Styler`, which converts native SRT subtitle items into video clips containing exact Fusion comps built from the installed PixMind Glow title templates.
- `PixMind Glow Hebrew`, a custom geometric Hebrew display font.

## Usage

1. Open a timeline.
2. Put the playhead over the video clip you want to caption.
3. Run the script from `Workspace -> Scripts -> Edit`.
4. Paste your Groq API key.
5. Click `Create SRT`.
6. Drag the imported SRT from the Media Pool to a subtitle track.

## Gold Glow Look

After install and Resolve restart:

- To create a new glowing title, drag `Effects Library -> Titles -> PixMind Glow -> Gold` to the timeline.
- To apply the look to an existing Text/Text+ clip, put the playhead over that title or select its Text+ node in Fusion, then run:

```
Workspace -> Scripts -> Edit -> PixMind Glow Apply Gold
```

Resolve scripting does not expose a custom drag/drop event for dropping one title template directly onto an existing title clip, so this package provides the closest reliable workflow: one script click applies the same gold glow styling to the existing Text+ content.

## Apply PixMind Glow to SRT Subtitles

DaVinci Resolve does not allow Fusion Effects or Fusion Titles to be dropped onto native subtitle/SRT rows as a style replacement. To get a 1:1 PixMind Glow result, use:

```
Workspace -> Scripts -> Edit -> PixMind Glow Caption Styler
```

It reads subtitle items already on the timeline, lets you choose an installed PixMind Glow title template, creates transparent video clips above the edit, and imports a Fusion comp into each clip. The Fusion comp is generated from the original `.setting` template, so it contains the same `TextPlus`, `BitmapMask`, `CreateBumpMap`, `Desat`, `Tint`, and `SoftGlow` graph.

Modes:

- `All subtitles on track`
- `Marked range`
- `Current subtitle`

If you do not want duplicate text, enable `Disable original subtitle track after creating styled clips`.

## Requirements

- `ffmpeg`
- Groq API key

The script looks for `ffmpeg` at `/opt/homebrew/bin/ffmpeg`, `/usr/local/bin/ffmpeg`, common Homebrew locations, and then `PATH`.
