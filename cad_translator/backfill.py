"""译文回填模块.

将翻译后的文字回填到 DXF 文档中，并应用英文文字样式。
支持从 CSV 文件读取翻译对进行回填。
"""

from __future__ import annotations

import csv
import logging
from typing import Optional

from ezdxf.document import Drawing

from .extractor import TextEntity
from .style import apply_style_to_entity, DEFAULT_WIDTH

logger = logging.getLogger("cad_translator")


def backfill(
    doc: Drawing,
    texts: list[TextEntity],
    translations: dict[str, str],
    style_name: str,
    mode: str = "replace",
) -> int:
    """回填译文到 DXF 文档.

    Args:
        doc: ezdxf Drawing 对象
        texts: 提取到的文字实体列表
        translations: {原文: 译文} 字典
        style_name: 要应用的英文样式名
        mode: "replace"（替换）或 "bilingual"（双语）

    Returns:
        回填的实体数量
    """
    count = 0
    for te in texts:
        if te.text not in translations:
            continue

        translated = translations[te.text]
        if _backfill_entity(te, translated, style_name, mode):
            count += 1

    logger.info(f"回填完成: {count}/{len(texts)} 个实体")
    return count


def _backfill_entity(
    te: TextEntity,
    translated: str,
    style_name: str,
    mode: str,
) -> bool:
    """回填单个实体."""
    try:
        entity = te.entity
        dxftype = te.entity_type

        if mode == "replace":
            new_text = translated
        else:  # bilingual
            new_text = f"{te.text}\\P{translated}"

        if dxftype == "TEXT":
            entity.dxf.text = new_text
            apply_style_to_entity(entity, style_name, DEFAULT_WIDTH)

        elif dxftype == "MTEXT":
            if hasattr(entity, "text"):
                entity.text = new_text
            apply_style_to_entity(entity, style_name, DEFAULT_WIDTH)

        elif dxftype in ("ATTRIB", "ATTDEF"):
            entity.dxf.text = new_text
            apply_style_to_entity(entity, style_name, DEFAULT_WIDTH)

        elif dxftype == "DIMENSION":
            entity.dxf.text = translated

        elif dxftype == "MULTILEADER":
            if hasattr(entity, "set_mtext_content"):
                entity.set_mtext_content(translated)

        return True

    except Exception as e:
        logger.warning(
            f"回填失败 {te.entity_type}({te.handle}): {e}"
        )
        return False


def backfill_from_csv(
    doc: Drawing,
    texts: list[TextEntity],
    csv_path: str,
    style_name: str,
    mode: str = "replace",
) -> int:
    """从 CSV 文件读取翻译对并回填.

    CSV 格式: handle,original,translated,source
    按 handle 优先匹配，fallback 按原文匹配。

    Args:
        doc: ezdxf Drawing 对象
        texts: 提取到的文字实体列表
        csv_path: 翻译对 CSV 文件路径
        style_name: 要应用的英文样式名
        mode: "replace"（替换）或 "bilingual"（双语）

    Returns:
        回填的实体数量
    """
    # 从 CSV 构建 handle->译文 和 原文->译文 映射
    handle_map: dict[str, str] = {}
    text_map: dict[str, str] = {}

    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            handle = row.get("handle", "").strip()
            orig = row.get("original", "").strip()
            trans = row.get("translated", "").strip()
            if handle and trans:
                handle_map[handle] = trans
            if orig and trans:
                text_map[orig] = trans

    if not handle_map and not text_map:
        logger.warning(f"CSV 文件无有效数据: {csv_path}")
        return 0

    count = 0
    for te in texts:
        translated = handle_map.get(te.handle) or text_map.get(te.text)
        if translated is None:
            continue
        if _backfill_entity(te, translated, style_name, mode):
            count += 1

    logger.info(f"CSV 回填完成: {count}/{len(texts)} 个实体 (来自 {csv_path})")
    return count