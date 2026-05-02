"""DWG↔DXF 转换模块.

基于 ezdxf.addons.odafc 封装，处理 DWG 与 DXF 之间的格式转换。
"""

from __future__ import annotations

import os
import logging
from pathlib import Path
from typing import Optional

import ezdxf
from ezdxf.addons import odafc
from ezdxf.document import Drawing

logger = logging.getLogger("cad_translator")


def is_odafc_installed() -> bool:
    """检查 ODA File Converter 是否已安装."""
    try:
        return odafc.is_installed()
    except Exception:
        return False


def dwg_to_dxf(input_path: str | os.PathLike, output_dir: str | os.PathLike) -> str:
    """将 DWG 文件转换为 DXF 文件.

    Args:
        input_path: 输入的 DWG 文件路径
        output_dir: 输出目录

    Returns:
        转换后的 DXF 文件路径

    Raises:
        FileNotFoundError: 输入文件不存在
        odafc.ODAFCNotInstalledError: ODAFC 未安装
    """
    src = Path(input_path)
    if not src.is_file():
        raise FileNotFoundError(f"文件不存在: '{src}'")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / src.with_suffix(".dxf").name

    logger.info(f"正在转换 DWG→DXF: {src.name}")
    doc = odafc.readfile(str(src))
    doc.saveas(str(dst))
    logger.info(f"转换完成: {dst}")
    return str(dst)


def dxf_to_dwg(doc: Drawing, output_path: str | os.PathLike, replace: bool = True) -> str:
    """将 ezdxf Drawing 对象保存为 DWG 文件.

    Args:
        doc: ezdxf Drawing 对象
        output_path: 输出的 DWG 文件路径
        replace: 是否覆盖已有文件

    Returns:
        输出的 DWG 文件路径

    Raises:
        FileExistsError: 文件已存在且 replace=False
        odafc.ODAFCNotInstalledError: ODAFC 未安装
    """
    dst = Path(output_path)
    if dst.exists() and not replace:
        raise FileExistsError(f"文件已存在: '{dst}'")
    if dst.exists():
        dst.unlink()

    dst.parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"正在导出 DWG: {dst.name}")
    odafc.export_dwg(doc, str(dst), replace=True)
    logger.info(f"导出完成: {dst}")
    return str(dst)


def read_dxf(input_path: str | os.PathLike) -> Drawing:
    """读取 DXF 文件（自动处理编码）.

    Args:
        input_path: DXF 文件路径

    Returns:
        ezdxf Drawing 对象

    Raises:
        FileNotFoundError: 文件不存在
    """
    src = Path(input_path)
    if not src.is_file():
        raise FileNotFoundError(f"文件不存在: '{src}'")

    logger.info(f"正在读取 DXF: {src}")
    doc = ezdxf.readfile(str(src))
    logger.info(f"读取成功: 版本={doc.dxfversion}, 编码={doc.encoding}")
    return doc
