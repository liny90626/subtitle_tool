"""命令行入口。GUI 之外的批处理/脚本化用法，也是自动化测试的入口。"""

import argparse
import sys

from . import __version__, hub, i18n, runtime, settings, worker
from .asr import MODEL_SIZES, default_model
from .audio import probe_tracks
from .i18n import t
from .languages import describe_whisper, flores_name, resolve_target, target_choices
from .pipeline import LAYOUTS, Options
from .subtitles import FORMATS
from .translate import DEFAULT_MODEL as DEFAULT_TRANSLATE_MODEL
from .translate import MODEL_REPOS

#: --model-source 的简写，也可以直接给一个自建源的地址
MODEL_SOURCES = {"auto": settings.AUTO, "official": hub.OFFICIAL, "mirror": hub.MIRROR}


def build_parser():
    parser = argparse.ArgumentParser(
        prog="subtitle-tool",
        description=t("从视频音轨生成字幕：自动识别语种，可翻译为指定目标语言。"),
    )
    parser.add_argument("videos", nargs="*", help=t("视频/音频文件，可传多个"))
    parser.add_argument("--list-tracks", action="store_true", help=t("只列出音轨信息后退出"))
    parser.add_argument("--list-languages", action="store_true", help=t("列出可选目标语种后退出"))
    parser.add_argument(
        "--track", type=int, default=1, help=t("使用第几条音轨，从 1 开始（默认 1）")
    )
    fallback = default_model()
    parser.add_argument(
        "--model",
        default=fallback,
        choices=MODEL_SIZES,
        help=t("识别模型（按当前设备默认 {default}）", default=fallback),
    )
    parser.add_argument(
        "--device",
        default="auto",
        choices=("auto", "cpu", "cuda"),
        help=t("推理设备（默认自动）"),
    )
    parser.add_argument("--language", help=t("指定源语种的 Whisper 码，默认自动识别"))
    parser.add_argument(
        "--multi-language", action="store_true", help=t("一条音轨内多语言混说时逐段识别语种")
    )
    parser.add_argument("--target", help=t("字幕目标语种，接受短码、FLORES 码或语种名"))
    parser.add_argument(
        "--layout", default="target", choices=LAYOUTS, help=t("译文/原文/双语排版（默认 target）")
    )
    parser.add_argument(
        "--format",
        default="srt",
        help=t("输出格式，逗号分隔，可选 {formats}（默认 srt）", formats="/".join(FORMATS)),
    )
    parser.add_argument("--output-dir", help=t("输出目录，默认与视频同目录"))
    parser.add_argument(
        "--translate-model",
        default=DEFAULT_TRANSLATE_MODEL,
        choices=tuple(MODEL_REPOS),
        help=t("翻译模型（默认 {default}）", default=DEFAULT_TRANSLATE_MODEL),
    )
    parser.add_argument("--model-dir", help=t("模型缓存目录，默认用 HuggingFace 默认缓存"))
    parser.add_argument(
        "--model-source",
        help=t("模型下载源：auto（默认，官方源连不上自动换镜像）/ official / mirror / 自建源地址"),
    )
    parser.add_argument("--proxy", help=t("下载模型走的代理，例如 http://127.0.0.1:7890"))
    parser.add_argument(
        "--lang", choices=i18n.LANGUAGES, help=t("界面语言：auto（跟随系统）/ zh / en")
    )
    return parser


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    saved = settings.load()
    # --lang 得赶在建 parser 之前生效，否则 --help 打出来还是上一种语言
    i18n.use(_early_language(argv) or saved.language)
    runtime.start_log()  # 每次运行都从头记，不然翻日志找线索成了大海捞针
    runtime.trace(f"命令行启动 v{__version__} {runtime.memory_note()}")
    args = build_parser().parse_args(argv)

    if args.list_languages:
        for flores, name in target_choices():
            print(f"{flores:12s} {name}")
        return 0

    if not args.videos:
        build_parser().print_help()
        return 2

    if args.list_tracks:
        for video in args.videos:
            print(video)
            for track in probe_tracks(video):
                print(
                    "  "
                    + t(
                        "{label} | 时长 {duration:.1f}s",
                        label=track.label,
                        duration=track.duration,
                    )
                )
        return 0

    target = None
    if args.target:
        target = resolve_target(args.target)
        if target is None:
            print(
                t(
                    "无法识别的目标语种：{value}（用 --list-languages 查看可选值）",
                    value=args.target,
                ),
                file=sys.stderr,
            )
            return 2

    formats = tuple(f.strip() for f in args.format.split(",") if f.strip())
    unknown = [f for f in formats if f not in FORMATS]
    if unknown:
        print(t("不支持的字幕格式：{format}", format=",".join(unknown)), file=sys.stderr)
        return 2

    if args.model_source:
        saved.source = MODEL_SOURCES.get(args.model_source, args.model_source)
    if args.proxy is not None:
        saved.proxy = args.proxy
    hub.apply(saved)

    options = Options(
        track_index=args.track - 1,
        source_language=args.language,
        multi_language=args.multi_language,
        target_language=target,
        layout=args.layout,
        formats=formats,
        output_dir=args.output_dir,
    )
    jobs = [worker.Job(index, video, options) for index, video in enumerate(args.videos)]
    setup = worker.Setup(args.model, args.device, args.translate_model, args.model_dir)
    failed = _run(jobs, setup, args, target)

    runtime.finished()
    return 1 if failed else 0


def _run(jobs, setup, args, target) -> int:
    """跑完所有文件，返回失败个数。

    和图形界面共用同一套驱动：流水线在子进程里跑，原生层崩掉时这边还能换保守配置重试，
    而不是整个命令行跟着一起消失。
    """
    paths = {job.row: job.path for job in jobs}
    started, failed = set(), set()

    def heading(row):
        if row not in started:
            started.add(row)
            print(f"→ {paths[row]}")

    def progress(row, stage, fraction):
        heading(row)
        _print_progress(stage, fraction)

    def done(row, result):
        heading(row)
        _overwrite("  " + _summary(result, args.multi_language, target))
        for out in result.outputs:
            print(f"  ✓ {out}")

    def failure(row, message):
        heading(row)
        failed.add(row)
        _overwrite(f"  ✗ {message}")

    worker.drive(
        jobs,
        setup,
        worker.Events(
            progress=progress,
            note=_note,
            done=done,
            failed=failure,
            retry=lambda: _overwrite(
                "  " + t("⚠ 处理时异常退出，正在用更保守的配置重试（会慢一些）")
            ),
            give_up=lambda row: failure(
                row, t("这个文件处理时异常退出，已跳过。详情见程序目录下的 subtitle-tool.log")
            ),
        ),
    )
    return len(failed)


def _summary(result, multi_language, target) -> str:
    text = t("源语种 {language}", language=describe_whisper(result.source_language))
    if multi_language:
        text += t("，共 {count} 种语言", count=len({s[2] for s in result.language_spans}))
    if target:
        text += f" → {flores_name(target)}"
    return text + t("，{count} 条字幕", count=len(result.cues))


def _early_language(argv):
    """在 argparse 之前把 --lang 抠出来。"""
    for index, arg in enumerate(argv):
        if arg == "--lang" and index + 1 < len(argv):
            return argv[index + 1]
        if arg.startswith("--lang="):
            return arg.split("=", 1)[1]
    return None


def _print_progress(stage: str, fraction: float):
    print(f"\r  {t(stage)} {fraction * 100:5.1f}%", end="", flush=True)


def _note(message: str, fraction=None):
    if fraction is None:
        _overwrite(f"  {message}")
    else:
        print(f"\r  {message} {fraction * 100:5.1f}%", end="", flush=True)


def _overwrite(message: str):
    """进度是用 \\r 原地刷的，插话前先把那一行擦掉。"""
    print(f"\r{' ' * 60}\r{message}")


if __name__ == "__main__":
    sys.exit(main())
