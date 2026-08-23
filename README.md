# 字幕生成工具

从任意视频的音轨生成字幕：自动识别语种、支持多音轨选择，并可翻译成你要的目标语言。
全程本地运行，不上传任何内容。

- 🎬 **任意视频** — MP4 / MKV / MOV / AVI / TS / WebM…，也直接吃音频文件
- 🔊 **多音轨** — 列出片源里的每条音轨（含语言标签），按需选择
- 🌍 **多语种** — 自动识别 99 种语言；一条音轨里多语言混说也能逐段识别
- 🈯 **任选目标语言** — 99 种目标语言，可输出译文 / 原文 / 双语对照
- 📄 **SRT / VTT / TXT**，批量处理，可随时取消
- 🔌 **离线可用** — 首次下载模型后完全断网运行

## 快速开始

1. 到 [Releases](https://github.com/liny90626/subtitle_tool/releases) 下载
   `subtitle-tool-windows-x64.zip`
2. 解压到任意目录，双击 `字幕生成工具.exe`（免安装）
3. 把视频拖进窗口 → 选音轨和目标语言 → 点「开始生成」

首次运行会自动下载模型（识别模型按所选大小 75MB~1.6GB，翻译模型 620MB），
之后一直复用。默认存放在 `%USERPROFILE%\.cache\huggingface`。

![界面](docs/screenshot.png)

## 选哪个识别模型

在 8 核 CPU（int8 量化，无 GPU）上的实测速度：

| 模型 | 下载体积 | 速度（相对实时） | 适用 |
| --- | --- | --- | --- |
| `base` | 145 MB | 快 | 试跑、对速度要求高 |
| `small` | 484 MB | 中 | 日常够用 |
| `large-v3-turbo` | 1.6 GB | 慢 | **默认**，精度最好，推荐配 GPU |

> 具体耗时随 CPU 核数、视频长度浮动。1 小时的视频用 `small` 在普通笔记本上大致
> 十几到几十分钟；配 NVIDIA 显卡可快一个数量级。

## 用 GPU 加速

免安装包只带 CPU 推理（带上 CUDA 运行库会让体积从 500MB 涨到 3GB）。
有 NVIDIA 显卡的话，装好 CUDA 12 运行库后程序会自动检测并使用：

```powershell
pip install nvidia-cublas-cu12 nvidia-cudnn-cu12
```

把这两个包安装目录里的 DLL 放到程序目录，或改用下面的源码方式运行。
设置里的「设备」保持「自动」即可，检测不到显卡会自动退回 CPU。

## 命令行用法

批量处理和脚本化用命令行更方便：

```bash
# 列出音轨
subtitle-tool video.mkv --list-tracks

# 用第 2 条音轨，生成中文字幕
subtitle-tool video.mkv --track 2 --target zh

# 多语言混说的音轨，输出中英双语 SRT + VTT
subtitle-tool video.mkv --multi-language --target zh --layout bilingual --format srt,vtt

# 批量处理整个目录
subtitle-tool *.mp4 --target ja --model small --output-dir ./subs
```

`--target` 接受 `zh` / `zho_Hans` / `中文（简体）` 三种写法，
`--list-languages` 可以看全部可选语言。

## 从源码运行

```bash
git clone https://github.com/liny90626/subtitle_tool.git
cd subtitle_tool
pip install -e ".[gui]"

subtitle-tool-gui          # 图形界面
subtitle-tool --help       # 命令行
```

需要 Python 3.9+。GPU 加速另装 `nvidia-cublas-cu12 nvidia-cudnn-cu12`。

### 开发

```bash
pip install -e ".[gui,dev]"
python scripts/make_fixture.py   # 生成多音轨测试素材
pytest -q
ruff check src tests scripts

pyinstaller subtitle_tool.spec   # 打包（在 Windows 上执行才产出 exe）
```

## 它是怎么做的

视频 → PyAV 按轨解码为 16kHz 单声道 → faster-whisper 识别语种并转写 →
按词级时间戳切成字幕大小的条目 → NLLB-200 翻译 → 写出 SRT/VTT/TXT。

技术选型对比、实测踩过的坑和已知限制都写在 [docs/design.md](docs/design.md)。

## 已知限制

- 翻译质量取决于 NLLB-600M，长句和专业术语一般般；追求质量建议导出原文字幕后
  另行翻译
- 不做说话人分离
- 整条音轨解码进内存，约每小时 230MB
- 逐段语种检测按 30 秒分组，同组内换语言会跟着组内多数走

## 许可

MIT，见 [LICENSE](LICENSE)。使用的开源项目：
[faster-whisper](https://github.com/SYSTRAN/faster-whisper)（MIT）、
[CTranslate2](https://github.com/OpenNMT/CTranslate2)（MIT）、
[PyAV](https://github.com/PyAV-Org/PyAV)（BSD）、
[NLLB-200](https://huggingface.co/facebook/nllb-200-distilled-600M)（CC-BY-NC 4.0，
**仅限非商业用途**）、[PySide6](https://doc.qt.io/qtforpython/)（LGPLv3）。
