# 羽画 · 羽画插件

把参考图片**离线描摹**成纯 HTML + CSS 单文件插画。打开成品只需浏览器：
动图（GIF / WebP）可描成**纯 CSS 动画**——帧间图层跟踪 + @keyframes 时间线，浏览器直接循环播放。
没有 `<img>`、没有 SVG、没有 Canvas、没有 JavaScript、没有 base64、没有外部资源。

- ✅ 保留原图比例，CSS `clip-path` 绘制轮廓、孔洞与细线
- ✅ 较大色块内拟合局部渐变，内层 48 色底板压住缩小观看时的浅色接缝
- ✅ Oklab 感知色彩空间量化，色带与细节丢失更少
- ✅ 输出有契约审计（无脚本/外链/图片注入），离线 MAE 评分
- ✅ 确定性：相同输入、参数与依赖环境产出逐字节一致的 HTML

## 档位

| 档位 | 描摹宽度上限 | 调色板 | 轮廓简化 | 合并轮数 | 适合 |
| --- | ---: | ---: | ---: | ---: | --- |
| 速写 | 768 | 96 | 0.38 | 2 | 小图、表情包、印章，快而轻 |
| 动画 | 512 | 96 | 0.36 | 2 | 动图专用：多帧描摹，快而稳 |
| 写意（默认） | 1200 | 160 | 0.30 | 3 | 日常插画，均衡之选 |
| 工笔 | 1600 | 256 | 0.24 | 4 | 细节优先，输出更大更慢 |

## 安装

1. 把 `astrbot_plugin_feather_art` 目录放进 `data/plugins/`
2. 安装依赖（生成阶段需要，查看 HTML 不需要）：

```powershell
<python 环境>\Scripts\python.exe -m pip install -r requirements.txt
```

3. 重启 AstrBot（或在 WebUI 重载插件）

系统要求：Python 3.12+；NumPy / Pillow / OpenCV（headless）。

## 使用

- 命令：`/羽画 [档位] [--fit N]` + 发一张图（档位与图片顺序随意，`图片` 二字可省略）
  - 档位：`速写` / `写意` / `工笔`（默认写意）
  - `--fit N`：目标体积（MiB）；超预算自动降档（先降颜色、后降宽度）直到装得下
- 自然语言：发图后说「把这张图做成纯 CSS 插画」即可触发（可在配置中关闭）
- 动图：发 GIF / WebP 动图自动走动画档，描成可循环播放的纯 CSS 动画
- 群聊：@ 机器人后发送

示例：

```
/羽画 速写
/羽画 工笔 --fit 20
```

## 配置（WebUI 可改）

| 键 | 默认 | 说明 |
| --- | --- | --- |
| preset | freehand | 默认档位（sketch / freehand / finebrush） |
| fit_mb | 40 | 输出体积目标（MiB），含 2% 容差；0 = 不自动降档 |
| max_mb | 64 | 输出体积硬上限（MiB） |
| score | true | 是否离线计算 MAE 相似度 |
| concurrent | 1 | 同时进行的描摹任务数 |
| cooldown | 60 | 同一用户相邻描摹冷却秒数 |
| llm_tool | true | 自然语言入口开关 |
| max_image_mb | 20 | 输入图片体积上限 |
| max_pixels | 40000000 | 输入图片总像素上限（防解压炸弹） |

## 原理（管线）

1. EXIF 转正 → 透明按底色合成 → 限宽缩放 → 双边滤波
2. Oklab 感知空间盒式中位切分量化（无抖动）
3. 碎块（<16px）只并入相邻、更大且颜色相近的色块（色差 ≤18，累计漂移 ≤23）
4. 4x 亚像素采样轮廓，轻微膨胀、平滑、简化
5. 孔洞与孤岛用偶奇多边形（零面积桥接）承载
6. 大色块拟合一阶线性渐变，小碎块按网格聚组减少元素数
7. 48 色低分辨率底板铺底
8. 生成单文件 HTML 并跑契约审计

## 开发

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

## 已知限制

- 照片、噪点与纹理密集的图会生成大文件；建议用 `--fit` 或换低档
- 超长动图（估算时长 > 30 秒或 2500 帧以上）会先提示建议用原 GIF 或剪 10~15 秒片段，确认后才描摹
- 透明背景会合成到指定底色（默认白）
- 宽色域 / CMYK 来源建议先转 sRGB
- 审计验证结构，不替代肉眼对比；渲染开销与设备内存相关

## 致谢

- 静态描摹管线（量化 / 合并 / 轮廓 / 渐变）算法思路参考
  [AvroraCL/image-to-css-art](https://github.com/AvroraCL/image-to-css-art)（MIT）；
- 动图 → 纯 CSS 动画的方向启发自
  [kevinjycui/css-video](https://github.com/kevinjycui/css-video)——我们用帧间
  图层跟踪（IoU + 颜色 + 质心匹配）替代其帧内聚块 + 序号对齐，实现为独立设计，未复制其代码；
- [javierbyte/img2css](https://github.com/javierbyte/img2css) 作为经典对照
  （每像素 box-shadow 路径），本插件未采用该方案。

以上均为思路参考，无代码复制；第三方依赖遵循各自许可证，输入图片与派生内容的权利不因使用本插件而改变。

## 许可

[AGPL-3.0](LICENSE)
