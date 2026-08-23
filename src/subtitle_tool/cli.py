"""命令行入口。GUI 之外的批处理/脚本化用法，也是自动化测试的入口。"""

import argparse
import sys

from .asr import MODEL_SIZES, Cancelled, default_model
from .audio import probe_tracks
from .languages import FLORES_NAMES, describe_whisper, resolve_target, target_choices
from .pipeline import LAYOUTS, Engine, Options
from .subtitles import FORMATS
from .translate import DEFAULT_MODEL as DEFAULT_TRANSLATE_MODEL
from .translate import MODEL_REPOS


def build_parser():
    parser = argparse.ArgumentParser(
        prog="subtitle-tool",
        description="从视频音轨生成字幕：自动识别语种，可翻译为指定目标语言。",
    )
    parser.add_argument("videos", nargs="*", help="视频/音频文件，可传多个")
    parser.add_argument("--list-tracks", action="store_true", help="只列出音轨信息后退出")
    parser.add_argument("--list-languages", action="store_true", help="列出可选目标语种后退出")
    parser.add_argument("--track", type=int, default=1, help="使用第几条音轨，从 1 开始（默认 1）")
    fallback = default_model()
    parser.add_argument(
        "--model",
        default=fallback,
        choices=MODEL_SIZES,
        help=f"识别模型（按当前设备默认 {fallback}）",
    )
    parser.add_argument(
        "--device", default="auto", choices=("auto", "cpu", "cuda"), help="推理设备（默认自动）"
    )
    parser.add_argument("--language", help="指定源语种的 Whisper 码，默认自动识别")
    parser.add_argument(
        "--multi-language", action="store_true", help="一条音轨内多语言混说时逐段识别语种"
    )
    parser.add_argument("--target", help="字幕目标语种，接受 zh / zho_Hans / 中文（简体） 三种写法")
    parser.add_argument(
        "--layout", default="target", choices=LAYOUTS, help="译文/原文/双语排版（默认 target）"
    )
    parser.add_argument(
        "--format", default="srt", help=f"输出格式，逗号分隔，可选 {'/'.join(FORMATS)}（默认 srt）"
    )
    parser.add_argument("--output-dir", help="输出目录，默认与视频同目录")
    parser.add_argument(
        "--translate-model",
        default=DEFAULT_TRANSLATE_MODEL,
        choices=tuple(MODEL_REPOS),
        help=f"翻译模型（默认 {DEFAULT_TRANSLATE_MODEL}）",
    )
    parser.add_argument("--model-dir", help="模型缓存目录，默认用 HuggingFace 默认缓存")
    return parser


def main(argv=None) -> int:
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
                print(f"  {track.label} | 时长 {track.duration:.1f}s")
        return 0

    target = None
    if args.target:
        target = resolve_target(args.target)
        if target is None:
            print(
                f"无法识别的目标语种：{args.target}（用 --list-languages 查看可选值）",
                file=sys.stderr,
            )
            return 2

    formats = tuple(f.strip() for f in args.format.split(",") if f.strip())
    unknown = [f for f in formats if f not in FORMATS]
    if unknown:
        print(f"不支持的字幕格式：{','.join(unknown)}", file=sys.stderr)
        return 2

    options = Options(
        track_index=args.track - 1,
        source_language=args.language,
        multi_language=args.multi_language,
        target_language=target,
        layout=args.layout,
        formats=formats,
        output_dir=args.output_dir,
    )
    engine = Engine(args.model, args.device, args.translate_model, args.model_dir)

    for video in args.videos:
        print(f"→ {video}")
        try:
            result = engine.run(video, options, progress=_print_progress)
        except Cancelled:
            return 130
        print(f"\r{' ' * 60}\r  源语种 {describe_whisper(result.source_language)}", end="")
        if args.multi_language:
            print(f"，共 {len({s[2] for s in result.language_spans})} 种语言", end="")
        if target:
            print(f" → {FLORES_NAMES[target]}", end="")
        print(f"，{len(result.cues)} 条字幕")
        for out in result.outputs:
            print(f"  ✓ {out}")
    return 0


def _print_progress(stage: str, fraction: float):
    print(f"\r  {stage} {fraction * 100:5.1f}%", end="", flush=True)


if __name__ == "__main__":
    sys.exit(main())
