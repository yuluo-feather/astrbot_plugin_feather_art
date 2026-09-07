<p align="center">
  <img src="https://raw.githubusercontent.com/yuluo-feather/astrbot_plugin_feather_art/main/logo_small.png" width="110" height="110" align="middle"/> <font size="6"><b>羽画 Feather Art 🪶</b></font>
</p>

<p align="center">
  "Hand me an image, get back something that opens on HTML + CSS alone. Hmph — no internet needed." — Feather
</p>

<p align="center">
  <a href="https://github.com/yuluo-feather/astrbot_plugin_feather_art/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-AGPL%20v3-ffb3d9" alt="License: AGPL v3"/></a>
  <a href="https://astrbot.app"><img src="https://img.shields.io/badge/AstrBot-Plugin-ff9ecb" alt="AstrBot Plugin"/></a>
  <img src="https://img.shields.io/badge/version-v0.2.0-f8a5c2" alt="v0.2.0"/>
</p>

<p align="center">🪶 ✨ 🎨 🎬</p>

> [English](https://github.com/yuluo-feather/astrbot_plugin_feather_art/blob/main/README.en.md) | [简体中文](https://github.com/yuluo-feather/astrbot_plugin_feather_art/blob/main/README.md)

---

## 📖 Contents

- 🎨 [Features](#features)
- 🎚️ [Presets](#presets)
- 🖊️ [Usage](#usage)
- ⚙️ [Configuration](#configuration)
- ⚗️ [How it works](#how-it-works)
- 📦 [Installation](#installation)
- 🛠️ [Development](#development)
- 📜 [Changelog](#changelog)
- 🌙 [Known limits](#known-limits)
- ⭐ [Credits](#credits)

---

An AstrBot plugin that **traces an image offline** into a single-file HTML + CSS illustration — no `<img>`, no SVG, no Canvas, no JavaScript, no base64, no external assets. Opening it needs nothing but a browser. Animated GIF / WebP inputs become **pure-CSS looping animations**: frame-to-frame layer tracking plus a @keyframes timeline, played directly by the browser.

## 🎨 Features

- 🖼️ **Offline tracing**: bitmap → single-file HTML; everything computed locally, zero API dependency
- 🎬 **Animated input**: GIF / WebP → pure-CSS animation with frame-to-frame layer tracking (IoU + color + centroid scoring), anchored across missing frames — no flicker
- 🎨 **Perceptual quantization**: Oklab median-cut in perceptual space; local gradients inside large regions plus a 48-color underpainting layer — less banding, less detail loss
- 🎚️ **Four presets**: sketch / motion / freehand (default) / finebrush; `--fit` budget overshoot steps down **colors first, width last**, so finer presets keep their resolution
- 🛡️ **Contract audit**: the output is audited (no scripts / images / external links / base64 injection), with an offline MAE similarity score
- ⚖️ **Deterministic**: identical input, parameters and dependency versions produce byte-identical HTML — no randomness, no tricks
- 🤖 **Two entry points**: `/羽画` command + natural language (send an image and say "make this a pure CSS illustration", disable via config)
- 🚦 **Hardening & throttling**: input size caps / pixel-bomb guard / multi-frame checks; global concurrency 1 + 60s per-user cooldown

## 🎚️ Presets

| Preset | Max width | Palette | Epsilon | Merge passes | Notes |
| --- | ---: | ---: | ---: | ---: | --- |
| sketch · 速写 | 768 | 96 | 0.38 | 2 | light & fast; icons, memes, stamps |
| motion · 动画 | 512 | 96 | 0.36 | 2 | animated GIF / WebP: multi-frame tracing, fast & stable |
| freehand · 写意 (default) | 1200 | 160 | 0.30 | 3 | daily illustrations, balanced |
| finebrush · 工笔 | 1600 | 256 | 0.24 | 4 | detail first; larger & slower |

## 🖊️ Usage

| Use | How | Notes |
|-----|-----|-------|
| Trace an image | `/羽画 [preset]` + send image | preset and image order doesn't matter; the literal word `图片` is optional; presets: sketch / freehand / finebrush (default freehand) |
| Cap the size | `/羽画 --fit N` | target volume (MiB) with 2% tolerance; overshoot steps down colors first, then width |
| Trace an animation | send a GIF / WebP | automatically uses the motion preset → looping pure-CSS animation; very long ones (>30 s or 2500+ frames) prompt first |
| Natural language | say "make this a pure CSS illustration" after sending an image | triggers automatically (disable via config) |

Examples:

```
/羽画 速写
/羽画 工笔 --fit 20
```

> 💡 **Triggering**: works directly in private chat (with or without the `/` prefix); in group chats, @ the bot first.

## ⚙️ Configuration

Configurable from the AstrBot plugin panel:

| Key | Default | Description |
|-----|---------|-------------|
| `preset` | `freehand` | default preset (sketch / freehand / finebrush; the motion preset is picked automatically for animated input) |
| `fit_mb` | `40` | output volume target (MiB), 2% tolerance; `0` = no auto stepping |
| `max_mb` | `64` | hard output size cap (MiB) |
| `score` | `true` | compute the offline MAE similarity score |
| `concurrent` | `1` | simultaneous trace jobs |
| `cooldown` | `60` | per-user cooldown between traces (seconds) |
| `llm_tool` | `true` | natural-language entry switch |
| `max_image_mb` | `20` | input image size cap |
| `max_pixels` | `40000000` | input pixel cap (decompression-bomb guard) |

## ⚗️ How it works

1. EXIF orientation → matte compositing → downscale → bilateral filter
2. Oklab perceptual-space box median-cut quantization (no dithering)
3. Small regions (<16px) merge only into adjacent, larger, color-similar ones (ΔE ≤18, cumulative drift ≤23)
4. 4x subpixel contour sampling, slight dilation, smoothing, simplification
5. Holes and islands carried by even-odd polygons (zero-area bridging)
6. First-order linear gradients inside large regions; small fragments gathered by grid to cut element count
7. 48-color low-res underpainting layer
8. Single-file HTML generation + contract audit

Animated input adds another stage: sampling (adaptive to duration, ~4 fps target) → frame-to-frame layer tracking (deterministic greedy: IoU + color + centroid) → missing frames anchored to the previous frame's features → @keyframes timeline (hard-cut by default, optional vertex-aligned tweening).

## 📦 Installation

### Option 1: install from GitHub

1. Open the AstrBot panel → "Plugin market / Install plugin"
2. Choose "Install from GitHub repository" and enter:

   `https://github.com/yuluo-feather/astrbot_plugin_feather_art`

3. Install, and let dependencies resolve automatically

### Option 2: manual install

1. Clone or download this repo into AstrBot's `data/plugins/` directory, keeping the folder name `astrbot_plugin_feather_art`:

   ```bash
   cd AstrBot/data/plugins
   git clone https://github.com/yuluo-feather/astrbot_plugin_feather_art.git
   ```

2. Install authoring dependencies (needed for tracing; not needed to view the HTML):

   ```powershell
   <python>\Scripts\python.exe -m pip install -r requirements.txt
   ```

3. Restart AstrBot (or reload the plugin from the WebUI)

**Runtime**: Python 3.12+; dependencies are NumPy / Pillow / OpenCV (headless).

## 🛠️ Development

```
feather_art/          # algorithm package: imaging/quantize/merge/geometry/gradient/render/audit/score
service.py            # orchestration: static tracing, fit ladder, atomic writes, reports
service_animation.py  # orchestration: animation tracing (sampling/layer tracking/animation render)
hardening.py          # input hardening: size, pixel bombs, multi-frame
limiter.py            # concurrency + per-user cooldown
deliver.py            # reporting copy + file chain
main.py               # plugin entry (command + natural language)
config.py             # config defaults and reading primitives
tests/                # pytest suite (grows with development)
```

```powershell
<python>\Scripts\python.exe -m pytest tests -q
```

## 📜 Changelog

#### v0.2.0

- Added: animation tracing — GIF / WebP → pure-CSS animation (frame-to-frame layer tracking + @keyframes timeline); new motion preset
- Fixed: legacy WebView rendering compatibility (dropped `aspect-ratio` / `min()` / `inset`); `color-scheme: light` prevents Android dark-mode inversion; kernels without `clip-path` support get a clear hint instead of garbage
- Fixed: conversion failure no longer leaks internal exception messages (which may contain server paths); malformed config values no longer reach the volume calculation layer
- Improved: animation frame cap 200 → 6000 (total-pixel budget guards); command parsing is order-independent; `--fit` steps colors first, width last; default budget 20 → 40 MiB

> Full history: [CHANGELOG.md](https://github.com/yuluo-feather/astrbot_plugin_feather_art/blob/main/CHANGELOG.md).

## 🌙 Known limits

- Photos, noise and dense textures produce large files; use `--fit` or a lighter preset
- Very long animations (>30 s or 2500+ frames) prompt first: use the original GIF or trim a 10–15 s clip, and tracing runs only after you confirm
- Transparent PNG is composited onto the matte (default white)
- Wide-gamut / CMYK sources: convert to sRGB first
- The audit checks structure, not visual similarity — always eyeball the result

---

## ⭐ Credits

- The static tracing pipeline (quantization / merging / contours / gradients) is inspired by [AvroraCL/image-to-css-art](https://github.com/AvroraCL/image-to-css-art) (MIT)
- The *animated GIF / WebP → pure-CSS animation* idea is inspired by [kevinjycui/css-video](https://github.com/kevinjycui/css-video) — we replaced its per-frame clustering + index alignment with frame-to-frame layer tracking (IoU + color + centroid matching); an independent design, no code copied
- [javierbyte/img2css](https://github.com/javierbyte/img2css) is kept as a classic reference (per-pixel box-shadow path), which this plugin does not follow

Inspiration only; no code was copied. Third-party dependencies keep their own licenses; rights over input images and derived content are unaffected by using this plugin.

## License

[AGPL-3.0](LICENSE)
