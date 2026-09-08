<p align="center">
  <img src="https://raw.githubusercontent.com/yuluo-feather/astrbot_plugin_feather_art/main/logo_small.png" width="110" height="110" align="middle"/> <font size="6"><b>羽画 Feather Art 🪶</b></font>
</p>

<p align="center">
  「把图交给我，还你一个只靠 HTML + CSS 就能打开的画。哼，联网都不必。」—— 本羽
</p>

<p align="center">
  <a href="https://github.com/yuluo-feather/astrbot_plugin_feather_art/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-AGPL%20v3-ffb3d9" alt="License: AGPL v3"/></a>
  <a href="https://astrbot.app"><img src="https://img.shields.io/badge/AstrBot-Plugin-ff9ecb" alt="AstrBot Plugin"/></a>
  <img src="https://img.shields.io/badge/version-v0.2.2-f8a5c2" alt="v0.2.2"/>
</p>

<p align="center">🪶 ✨ 🎨 🎬</p>

> [English](https://github.com/yuluo-feather/astrbot_plugin_feather_art/blob/main/README.en.md) | [简体中文](https://github.com/yuluo-feather/astrbot_plugin_feather_art/blob/main/README.md)

---

## 📖 目录

- 🎨 [功能特点](#功能特点)
- 🎚️ [档位](#档位)
- 🖊️ [使用](#使用)
- ⚙️ [配置项](#配置项)
- ⚗️ [工作原理](#工作原理)
- 📦 [安装方法](#安装方法)
- 🛠️ [开发](#开发)
- 📜 [更新记录](#更新记录)
- 🌙 [已知限制](#已知限制)
- ⭐ [致谢](#致谢)

---

一款基于 AstrBot 的描图插件，本羽亲手写的。把图片**离线描摹**成纯 HTML + CSS 单文件插画——没有 `<img>`、没有 SVG、没有 Canvas、没有 JavaScript、没有 base64、没有外部资源，打开它只需要一个浏览器。动图（GIF / WebP）也能描成**纯 CSS 动画**，帧间图层跟踪 + @keyframes 时间线，浏览器直接循环播放。

## 🎨 功能特点

- 🖼️ **离线描摹**：位图 → 单文件 HTML 插画，全程本地计算，不依赖任何 API
- 🎬 **动图描摹**：GIF / WebP → 纯 CSS 动画，帧间图层跟踪（IoU + 颜色 + 质心打分）跨帧锚定，不闪烁
- 🎨 **感知量化**：Oklab 色彩空间盒式中位切分；大色块拟合局部渐变 + 内层 48 色底板，色带与细节丢失更少
- 🎚️ **四档精度**：速写 / 动画 / 写意（默认）/ 工笔；`--fit` 体积预算超了自动降档——**先削颜色、再缩宽度**，精细档保得住分辨率
- 🛡️ **契约审计**：成品过审计（无脚本 / 图片 / 外链 / base64 注入），附离线 MAE 相似度评分
- ⚖️ **确定性**：相同输入、参数与依赖环境，产出逐字节一致——不搞随机，不玩玄学
- 🤖 **双入口**：`/羽画` 命令 + 自然语言（发图说「把这张图做成纯 CSS 插画」即可触发，可在配置中关闭）
- 🚦 **防护与限流**：输入体积上限 / 像素炸弹防线 / 多帧检查；全局并发 1 + 每用户 60s 冷却

## 🎚️ 档位

| 档位 | 描摹宽度上限 | 调色板 | 轮廓简化 | 合并轮数 | 适合 |
| --- | ---: | ---: | ---: | ---: | --- |
| 速写 | 768 | 96 | 0.38 | 2 | 小图、表情包、印章，快而轻 |
| 动画 | 512 | 96 | 0.36 | 2 | 动图专用：多帧描摹，快而稳 |
| 写意（默认） | 1200 | 160 | 0.30 | 3 | 日常插画，均衡之选 |
| 工笔 | 1600 | 256 | 0.24 | 4 | 细节优先，输出更大更慢 |

## 🖊️ 使用

| 功能 | 命令 | 说明 |
|------|------|------|
| 描摹图片 | `/羽画 [档位]` + 发图 | 档位与图片顺序随意，`图片` 二字可省略；档位：速写 / 写意 / 工笔（默认写意） |
| 控制体积 | `/羽画 --fit N` | 目标体积（MiB），含 2% 容差；超预算自动降档（先颜色、后宽度）直到装得下 |
| 描摹动图 | 发 GIF / WebP 动图 | 自动走动画档，描成可循环播放的纯 CSS 动画；超长动图（>30 秒或 2500 帧）先提示后描摹 |
| 动画采样密度 | `/羽画 --sample N` + 发动图 | 固定采样 N 帧（8~96，越界钳制）；不传按按时长自适应（上限 48 帧） |
| 自然语言 | 发图后说「把这张图做成纯 CSS 插画」 | 即可触发（可在配置中关闭） |

示例：

```
/羽画 速写
/羽画 工笔 --fit 20
```

> 💡 **触发规则**：私聊直接说即可（带 `/` 前缀也行）；群聊 `@机器人` 后发送。

## ⚙️ 配置项

在 AstrBot 插件管理界面中配置：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `preset` | `freehand` | 默认档位（sketch / freehand / finebrush；动画档由动图输入自动选择） |
| `fit_mb` | `40` | 输出体积目标（MiB），含 2% 容差；`0` = 不自动降档 |
| `max_mb` | `64` | 输出体积硬上限（MiB） |
| `score` | `true` | 是否离线计算 MAE 相似度 |
| `motion_sample` | `0` | 动画采样帧数默认覆盖：`0` = 按时长自适应（上限 48 帧）；8~96 = 固定采样 |
| `concurrent` | `1` | 同时进行的描摹任务数 |
| `cooldown` | `60` | 同一用户相邻描摹冷却秒数 |
| `llm_tool` | `true` | 自然语言入口开关 |
| `max_image_mb` | `20` | 输入图片体积上限 |
| `max_pixels` | `40000000` | 输入图片总像素上限（防解压炸弹） |

## ⚗️ 工作原理

1. EXIF 转正 → 透明按底色合成 → 限宽缩放 → 双边滤波
2. Oklab 感知空间盒式中位切分量化（无抖动）
3. 碎块（<16px）只并入相邻、更大且颜色相近的色块（色差 ≤18，累计漂移 ≤23）
4. 4x 亚像素采样轮廓，轻微膨胀、平滑、简化
5. 孔洞与孤岛用偶奇多边形（零面积桥接）承载
6. 大色块拟合一阶线性渐变，小碎块按网格聚组减少元素数
7. 48 色低分辨率底板铺底
8. 生成单文件 HTML 并跑契约审计

动图输入额外走一层：采样（按时长自适应，目标约 4 帧/秒）→ 帧间图层跟踪（确定性贪心：IoU + 颜色 + 质心打分）→ 缺失帧锚定上一帧特征 → @keyframes 时间线（默认硬切，可选顶点对齐补间）。

## 📦 安装方法

### 方式一：通过 GitHub 仓库地址安装

1. 打开 AstrBot 管理面板，进入「插件市场 / 安装插件」
2. 选择「从 GitHub 仓库地址安装」，填入：

   `https://github.com/yuluo-feather/astrbot_plugin_feather_art`

3. 点击安装，等待插件下载并自动安装依赖

### 方式二：手动安装

1. 将本仓库克隆或下载到 AstrBot 的 `data/plugins/` 目录下，目录名保持为 `astrbot_plugin_feather_art`：

   ```bash
   cd AstrBot/data/plugins
   git clone https://github.com/yuluo-feather/astrbot_plugin_feather_art.git
   ```

2. 安装依赖（生成阶段需要，查看 HTML 不需要）：

   ```powershell
   <python 环境>\Scripts\python.exe -m pip install -r requirements.txt
   ```

3. 重启 AstrBot（或在 WebUI 重载插件）

**运行环境**：Python 3.12+；依赖 NumPy / Pillow / OpenCV（headless）。

## 🛠️ 开发

```
feather_art/          # 算法包：成像/量化/合并/几何/渐变/渲染/审计/评分
service.py            # 编排：静态描摹、fit 阶梯、原子落盘、报告
service_animation.py  # 编排：动图描摹（采样/图层跟踪/动画渲染）
hardening.py          # 输入防护：体积、像素炸弹、多帧
limiter.py            # 并发 + 每用户冷却
deliver.py            # 报告文案与文件链
main.py               # 插件入口（命令 + 自然语言）
config.py             # 配置默认值与读取
tests/                # pytest 用例（随开发增长）
```

```powershell
<python 环境>\Scripts\python.exe -m pytest tests -q
```

## 📜 更新记录

#### v0.2.2

- 新增：动画采样密度可调——`--sample N`（8~96 帧）固定动画采样帧数，更流畅或更省体积由你定；配置项 `motion_sample` 可设默认值

#### v0.2.1

- 性能：超预算降档提速——不再逐档完整重试，改为体积估算直接跳档，大图降档等待时间明显缩短
- 修复：长动图确认后无需重发原图（每个用户的最近一张图保留 30 分钟），提示文案同步更新

#### v0.2.0

- 新增：动图描摹——GIF / WebP → 纯 CSS 动画（帧间图层跟踪 + @keyframes 时间线），新增动画档
- 修复：老 WebView 渲染兼容（去 `aspect-ratio` / `min()` / `inset` 依赖）；`color-scheme` 固定浅色防深色模式反向调色；不认 `clip-path` 的内核改为明确提示
- 修复：转换失败不再把内部异常消息（可能含服务器路径）透出；畸形配置值不再穿透到体积计算层
- 改进：动图帧数上限 200 → 6000（总像素预算兜底）；指令解析顺序无关；`--fit` 改「颜色优先、宽度兜底」；默认体积预算 20 → 40 MiB

> 完整更新日志见 [CHANGELOG.md](https://github.com/yuluo-feather/astrbot_plugin_feather_art/blob/main/CHANGELOG.md)。

## 🌙 已知限制

- 照片、噪点与纹理密集的图会生成大文件；建议用 `--fit` 或换低档
- **确定性依赖环境**：逐字节一致仅在依赖版本区间内成立（OpenCV 锁定 `≥4.10.0.84,<4.11`，见 `requirements.txt`）；跨环境复现请先安装该区间内的版本
- 超长动图（估算时长 > 30 秒或 2500 帧以上）会先提示建议用原 GIF 或剪 10~15 秒片段，确认后才描摹
- 透明背景会合成到指定底色（默认白）
- 宽色域 / CMYK 来源建议先转 sRGB
- 审计验证结构，不替代肉眼对比；渲染开销与设备内存相关

---

## ⭐ 致谢

- 静态描摹管线（量化 / 合并 / 轮廓 / 渐变）算法思路参考 [AvroraCL/image-to-css-art](https://github.com/AvroraCL/image-to-css-art)（MIT）
- 动图 → 纯 CSS 动画的方向启发自 [kevinjycui/css-video](https://github.com/kevinjycui/css-video)——我们用帧间图层跟踪（IoU + 颜色 + 质心匹配）替代其帧内聚块 + 序号对齐，实现为独立设计，未复制其代码
- [javierbyte/img2css](https://github.com/javierbyte/img2css) 作为经典对照（每像素 box-shadow 路径），本插件未采用该方案

以上均为思路参考，无代码复制；第三方依赖遵循各自许可证，输入图片与派生内容的权利不因使用本插件而改变。

## 许可

[AGPL-3.0](LICENSE)
