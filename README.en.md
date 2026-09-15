<p align="center">
  <img src="https://raw.githubusercontent.com/yuluo-feather/astrbot_plugin_feather_art/main/logo_small.png" width="110" height="110" align="middle"/> <font size="6"><b>羽画 Feather Art 🪶</b></font>
</p>

<p align="center">
  "Hand me an image, get back something that opens on HTML + CSS alone. Hmph — no internet needed." — Feather
</p>

<p align="center">
  <a href="https://github.com/yuluo-feather/astrbot_plugin_feather_art/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-AGPL%20v3-ffb3d9" alt="License: AGPL v3"/></a>
  <a href="https://astrbot.app"><img src="https://img.shields.io/badge/AstrBot-Plugin-ff9ecb" alt="AstrBot Plugin"/></a>
  <img src="https://img.shields.io/badge/version-v0.3.3-f8a5c2" alt="v0.3.3"/>
</p>

<p align="center">🪶 ✨ 🎨 🎬</p>

> [English](https://github.com/yuluo-feather/astrbot_plugin_feather_art/blob/main/README.en.md) | [简体中文](https://github.com/yuluo-feather/astrbot_plugin_feather_art/blob/main/README.md)

---

## 📖 Contents

- 🎨 [Features](#features)
- 🎚️ [Presets](#presets)
- 🖊️ [Usage](#usage)
- 🔄 [Workflow](#workflow)
- ⚙️ [Configuration](#configuration)
- ⚗️ [How it works](#how-it-works)
- 📦 [Installation](#installation)
- 🛠️ [Development](#development)
- 📜 [Changelog](#changelog)
- 🌙 [Known limits](#known-limits)
- ⭐ [Credits](#credits)

---

An AstrBot plugin that **traces an image offline** into a single-file illustration — by default **pure HTML + CSS**: no `<img>`, no SVG, no Canvas, no JavaScript, no base64, no external assets. (An optional inline-SVG dialect is available too — still a single file, still zero scripts and zero external links; see the `render_backend` config key.) Opening it needs nothing but a browser. Animated GIF / WebP inputs become **pure-CSS looping animations**: frame-to-frame layer tracking plus a @keyframes timeline, played directly by the browser.

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
| sketch · 速写 | 1152 | 96 | 0.38 | 2 | light & fast; icons, memes, stamps |
| motion · 动画 | 512 | 96 | 0.36 | 2 | animated GIF / WebP: multi-frame tracing, fast & stable |
| freehand · 写意 (default) | 1600 | 160 | 0.30 | 3 | daily illustrations, balanced |
| finebrush · 工笔 | 2000 | 256 | 0.24 | 4 | detail first; larger & slower |

## 🖊️ Usage

| Use | How | Notes |
|-----|-----|-------|
| Trace an image | `/羽画 [preset]` + send image | preset and image order doesn't matter; the literal word `图片` is optional; presets: sketch / freehand / finebrush (default freehand) |
| Cap the size | `/羽画 --fit N` | target volume (MiB) with 2% tolerance; overshoot steps down colors first, then width |
| Trace an animation | send a GIF / WebP | automatically uses the motion preset → looping pure-CSS animation; very long ones (>30 s or 2500+ frames) prompt first |
| Animation sampling | `/羽画 --sample N` + a GIF/WebP | fixes the sampled frame count (8–96, clamped); without it, adaptive sampling applies (48-frame cap) |
| Natural language | say "make this a pure CSS illustration" after sending an image | triggers automatically (disable via config) |

Examples:

```
/羽画 速写
/羽画 工笔 --fit 20
```

> 💡 **Triggering**: works directly in private chat (with or without the `/` prefix); in group chats, @ the bot first.

## 🔄 Workflow

From the moment you send an image to the moment you receive the result, the plugin runs through this pipeline — understand it and troubleshooting gets much easier.
> Module names in brackets show where each step lives (see [Development](#development)): how the flow goes is here; what each module does is there.

```
User request (either entry)【main.py entry orchestration】
   ├─ Command entry: "/羽画 [preset] [--fit N] [--sample N]" + send an image
   │     (works directly in private chat; in group chats, @ the bot; preset order is free)
   └─ Natural-language entry: send an image and say "把这张图做成纯 CSS 插画" (llm_tool, optional)
   │
   ▼
① Grab & cache the image【main.py】
   ├─ Take the first image from the message (downloaded locally by the framework)
   └─ The user's most recent image is kept for 30 minutes — LLM-tool flows and the "继续" (continue) confirmation never need the original resent
   │
   ▼
② Parse options【options.py】
   └─ preset / --fit / --sample are recognized in any order ("/羽画 图片 工笔" is the same as "/羽画 工笔 图片")
   │
   ▼
③ Rate-limit gate【limiter.py】
   ├─ Global concurrency (concurrent, default 1): one job at a time, others queue
   └─ Per-user cooldown (cooldown, default 60s): blocked requests are told how long to wait
   │
   ▼
④ Input hardening【hardening.py】
   ├─ Size cap (max_image_mb, default 20 MiB)
   ├─ Decompression-bomb guard (max_pixels, default 40M)
   ├─ Animations: frame count read + duration estimate; over-long ones (>30 s or 2500 frames) are prompted before tracing, "继续" admits
   └─ Failed checks get human-friendly words; internal exceptions go to logs only
   │
   ▼
⑤ Tracing orchestration
   ├─ Static image【service.py trace_image】
   │     ├─ EXIF rotation → quantization → fragment merge → contour simplify → gradient fit → render → audit → atomic write
   │     ├─ Render backend (render_backend): css = pure CSS artwork (default, the product identity) | svg = inline SVG (optional dialect)
   │     └─ --fit N: over-budget jumps ladder steps directly from a size estimate (colors first, width last), no per-step full retries; the budget is judged on the **actual bytes produced**, so the same target usually steps down one rung less on the svg dialect
   └─ Animation【service_animation.py trace_animation】
         ├─ Sampling: --sample N (clamped 8–96) > motion_sample config > adaptive to duration (48-frame cap)
         ├─ Frame-to-frame layer tracking (deterministic greedy: IoU + color + centroid) → @keyframes timeline
         └─ Rendering style (animation_style): scanline (default; per-pixel, seamless) | vector (legacy pipeline, supports tween)
   │
   ▼
⑥ Contract audit & scoring【feather_art/audit.py · score.py】
   ├─ Audit red lines (per dialect): neither dialect allows <script> / <img> / Canvas / base64 / external links; the css dialect also forbids SVG, while the svg dialect allows only svg / g / defs / clipPath / path / linearGradient / stop plus same-document anchor references
   └─ Optional offline MAE similarity score (score, on by default)
   │
   ▼
⑦ Delivery【deliver.py】
   ├─ Summary text (human words, no raw paths) + a single-file HTML (readable filename: 羽画_工笔_0908-2214.html)
   └─ Failure layering: explainable errors get human words; internal exceptions go to logger with a fixed fallback line
```

## ⚙️ Configuration

Configurable from the AstrBot plugin panel:

| Key | Default | Description |
|-----|---------|-------------|
| `preset` | `freehand` | default preset (sketch / freehand / finebrush; the motion preset is picked automatically for animated input) |
| `fit_mb` | `64` | output volume target (MiB), 2% tolerance; `0` = no auto stepping |
| `max_mb` | `128` | hard output size cap (MiB) |
| `score` | `true` | compute the offline MAE similarity score |
| `motion_sample` | `0` | default animation sampling override: `0` = adaptive to duration (48-frame cap); 8–96 = fixed frame count |
| `animation_style` | `scanline` | animation rendering style: scanline (default; per-pixel, seamless at any zoom) | vector (legacy pipeline, supports tween) |
| `render_backend` | `css` | static trace backend: css = pure CSS artwork (default, the product identity) | svg = inline SVG (optional dialect: about half the bytes; the same artwork is pixel-identical across Chromium / Firefox / WebKit — measured on a single artwork at three widths; animations unaffected) |
| `concurrent` | `1` | simultaneous trace jobs |
| `cooldown` | `60` | per-user cooldown between traces (seconds) |
| `llm_tool` | `true` | natural-language entry switch |
| `max_image_mb` | `64` | input image size cap |
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

#### v0.3.3

- Fix: an image posted by someone else could come back as the requester's own older image — two requests in a row returned the same picture; an image inside a quoted message is now picked up, and a request only ever uses the image the requester themselves posted (if they haven't posted one, it says so instead)

#### v0.3.2

- Fix: with the inline-SVG dialect selected, the artifact no longer labels itself "pure CSS" in the browser tab and the screen-reader label — the title follows the actual dialect
- Quality: animation tracing now favours quality over size — full row-by-row, higher colour precision, no de-dithering; measured error down to 1/8 ~ 1/2 of before, at 2.1–2.6× the file size
- Quality: the finebrush preset traces wider (max width 1600 → 3600), so wide images keep more texture and gradient detail (measured: error down 13.7% at the original size, output 3.0× larger)
- Quality: the sketch and freehand presets also trace wider — max width 768 → 1152 and 1200 → 1600, so small images and everyday illustrations are no longer shrunk ahead of time (measured: error down 8–16% and 7–11% at the original size)
- Quality: looser size budgets — output target 40 → 64 MiB, hard cap 64 → 128 MiB, input tolerance 20 → 64 MiB
- Fix: switching the natural-language entry or the similarity score off in the WebUI used to be a no-op — the string `"false"` was swallowed silently; it really switches them off now
- Fix: internal failure text no longer reaches users — phrasing such as "file already exists: xxx.html" stays internal, and text written for users is no longer mistaken for an internal fault
- Docs: the help text and the startup log now mention the inline-SVG dialect (first-class since v0.3.0)

#### v0.3.1

- Fix: the animation size cap (`max_mb`) was not enforced on the default scanline style, so oversized output was delivered anyway; both animation paths honour it now — over the cap you just get told the limit, nothing is written
- Fix: wide, flat animations (banners, progress bars) used to fail outright; they trace normally now
- Tweak: slightly smaller animation stylesheets — same picture, smaller file

#### v0.3.0

- New: optional inline-SVG dialect — set `render_backend` to `svg` and the same image is traced into a single-file inline SVG at about half the size; the default stays pure CSS
- New: readable delivery filenames — `羽画_工笔_0908-2214.html` tells you at a glance which run it is
- Fix: v0.2.2 reported missing dependencies at every entry point and errored out on animation sampling — fixed here
- Fix: the offline similarity score is no longer inflated

#### v0.2.2

- New: adjustable animation sampling density — `--sample N` (8–96 frames) fixes how many frames are sampled, for smoothness or smaller output; the config key `motion_sample` can set a default

#### v0.2.1

- Performance: faster budget stepping — no more retrying every ladder step; size estimates jump straight to a fitting step, noticeably cutting the wait for heavy images
- Fix: after confirming a long animation, the original image no longer needs to be resent — each user's latest image is kept for 30 minutes; the prompt text is updated accordingly

#### v0.2.0

- Added: animation tracing — GIF / WebP → pure-CSS animation (frame-to-frame layer tracking + @keyframes timeline); new motion preset
- Fixed: legacy WebView rendering compatibility (dropped `aspect-ratio` / `min()` / `inset`); `color-scheme: light` prevents Android dark-mode inversion; kernels without `clip-path` support get a clear hint instead of garbage
- Fixed: conversion failure no longer leaks internal exception messages (which may contain server paths); malformed config values no longer reach the volume calculation layer
- Improved: animation frame cap 200 → 6000 (total-pixel budget guards); command parsing is order-independent; `--fit` steps colors first, width last; default budget 20 → 40 MiB

> Full history: [CHANGELOG.md](https://github.com/yuluo-feather/astrbot_plugin_feather_art/blob/main/CHANGELOG.md).

## 🌙 Known limits

- Photos, noise and dense textures produce large files; use `--fit` or a lighter preset
- **Determinism depends on the environment**: byte-identical output holds only within the dependency ranges in `requirements.txt` (OpenCV pinned to `≥4.10.0.84,<4.11`); for cross-environment reproduction, install a version in that range first
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
