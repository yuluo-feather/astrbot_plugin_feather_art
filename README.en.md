# 羽画 · Feather Art

Turns a reference image into a **standalone HTML + CSS illustration**, fully offline.
Animated GIF / WebP can be traced into a **pure-CSS looping animation**
(@keyframes timeline with frame-to-frame layer tracking).
Open the result in any modern browser: no `<img>`, no SVG, no Canvas, no JavaScript,
no base64, no external assets.

- ✅ Keeps aspect ratio; CSS `clip-path` polygons carry contours, holes and fine lines
- ✅ Local linear gradients inside large regions, plus a 48-color underpainting layer
- ✅ Oklab perceptual quantization — less banding and detail loss at the same budget
- ✅ Contract audit (no scripts / imagery / external resources) and offline MAE scoring
- ✅ Deterministic: identical input, parameters and dependency versions produce
  byte-identical HTML

## Presets

| Preset | Max width | Palette | Epsilon | Merge passes | Notes |
| --- | ---: | ---: | ---: | ---: | --- |
| sketch · 速写 | 768 | 96 | 0.38 | 2 | light & fast; icons, memes, stamps |
| freehand · 写意 (default) | 1200 | 160 | 0.30 | 3 | daily illustrations, balanced |
| motion · 动画 | 512 | 96 | 0.36 | 2 | animated GIF / WebP: multi-frame tracing, fast & stable |
| finebrush · 工笔 | 1600 | 256 | 0.24 | 4 | detail first; larger & slower |

## Install

1. Put `astrbot_plugin_feather_art` into `data/plugins/`
2. Install authoring dependencies:

```powershell
<python>\Scripts\python.exe -m pip install -r requirements.txt
```

3. Restart AstrBot (or reload the plugin from the WebUI)

Requires Python 3.12+; authoring deps are NumPy / Pillow / OpenCV (headless).

## Usage

- Animated GIF / WebP: traced into a **pure-CSS looping animation** (motion preset, layer tracking + @keyframes) (`速写`/`写意`/`工笔`, default `写意`; preset and image order doesn't matter, the literal word `图片` is optional)
- Natural language: send an image and say "make this a pure CSS illustration"
  (disable via config)
- When `--fit` is exceeded, the ladder steps down **colors first, width last**,
  so finer presets keep their resolution within the same budget
- Group chat: @ the bot first

## Config (WebUI)

preset / fit_mb (default 40, 2% tolerance, 0 = off) / max_mb (64) / score (true) / concurrent (1) /
cooldown (60s) / llm_tool (true) / max_image_mb (20) / max_pixels (40M).

## Pipeline

EXIF → matte composite → downscale → bilateral filter → Oklab median-cut quantization →
adjacency-constrained small-region merging → 4x subpixel contours → even-odd holes →
local gradients → 48-color underpainting → single-file HTML + contract audit.

## Known limits

- Photos, noise and dense textures produce large files; use `--fit` or a lighter preset
- Very long animations (>30 s or 2500+ frames) get a prompt first: use the original GIF or trim a 10-15 s clip, and tracing runs only after you confirm
- Transparent PNG is composited onto the matte (default white)
- Wide-gamut / CMYK sources: convert to sRGB first
- The audit checks structure, not visual similarity — always eyeball the result

## Credits

- Static tracing pipeline (quantization / merging / contours / gradients) is inspired by
  [AvroraCL/image-to-css-art](https://github.com/AvroraCL/image-to-css-art) (MIT);
- The *animated GIF/WebP → pure-CSS animation* idea is inspired by
  [kevinjycui/css-video](https://github.com/kevinjycui/css-video) — we replaced its
  per-frame clustering + index alignment with frame-to-frame layer tracking
  (IoU + color + centroid matching); an independent design, no code copied;
- [javierbyte/img2css](https://github.com/javierbyte/img2css) is kept as a classic
  reference (per-pixel box-shadow path), which this plugin does not follow.

Inspiration only; no code was copied. Third-party dependencies keep their own licenses;
rights over input images and derived content are unaffected by using this plugin.

## License

[AGPL-3.0](LICENSE)
