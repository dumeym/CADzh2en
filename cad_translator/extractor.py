"""文字提取模块.

递归遍历 DXF 文档中的所有文字实体，支持 TEXT、MTEXT、ATTRIB、
ATTDEF、DIMENSION、LEADER、MULTILEADER 以及块定义（含嵌套块）。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Iterator, Optional, Set

import ezdxf
from ezdxf.document import Drawing
from ezdxf.entities import DXFEntity, Insert, MText
from ezdxf.tools.text import plain_text, fast_plain_mtext

logger = logging.getLogger("cad_translator")


@dataclass
class TextEntity:
    """提取到的文字实体信息."""

    handle: str
    """实体句柄"""
    text: str
    """原始文字内容"""
    entity: DXFEntity
    """ezdxf 实体引用"""
    block_name: str = ""
    """所属块名，空字符串表示在模型/图纸空间"""
    entity_type: str = ""
    """实体类型: TEXT, MTEXT, ATTRIB 等"""

    def __hash__(self):
        return hash(self.handle)

    def __eq__(self, other):
        return isinstance(other, TextEntity) and self.handle == other.handle


_CHINESE_RE = re.compile(r"[一-鿿㐀-䶿豈-﫿]")


def contains_chinese(text: str) -> bool:
    """检查文本是否包含中文字符."""
    return bool(_CHINESE_RE.search(text))


def should_skip(text: str) -> bool:
    """判断是否应跳过此文本（纯数字、纯符号、空字符串等）."""
    if not text or not text.strip():
        return True
    # 纯数字/符号/空格，不含字母和中文
    stripped = text.strip()
    if not stripped:
        return True
    return False


def extract_texts(doc: Drawing) -> list[TextEntity]:
    """从 DXF 文档中提取所有文字实体.

    Args:
        doc: ezdxf Drawing 对象

    Returns:
        文字实体列表
    """
    result: list[TextEntity] = []

    # 1. 遍历模型空间和图纸空间
    for layout in (doc.modelspace(), doc.paperspace()):
        for entity in layout:
            result.extend(_extract_from_entity(entity))

    # 2. 遍历所有块定义
    _extract_blocks(doc, result)

    # 3. 去重（基于 handle）
    seen: set[str] = set()
    unique: list[TextEntity] = []
    for te in result:
        if te.handle not in seen:
            seen.add(te.handle)
            unique.append(te)

    logger.info(f"提取到 {len(unique)} 个文字实体")
    return unique


def _extract_from_entity(entity: DXFEntity, block_name: str = "") -> list[TextEntity]:
    """从单个实体中提取文字."""
    result: list[TextEntity] = []
    dxftype = entity.dxftype()

    try:
        if dxftype == "TEXT":
            text = entity.dxf.text  # type: ignore[attr-defined]
            if text:
                plain = plain_text(text)
                if not should_skip(plain):
                    result.append(
                        TextEntity(
                            handle=entity.dxf.handle,
                            text=plain,
                            entity=entity,
                            block_name=block_name,
                            entity_type="TEXT",
                        )
                    )

        elif dxftype == "MTEXT":
            mtext: MText = entity  # type: ignore[assignment]
            if mtext.text:
                plain = fast_plain_mtext(mtext.text)
                if isinstance(plain, list):
                    text = " ".join(plain)
                else:
                    text = plain
                if not should_skip(text):
                    result.append(
                        TextEntity(
                            handle=entity.dxf.handle,
                            text=text,
                            entity=entity,
                            block_name=block_name,
                            entity_type="MTEXT",
                        )
                    )

        elif dxftype == "ATTRIB":
            text = entity.dxf.text  # type: ignore[attr-defined]
            if text:
                plain = plain_text(text)
                if not should_skip(plain):
                    result.append(
                        TextEntity(
                            handle=entity.dxf.handle,
                            text=plain,
                            entity=entity,
                            block_name=block_name,
                            entity_type="ATTRIB",
                        )
                    )

        elif dxftype == "ATTDEF":
            text = entity.dxf.text  # type: ignore[attr-defined]
            if text:
                plain = plain_text(text)
                if not should_skip(plain):
                    result.append(
                        TextEntity(
                            handle=entity.dxf.handle,
                            text=plain,
                            entity=entity,
                            block_name=block_name,
                            entity_type="ATTDEF",
                        )
                    )

        elif dxftype == "DIMENSION":
            text = entity.dxf.text  # type: ignore[attr-defined]
            if text and text.strip() and text.strip() not in ("<>",):
                # <> 表示使用测量值，不提取
                if not should_skip(text):
                    result.append(
                        TextEntity(
                            handle=entity.dxf.handle,
                            text=text,
                            entity=entity,
                            block_name=block_name,
                            entity_type="DIMENSION",
                        )
                    )

        elif dxftype == "LEADER":
            ann_handle = entity.dxf.annotation_handle  # type: ignore[attr-defined]
            if ann_handle and ann_handle != "0":
                ann_entity = entity.doc.entitydb.get(ann_handle)  # type: ignore[union-attr]
                if ann_entity is not None:
                    result.extend(
                        _extract_from_entity(ann_entity, block_name)
                    )

        elif dxftype in ("MULTILEADER", "MLEADER"):
            if entity.has_mtext_content():  # type: ignore[attr-defined]
                text = entity.get_mtext_content()  # type: ignore[attr-defined]
                if text and not should_skip(text):
                    result.append(
                        TextEntity(
                            handle=entity.dxf.handle,
                            text=text,
                            entity=entity,
                            block_name=block_name,
                            entity_type="MULTILEADER",
                        )
                    )

        elif dxftype == "INSERT":
            insert: Insert = entity  # type: ignore[assignment]
            for attrib in insert.attribs:
                text = attrib.dxf.text
                if text:
                    plain = plain_text(text)
                    if not should_skip(plain):
                        result.append(
                            TextEntity(
                                handle=attrib.dxf.handle,
                                text=plain,
                                entity=attrib,
                                block_name=block_name,
                                entity_type="ATTRIB",
                            )
                        )

    except Exception as e:
        logger.warning(
            f"提取实体 {dxftype}(handle={entity.dxf.handle}) 时出错: {e}"  # type: ignore[union-attr]
        )

    return result


def _extract_blocks(doc: Drawing, result: list[TextEntity]) -> None:
    """递归遍历所有块定义，提取文字实体."""
    visited: Set[str] = set()

    def _recurse_block(block_name: str, depth: int = 0) -> None:
        """递归处理单个块定义."""
        if depth > 32:  # 防止循环引用
            return

        key = block_name.lower()
        if key in visited:
            return
        visited.add(key)

        block = doc.blocks.get(block_name)
        if block is None:
            return

        for entity in block:
            dxftype = entity.dxftype()

            # 提取文字实体
            result.extend(_extract_from_entity(entity, block_name))

            # 嵌套块：INSERT 实体
            if dxftype == "INSERT":
                insert: Insert = entity  # type: ignore[assignment]
                ref_name = insert.dxf.name

                # 提取 ATTRIB（块引用的属性）
                for attrib in insert.attribs:
                    text = attrib.dxf.text
                    if text:
                        plain = plain_text(text)
                        if not should_skip(plain):
                            result.append(
                                TextEntity(
                                    handle=attrib.dxf.handle,
                                    text=plain,
                                    entity=attrib,
                                    block_name=block_name,
                                    entity_type="ATTRIB",
                                )
                            )

                # 递归进入引用的块定义
                if ref_name:
                    _recurse_block(ref_name, depth + 1)

    for block_layout in doc.blocks:
        if block_layout.name.startswith("*"):
            # 跳过匿名块（如 *U###, *D###, *X###, *T###）
            continue
        visited.clear()
        _recurse_block(block_layout.name)


def filter_chinese_texts(texts: list[TextEntity]) -> list[TextEntity]:
    """仅保留含中文的文字实体."""
    return [t for t in texts if contains_chinese(t.text)]


def build_text_map(texts: list[TextEntity]) -> dict[str, TextEntity]:
    """按 handle 构建文字实体字典."""
    return {t.handle: t for t in texts}
