# 羽画 · Changelog

> 每个版本条目均为中文在前、英文在后。

#### Unreleased

##### 🐛 修复

- **选中内联 SVG 方言后，成品的页签还自称「纯 CSS」**：配置切到 `svg` 描出来的文档，在浏览器页签和朗读标签上写的仍是「羽画 · 纯 CSS 描摹」。现在标题跟着实际方言走——SVG 稿自称「羽画 · SVG 描摹」，纯 CSS 稿一字未变

##### 🎨 画质

- **动图描摹改成画质优先**：不再把每两行压成一行（逐行还原）、颜色精度从 16 步提到 8 步，也不再做去抖动滤波——原本被抹平的抖动颗粒与细节都留了下来，画面明显更锐。六张真实动图实测误差降到原来的 1/8 ~ 1/2。代价是成品文件变成 **2.1~2.6 倍**（体积侧另有三笔改动先抵掉了一部分：行合并改取真实像素行、折叠相邻重复帧、写法紧凑化）
- **工笔档描得更细**：描摹宽度上限从 1600 一路提到 3600，宽图不再被提前缩掉，纹理与渐变的层次更贴原图（真实插画 3791×2000 实测：成品放回原图尺寸后与原图的误差降 13.7%，成品大 3.0 倍；4800 宽的摄影图同步受益）。宽度不到 1600 的图完全不受影响
- **速写与写意档也描得更细**：速写宽度上限 768 → 1152、写意 1200 → 1600，小图与日常插画不再被提前缩掉。三张真实插画实测（成品放回原图尺寸后与原图比）：速写误差降 8% ~ 16%、写意降 7% ~ 11%，成品大 98% ~ 126% 与 67% ~ 75%。宽度不到 768 / 1200 的图完全不受影响
- **体积预算放宽**：输出目标 40 → 64 MiB、硬上限 64 → 128 MiB、输入体积宽容 20 → 64 MiB。宽图与高保真档不再被预算提前削掉

**English**

##### 🐛 Fixes

- **The page title claimed "pure CSS" even for inline-SVG output**: with `render_backend` set to `svg`, the artifact still labelled itself "羽画 · 纯 CSS 描摹" in the browser tab and the screen-reader label. The title now follows the actual dialect — SVG output reads "羽画 · SVG 描摹", and pure-CSS output is unchanged

##### 🎨 Image quality

- **Animation tracing now favours quality over size**: no more averaging every two rows into one (full row-by-row), colour precision raised from 16-step to 8-step, and the de-dithering filter is gone — the dither texture and fine detail it used to smooth away are kept, so the picture is visibly sharper. Measured on six real GIFs: error is down to **1/8 ~ 1/2** of before. The cost is a **2.1–2.6× larger** file (three size-side changes already offset part of it: real pixel rows instead of averaging, repeated adjacent frames folded, tighter literals)
- **The finebrush preset traces finer**: its max tracing width goes 1600 → 3600, so wide images are no longer shrunk as aggressively and texture / gradient detail sits closer to the original (measured on a real 3791×2000 illustration: artifact scaled back to the original size and compared against it, error down 13.7%, output 3.0× larger; a 4800-wide photo benefits too). Images narrower than 1600 px are unaffected
- **The sketch and freehand presets trace finer too**: their max tracing widths go 768 → 1152 and 1200 → 1600, so small images and daily illustrations are no longer shrunk as aggressively. Measured on three real illustrations (artifact scaled back to the original size and compared against it): error down 8%–16% for sketch and 7%–11% for freehand, output 98%–126% and 67%–75% larger. Images narrower than 768 / 1200 px are unaffected
- **Looser size budgets**: output target 40 → 64 MiB, hard cap 64 → 128 MiB, input tolerance 20 → 64 MiB. Wide images and the fine-detail preset are no longer trimmed early by the budget

#### v0.3.1

##### 🐛 修复

- **动图的体积上限以前形同虚设**：扫描线风格（默认档）不受 `max_mb` 约束，超限成品会照样发出来（实测一张 48 帧动图能产出 76 MiB 的文件）。现在两条动画线一视同仁：超限只把结果告诉你，不再落盘、不再发送
- **细长条幅动图描不出来**：横幅、进度条这类又宽又扁的动图会整单失败，现在能正常描完

##### ⚡ 性能

- **动图样式体积略降**：矢量风格不再逐个关键帧重复声明同一种颜色，同样的画面文件更小

**English**

##### 🐛 Fixes

- **The animation size cap was not actually enforced**: the scanline style (the default) ignored `max_mb`, so oversized output was delivered anyway — a 48-frame animation measured at 76 MiB. Both animation paths honour it now: over the cap, you get told the limit and nothing is written or sent
- **Wide, flat animations failed to trace**: banner and progress-bar style GIFs made the whole job fail. They trace normally now

##### ⚡ Performance

- **Slightly smaller animation stylesheets**: the vector style no longer repeats the same colour on every keyframe — same picture, smaller file

#### v0.3.0

##### ✨ 新功能

- **可选的内联 SVG 方言**：配置项 `render_backend` 可选 `svg`——同一张图描成内联 SVG 单文件，体积约为纯 CSS 插画的一半（同一份几何实测）；Chromium / Firefox / WebKit 三个内核里逐位一致。默认仍是纯 CSS 插画，一个字节都没动
- **交付文件名可读化**：`羽画_工笔_feather_1788695429_a1b502bc.html` 变成 `羽画_工笔_0908-2214.html`，只留哪天哪一分钟

##### 🐛 修复

- **修复 v0.2.2 装不上**：那一版的包内容有缺漏，装上后**所有入口**都误报「缺少依赖」，动图指定采样帧数还会直接报错。本版补齐
- **离线相似度评分修正**：报出的 MAE 不再虚报，回到可信区间

**English**

##### ✨ New features

- **Optional inline-SVG dialect**: the `render_backend` config key accepts `svg` — the same image is traced into a single-file inline SVG at roughly half the size of the pure-CSS artwork (measured on identical geometry), pixel-identical across Chromium / Firefox / WebKit. The default stays pure CSS, unchanged
- **Readable delivery filenames**: `羽画_工笔_feather_1788695429_a1b502bc.html` becomes `羽画_工笔_0908-2214.html` — day and minute, nothing else

##### 🐛 Fixes

- **v0.2.2 could not be installed**: that release was missing pieces, so every entry point wrongly reported missing dependencies and animations with a fixed sampling count errored out. Fixed here
- **Offline similarity score corrected**: the reported MAE is no longer inflated

#### v0.2.2

##### ✨ 新功能

- **动画采样密度可调**：`--sample N`（8~96 帧，越界钳制）固定动画采样帧数——想要更流畅就拉高（如 10 秒动图采 96 帧 ≈ 9.6 帧/秒），想省体积就压低；不传则保持按时长自适应（上限 48 帧），也可用配置项 `motion_sample` 设默认值

**English**

##### ✨ New features

- **Adjustable animation sampling density**: `--sample N` (8–96 frames, clamped) fixes how many frames an animation is sampled with — raise it for smoothness (e.g. a 10 s animation sampled at 96 frames ≈ 9.6 fps), lower it for size; without it, duration-adaptive sampling stays (48-frame cap), and the config key `motion_sample` can set a default

#### v0.2.1

##### ⚡ 性能

- **超预算降档提速**：`--fit` 模式下输出超预算时不再逐个档位完整重试（大图原来要重试 6~7 次才降到位），改为按体积估算直接跳档，降档过程的总等待时间明显缩短

##### 🔧 修复

- **长动图确认流程**：回复「继续」后无需重发原图（每个用户的最近一张图自动保留 30 分钟），提示文案同步更新

**English**

##### ⚡ Performance

- **Faster budget stepping**: when the output exceeds the budget, --fit no longer retries every ladder step with a full render; it now jumps directly based on a size estimate, cutting the total wait for heavy images noticeably (previously up to 6–7 failed renders)

##### 🔧 Fixes

- **Long-animation confirmation**: after replying "继续" (continue), the original image does not need to be resent — each user's latest image is kept for 30 minutes; the prompt text is updated accordingly

#### v0.2.0

##### ✨ 新功能

- **动图描摹**：GIF / WebP 动图 → 纯 CSS 动画单文件（帧间图层跟踪 + @keyframes 时间线），浏览器直接循环播放——图层跟踪用确定性贪心（IoU + 颜色 + 质心打分），不按序号硬对齐；缺失帧锚定上一帧特征，不闪烁；默认硬切（step-end），可选顶点对齐补间。独立 motion 档（512 宽 / 96 色 / ε0.36 / 2 轮 / 采样上限 48 帧），按时长自适应（目标约 4 帧/秒、下限 8 帧）——短动画近全帧还原节奏，长动画按上限兜底，不再出现「2000+ 帧动图隔 5 秒跳一帧」的鬼畜感。动画抗诡异三件套（长动图 2000+ 帧实测校准）：实例阈值 2 → 8 像素（量化碎块不再当独立物体，图层数从 2000+ 降到几十条量级）；短轨迹过滤（闪现 1–2 帧的碎片层直接丢弃）；轨迹级固定色（跨帧色板漂移消除，颜色跨帧恒定）。超长动图先提示后描摹（估算时长 > 30 秒或 2500 帧以上时先给「建议用原 GIF / 剪 10~15 秒片段」提示，回复「继续」才放行）。输出契约审计同步扩展（layer 类名与 @keyframes 引用校验）
- **指令解析顺序无关**：`/羽画 工笔 图片` 与 `/羽画 图片 工笔` 等价，档位随写随认，`图片` 二字可省略
- **超预算降档策略调整**：「颜色优先、宽度兜底」——先削色板、再缩宽度，精细档在相同体积预算下保住分辨率，三档差距更明显
- **输出体积预算放宽**：`fit_mb` 由 20 提到 40 MiB，工笔默认即可满配（1600 宽 / 256 色）；新增 2% 容差，卡线（如超 0.5%）不再触发整级降档重跑

##### 🔧 修复

- **移动端/旧浏览器渲染失败**：不再使用 `clip-path: polygon(evenodd, …)`——fill-rule 参数在 Chromium 88 之前的 WebView 里不被解析，整条 clip-path 失效会让成品退化成色块堆叠；改为「方向归一化 + 零面积桥」走 nonzero 绕数填充，挖孔效果等价、兼容面反而更宽
- **模板替换同年代新特性**：`aspect-ratio` 改 `::before` padding-top 撑高、`min()` 改 `max-width`、`inset` 改四边显式定位（旧内核全部认得）
- **深色模式反向调色**：输出声明 `color-scheme: light`，阻止 Android 自动深色模式反向调色；动画页补上缺失的 viewport meta
- **内核兜底提示**：不认 `clip-path: polygon(...)` 的老 WebView / 文件管理器预览器不再花屏，改为明确提示「用 Chrome / Edge / Firefox 或电脑打开」（提示层默认显示、支持 clip-path 的内核自动隐藏，极老内核也兜得住）
- **动图跨帧轨迹锚定**：轨迹首次出现在非首帧时，渲染只补齐第 0 帧、其余空槽仍是 None → 渲染崩溃；改为全部空槽锚定首个特征，此前会失败的动图现在能正常描完
- **动图防线按成本重校**：帧数上限 200 → 6000（管线均匀采样 ≤16 帧描摹，头解析便宜，帧数本身不是成本；真正成本炸弹「帧数 × 单帧像素」仍由总像素预算兜底）——2000+ 帧的普通动图不再被误拒
- **安全修复**：转换失败时不再把内部异常消息（可能含服务器路径）展示给用户，一律走固定友好文案，细节只进日志
- **安全修复**：畸形配置值（字符串/负数）不再穿透到体积计算层；冷却记录增加过期清理
- **兼容性回归锁定**：nonzero 孔洞存活、内外环方向相反断言、模板无新特性残留、改后审计仍通过

**English**

##### ✨ New features

- **Animation tracing**: GIF / WebP → a single-file pure-CSS animation (frame-to-frame layer tracking + @keyframes timeline) that the browser plays in a loop — tracking is a deterministic greedy scorer (IoU + color + centroid), not per-frame index alignment; missing frames anchor to the previous frame's features (no flicker); hard-cut (step-end) by default with optional vertex-aligned tweening. A dedicated motion preset (512 wide / 96 colors / ε0.36 / 2 passes / up to 48 sampled frames) adapts to duration (~4 fps target, 8-frame floor) — short animations keep their rhythm nearly frame-for-frame, long ones cap at the budget instead of the old "one frame every 5 seconds" stutter. The anti-weirdness trio, calibrated on 2000+ frame animations: instance threshold 2 → 8 px (quantization debris no longer counts as an object; layer count drops from 2000+ to tens); short-track filtering (1–2 frame flickers dropped); track-level fixed colors (cross-frame palette drift eliminated, colors stay constant). Very long animations prompt first (>30 s or 2500+ frames: "use the original GIF or trim a 10–15 s clip"; tracing runs after you confirm); the contract audit now also validates layer class names and @keyframes references
- **Order-independent command parsing**: `/羽画 工笔 图片` and `/羽画 图片 工笔` are equivalent; the preset word is recognized anywhere, the literal `图片` is optional
- **New overshoot ladder**: colors first, width last — finer presets keep their resolution within the same budget; the presets now differ more clearly
- **Looser default budget**: `fit_mb` raised 20 → 40 MiB (finebrush fully fits at defaults: 1600 wide / 256 colors), plus a 2% tolerance so borderline overshoots (e.g. +0.5%) no longer trigger a full re-run at a lower tier

##### 🔧 Fixes

- **Mobile / legacy rendering failure**: dropped `clip-path: polygon(evenodd, …)` — the fill-rule argument is not parsed in WebViews before Chromium 88, and a dead clip-path degrades the artwork into color blobs; replaced with "direction normalization + zero-area bridge" using nonzero fill — hole carving is equivalent and compatibility is wider
- **Template upgraded to era-safe CSS**: `aspect-ratio` → `::before` padding-top, `min()` → `max-width`, `inset` → explicit four-side positioning (recognized by old engines)
- **Dark-mode inversion**: outputs now declare `color-scheme: light` so Android auto dark mode no longer inverts the palette; animation pages gained the missing viewport meta
- **Kernel fallback hint**: old WebViews / file-manager previewers that don't know `clip-path: polygon(...)` no longer show garbage — they get a clear "use Chrome / Edge / Firefox or open on a desktop" hint (shown by default, auto-hidden on capable engines, held even by very old kernels)
- **Cross-frame track anchoring**: when a track first appears on a non-first frame, the renderer filled only frame 0 and left later slots as None → crash; every empty slot now anchors to the first feature, so animations that used to fail trace to completion
- **Animation guard re-costed**: frame cap 200 → 6000 (sampling ≤16 frames for tracing; header parsing is cheap — frame count itself is not the cost; the real bomb, frames × pixels-per-frame, is still capped by the total-pixel budget) — 2000+ frame animations are no longer rejected by mistake
- **Security fix**: conversion failure no longer shows internal exception messages (which may contain server paths) — a fixed friendly message instead, details go to logs only
- **Security fix**: malformed config values (strings / negatives) no longer reach the volume-calculation layer; cooldown records now expire
- **Compatibility regression lock**: nonzero hole survival, opposing inner/outer ring directions, no leftover era-unsafe template features, audit still passing after the changes

#### v0.1.0

初始版本。

##### ✨ 新功能

- **图片 → 纯 HTML + CSS 单文件插画描摹**：离线，无 API 依赖——Oklab 感知量化、碎块邻接合并、4x 亚像素轮廓、偶奇孔洞桥接、局部渐变、48 色底板、输出契约审计（禁脚本 / 图片 / 外链 / base64）与离线 MAE 评分
- **三档精度**：速写 / 写意 / 工笔（sketch / freehand / finebrush）
- **`--fit` 体积预算**：超预算自动逐档降精度直到装得下
- **插件双入口**：`/羽画` 命令 + 自然语言 LLM 工具
- **输入防护**：体积上限、像素炸弹防线、动图拒绝
- **限流**：全局并发 1 + 每用户 60s 冷却
- **测试**：pytest 套件覆盖核心管线与防护

**English**

Initial release.

##### ✨ New features

- **Image → single-file HTML + CSS illustration tracing**: offline, no API dependency — Oklab perceptual quantization, adjacency-constrained small-region merging, 4x subpixel contours, even-odd hole bridging, local gradients, 48-color underpainting, output contract audit (no scripts / images / external links / base64) and offline MAE scoring
- **Three presets**: sketch / freehand / finebrush
- **`--fit` volume budget**: automatically steps down presets until the output fits
- **Dual entry points**: `/羽画` command + natural-language LLM tool
- **Input hardening**: size caps, pixel-bomb guard, animation rejection
- **Throttling**: global concurrency 1 + 60s per-user cooldown
- **Tests**: pytest suite covering the core pipeline and hardening
