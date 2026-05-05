"""译文回填模块.

将翻译后的文字回填到 DXF 文档中，并应用英文文字样式。
"""

from __future__ import annotations

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
