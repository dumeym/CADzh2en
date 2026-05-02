"""文字样式管理模块.

创建和管理英文翻译专用的文字样式（SHX 字体）。
"""

from __future__ import annotations

import logging
from typing import Optional

import ezdxf
from ezdxf.document import Drawing

logger = logging.getLogger("cad_translator")

# 默认英文样式配置
DEFAULT_STYLE_NAME = "TONGJI-FONT"
DEFAULT_FONT = "simplex.shx"
DEFAULT_WIDTH = 0.65


def create_english_style(
    doc: Drawing,
    style_name: str = DEFAULT_STYLE_NAME,
    font: str = DEFAULT_FONT,
    width: float = DEFAULT_WIDTH,
    set_current: bool = True,
) -> str:
    """创建英文翻译专用的文字样式.

    Args:
        doc: ezdxf Drawing 对象
        style_name: 样式名称
        font: SHX 字体文件名
        width: 宽度因子
        set_current: 是否设置为当前文字样式

    Returns:
        样式名称（如果已存在则返回现有样式名）

    Raises:
        ValueError: 样式参数无效
    """
    if not style_name:
        raise ValueError("样式名称不能为空")

    # 检查样式是否已存在
    if style_name in doc.styles:
        logger.info(f"样式 '{style_name}' 已存在，跳过创建")
        if set_current:
            doc.header["$TEXTSTYLE"] = style_name
        return style_name

    # 创建 SHX 字体样式
    style = doc.styles.new(
        style_name,
        dxfattribs={
            "font": font,
            "bigfont": "",
            "width": width,
            "height": 0,  # 不固定高度，继承实体原始高度
            "flags": 0,
        },
    )

    logger.info(
        f"创建文字样式: '{style_name}' "
        f"(font={font}, width={width})"
    )

    if set_current:
        doc.header["$TEXTSTYLE"] = style_name
        logger.info(f"已将 '{style_name}' 置为当前文字样式")

    return style_name


def apply_style_to_entity(entity, style_name: str) -> None:
    """将文字样式应用到实体.

    Args:
        entity: DXF 实体（TEXT, MTEXT, ATTRIB, ATTDEF 等）
        style_name: 样式名称
    """
    try:
        entity.dxf.style = style_name
    except Exception as e:
        logger.warning(
            f"无法为实体 {entity.dxftype()}({entity.dxf.handle}) "
            f"设置样式: {e}"
        )
