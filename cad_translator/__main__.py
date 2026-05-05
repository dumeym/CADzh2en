#!/usr/bin/env python3
"""CAD 图纸中英文自动翻译工具 - CLI 入口.

用法:
    # 单文件翻译（替换模式）
    python -m cad_translator -i 图纸.dwg -t 术语表.csv -o ./out

    # 双语输出
    python -m cad_translator -i 图纸.dxf -t 术语表.csv -o ./out -m bilingual

    # 批量处理文件夹
    python -m cad_translator -d ./图纸目录 -t 术语表.csv -o ./out
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from . import __version__
from .converter import is_odafc_installed, dwg_to_dxf, dxf_to_dwg, read_dxf
from .extractor import extract_texts, filter_chinese_texts
from .style import create_english_style, DEFAULT_STYLE_NAME, DEFAULT_FONT, DEFAULT_WIDTH
from .translator import (
    TermTable,
    TranslatorEngine,
    BaiduCloudTranslator,
    SiliconFlowTranslator,
    NullTranslator,
)
from .backfill import backfill


def setup_logging(verbose: bool = False) -> None:
    """配置日志."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器."""
    parser = argparse.ArgumentParser(
        prog="cad_translator",
        description="CAD 图纸中英文自动翻译工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # 输入
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "-i", "--input",
        help="输入的 DWG/DXF 文件路径",
    )
    input_group.add_argument(
        "-d", "--directory",
        help="批量处理的文件夹路径",
    )

    # 术语表
    parser.add_argument(
        "-t", "--term-table",
        required=True,
        help="CSV 术语对照表路径（UTF-8 编码，两列：中文,英文）",
    )

    # 输出
    parser.add_argument(
        "-o", "--output-dir",
        default="./output",
        help="输出目录（默认: ./output）",
    )

    # 翻译模式
    parser.add_argument(
        "-m", "--mode",
        choices=["replace", "bilingual"],
        default="replace",
        help="翻译模式: replace=替换原文, bilingual=双语并列（默认: replace）",
    )

    # 样式配置
    parser.add_argument(
        "--style-name",
        default=DEFAULT_STYLE_NAME,
        help=f"英文文字样式名称（默认: {DEFAULT_STYLE_NAME}）",
    )
    parser.add_argument(
        "--style-font",
        default=DEFAULT_FONT,
        help=f"SHX 字体文件名（默认: {DEFAULT_FONT}）",
    )
    parser.add_argument(
        "--style-width",
        type=float,
        default=DEFAULT_WIDTH,
        help=f"宽度因子（默认: {DEFAULT_WIDTH}）",
    )

    # API 配置
    parser.add_argument(
        "--api",
        choices=["null", "baidu", "siliconflow"],
        default="null",
        help="翻译 API 类型（默认: null=仅术语表）",
    )
    parser.add_argument(
        "--baidu-api-key",
        help="百度云翻译 API Key（也可通过 BAIDU_API_KEY 环境变量设置）",
    )
    parser.add_argument(
        "--baidu-secret-key",
        help="百度云翻译 Secret Key（也可通过 BAIDU_SECRET_KEY 环境变量设置）",
    )
    parser.add_argument(
        "--baidu-app-id",
        default="",
        help="百度云翻译 App ID（仅用于日志记录）",
    )
    parser.add_argument(
        "--siliconflow-key",
        help="硅基流动 API key（也可通过 SILICONFLOW_API_KEY 环境变量设置）",
    )
    parser.add_argument(
        "--siliconflow-model",
        default="Qwen/Qwen3.5-9B",
        help="硅基流动模型名（默认: Qwen/Qwen3.5-9B）",
    )

    # 其他
    parser.add_argument(
        "--from-csv",
        default="",
        help="从 CSV 文件读取翻译对进行回填（跳过 API 翻译）",
    )
    parser.add_argument(
        "--skip-odafc",
        action="store_true",
        help="跳过 DWG→DXF 转换（输入已是 DXF 格式）",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="详细输出",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"cad_translator {__version__}",
    )

    return parser


def _save_translation_csv(
    input_stem: str,
    chinese_texts: list,
    translations: dict[str, "TranslationResult"],
) -> str:
    """将翻译结果保存为 CSV 文件.

    Args:
        input_stem: 输入文件名（不含扩展名）.
        chinese_texts: 中文文字实体列表.
        translations: {原文: TranslationResult} 字典.

    Returns:
        CSV 文件路径.
    """
    progress_dir = Path("test_progress")
    progress_dir.mkdir(parents=True, exist_ok=True)
    csv_path = str(progress_dir / f"{input_stem}_TEXT.csv")

    # 构建 {原文: 最佳译文} 映射，优先 term_table > api > untranslated
    result_map: dict[str, tuple[str, str]] = {}
    for orig, tr in translations.items():
        result_map[orig] = (tr.translated, tr.source)

    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["handle", "original", "translated", "source"])
        for te in chinese_texts:
            translated, source = result_map.get(te.text, (te.text, "untranslated"))
            writer.writerow([te.handle, te.text, translated, source])

    logger = logging.getLogger("cad_translator")
    logger.info(f"翻译记录已写入: {csv_path}")
    return csv_path


def process_file(
    input_path: str,
    output_dir: str,
    term_table: TermTable,
    style_name: str,
    style_font: str,
    style_width: float,
    mode: str,
    api_type: str = "null",
    baidu_api_key: str = "",
    baidu_secret_key: str = "",
    baidu_app_id: str = "",
    siliconflow_api_key: str = "",
    siliconflow_model: str = "Qwen/Qwen3.5-9B",
    skip_odafc: bool = False,
    from_csv: str = "",
) -> dict:
    """处理单个文件."""
    result = {
        "file": input_path,
        "status": "ok",
        "text_count": 0,
        "chinese_count": 0,
        "translated_count": 0,
        "errors": [],
    }

    logger = logging.getLogger("cad_translator")

    # Step 1: DWG→DXF
    src = Path(input_path)
    ext = src.suffix.lower()
    if ext == ".dwg":
        if not is_odafc_installed():
            msg = "ODA File Converter 未安装，无法处理 DWG 文件"
            logger.error(msg)
            result["status"] = "error"
            result["errors"].append(msg)
            return result
        dxf_path = dwg_to_dxf(str(src), output_dir)
        doc = read_dxf(dxf_path)
    elif ext == ".dxf":
        doc = read_dxf(str(src))
    else:
        msg = f"不支持的文件格式: {ext}"
        logger.error(msg)
        result["status"] = "error"
        result["errors"].append(msg)
        return result

    # Step 2: 提取文字
    all_texts = extract_texts(doc)
    result["text_count"] = len(all_texts)

    chinese_texts = filter_chinese_texts(all_texts)
    result["chinese_count"] = len(chinese_texts)

    if not chinese_texts:
        logger.info("未发现中文文字，跳过翻译")
        result["status"] = "skipped"
        return result

    logger.info(f"发现 {len(chinese_texts)} 个含中文的文字实体")

    # Step 3: 翻译或从 CSV 读取
    if from_csv:
        # 从 CSV 读取翻译，跳过 API 翻译
        logger.info(f"从 CSV 读取翻译: {from_csv}")
        translations = {}
        with open(from_csv, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                orig = row.get("original", "").strip()
                trans = row.get("translated", "").strip()
                if orig and trans:
                    translations[orig] = trans
        result["translated_count"] = len(translations)
        csv_path = from_csv
    else:
        # 根据 API 类型构建翻译器
        api = TranslatorEngine.create_api(
            api_type=api_type,
            baidu_api_key=baidu_api_key,
            baidu_secret_key=baidu_secret_key,
            baidu_app_id=baidu_app_id,
            siliconflow_api_key=siliconflow_api_key,
            siliconflow_model=siliconflow_model,
        )
        engine = TranslatorEngine(term_table=term_table, api=api)

        # 收集需要翻译的原文
        texts_to_translate = list(set(te.text for te in chinese_texts))
        logger.info(f"待翻译的唯一文本: {len(texts_to_translate)} 条")

        trans_results = engine.translate_batch(texts_to_translate)
        trans_map = {
            t.original: t.translated
            for t in trans_results.values()
            if t.success and t.source != "untranslated"
        }

        untranslated = [
            t.original
            for t in trans_results.values()
            if not t.success or t.translated == t.original
        ]
        if untranslated:
            logger.warning(f"未翻译的文本: {len(untranslated)} 条")
            for t in untranslated[:5]:
                logger.warning(f"  [NOT_TRANSLATED] {t}")

        result["translated_count"] = len(trans_map)

        if not trans_map:
            logger.info("没有需要翻译的内容")
            return result

        # Step 4: 写入翻译对 CSV
        csv_path = _save_translation_csv(src.stem, chinese_texts, trans_results)

    # Step 5: 创建英文样式
    logger.info(f"创建文字样式 '{style_name}' (font={style_font}, width={style_width})")
    create_english_style(doc, style_name=style_name, font=style_font, width=style_width)

    # Step 6: 回填译文
    if from_csv:
        from .backfill import backfill_from_csv
        filled = backfill_from_csv(doc, chinese_texts, csv_path, style_name, mode)
    else:
        filled = backfill(doc, chinese_texts, trans_map, style_name, mode)
    logger.info(f"回填译文: {filled}/{result['chinese_count']} 个实体")

    # Step 7: 保存
    if mode == "replace":
        out_filename = src.stem + "_EN"
    else:
        out_filename = src.stem + "_双语"

    dxf_tmp = os.path.join(output_dir, out_filename + ".dxf")
    doc.saveas(dxf_tmp)
    logger.info(f"中间 DXF 已保存: {dxf_tmp}")

    if ext == ".dwg":
        # DWG 输入，转回 DWG
        out_path = os.path.join(output_dir, out_filename + ".dwg")
        dxf_to_dwg(doc, out_path)
        if os.path.exists(dxf_tmp):
            os.remove(dxf_tmp)
    else:
        # DXF 输入，直接保存为 DXF
        out_path = dxf_tmp

    logger.info(f"输出文件: {out_path}")

    return result


def process_directory(
    directory: str,
    output_dir: str,
    term_table: TermTable,
    style_name: str,
    style_font: str,
    style_width: float,
    mode: str,
    api_type: str = "null",
    baidu_api_key: str = "",
    baidu_secret_key: str = "",
    baidu_app_id: str = "",
    siliconflow_api_key: str = "",
    siliconflow_model: str = "Qwen/Qwen3.5-9B",
    skip_odafc: bool = False,
    from_csv: str = "",
) -> list[dict]:
    """批量处理目录下的所有图纸."""
    results = []
    dir_path = Path(directory)
    patterns = ["*.dwg", "*.dxf"]
    files = []
    for pat in patterns:
        files.extend(dir_path.glob(pat))
        files.extend(dir_path.glob(pat.upper()))

    if not files:
        logger = logging.getLogger("cad_translator")
        logger.warning(f"在 '{directory}' 中未找到 DWG/DXF 文件")
        return results

    for fpath in sorted(files):
        result = process_file(
            str(fpath),
            output_dir,
            term_table,
            style_name,
            style_font,
            style_width,
            mode,
            api_type,
            baidu_api_key,
            baidu_secret_key,
            baidu_app_id,
            siliconflow_api_key,
            siliconflow_model,
            skip_odafc,
            from_csv,
        )
        results.append(result)

    return results


def main() -> None:
    """主入口."""
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args()

    # 从环境变量读取 API key（CLI 参数优先级更高）
    baidu_api_key = args.baidu_api_key or os.environ.get("BAIDU_API_KEY", "")
    baidu_secret_key = args.baidu_secret_key or os.environ.get("BAIDU_SECRET_KEY", "")
    baidu_app_id = args.baidu_app_id or os.environ.get("BAIDU_APP_ID", "")
    siliconflow_api_key = args.siliconflow_key or os.environ.get("SILICONFLOW_API_KEY", "")
    from_csv = args.from_csv

    setup_logging(args.verbose)
    logger = logging.getLogger("cad_translator")

    start = time.time()

    # 加载术语表
    if not os.path.isfile(args.term_table):
        logger.error(f"术语表文件不存在: {args.term_table}")
        sys.exit(1)

    term_table = TermTable(args.term_table)

    # 确保输出目录存在
    os.makedirs(args.output_dir, exist_ok=True)

    if args.directory:
        results = process_directory(
            args.directory,
            args.output_dir,
            term_table,
            args.style_name,
            args.style_font,
            args.style_width,
            args.mode,
            args.api,
            baidu_api_key,
            baidu_secret_key,
            baidu_app_id,
            siliconflow_api_key,
            args.siliconflow_model,
            args.skip_odafc,
            from_csv,
        )
    else:
        results = [
            process_file(
                args.input,
                args.output_dir,
                term_table,
                args.style_name,
                args.style_font,
                args.style_width,
                args.mode,
                args.api,
                baidu_api_key,
                baidu_secret_key,
                baidu_app_id,
                siliconflow_api_key,
                args.siliconflow_model,
                args.skip_odafc,
                from_csv,
            )
        ]

    elapsed = time.time() - start

    # 打印摘要
    ok_count = sum(1 for r in results if r["status"] == "ok")
    error_count = sum(1 for r in results if "error" in r.get("errors", []))
    total_texts = sum(r.get("chinese_count", 0) for r in results)
    total_translated = sum(r.get("translated_count", 0) for r in results)

    logger.info("=" * 50)
    logger.info("处理完成!")
    logger.info(f"  处理文件: {len(results)}")
    logger.info(f"  成功: {ok_count}")
    logger.info(f"  失败: {error_count}")
    logger.info(f"  中文文本总数: {total_texts}")
    logger.info(f"  翻译文本数: {total_translated}")
    logger.info(f"  耗时: {elapsed:.1f} 秒")
    logger.info("=" * 50)


if __name__ == "__main__":
    main()
