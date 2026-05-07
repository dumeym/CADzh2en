# ezdxf 项目说明

# 注意事项（非常重要）
- 禁止over-thinking。如果用户提供的信息不足以支撑你的判断，**直接询问用户**，而不是自己猜测多种可能性。


## 项目概览
ezdxf 是一个纯 Python DXF 读写库，支持 DXF R12–R2018 版本。本项目基于 ezdxf 开发 **CAD 图纸中英文自动翻译工具**。

## 使用方式

```bash
# 单文件翻译（默认使用百度云翻译）
python -m cad_translator -i test_input/图纸.dwg -t terms.csv -o test_output

# 批量翻译
python -m cad_translator -d test_input -t terms.csv -o test_output

# 使用硅基流动（需在 .env 配置 SILICONFLOW_API_KEY）
python -m cad_translator -i 图纸.dwg -t terms.csv -o test_output --api siliconflow
```

**快速翻译：** 双击 `translate.bat` 打开交互菜单选择文件；文字宽度因子可在 `translate.bat` 中修改 `STYLE_WIDTH=0.65`。

**关键参数：**
| 参数 | 作用 |
|------|------|
| `-i` / `-d` | 单文件或批量目录 |
| `-t` | 术语表 CSV |
| `-o` | 输出目录 |
| `--api` | 翻译引擎：`baidu`（默认）、`siliconflow`、`null`（仅术语表） |
| `-m bilingual` | 双语模式（默认 replace） |
| `--style-width` | SHX 字体宽度因子（默认 0.65） |
| `--skip-odafc` | 输入已是 DXF 时跳过转换 |

## 构建与测试
- Python 版本: 3.10+
- 安装依赖: `pip install -e ".[dev]"` 或 `pip install -r requirements.txt`
- 运行测试: `pytest tests/`
- 检查类型: `mypy -p ezdxf --ignore-missing-imports`

## 项目结构
```
src/ezdxf/                # ezdxf 核心库（不应修改）
cad_translator/           # 翻译工具模块
  ├── __init__.py
  ├── __main__.py         # CLI 入口
  ├── converter.py        # DWG↔DXF 转换
  ├── extractor.py        # 文字提取
  ├── translator.py       # 翻译引擎
  ├── backfill.py         # 译文回填
  └── style.py            # 文字样式管理
```

## 关键 ezdxf API 参考

### DWG 转换
- `ezdxf.addons.odafc.readfile(path)` — 读取 DWG（需 ODA File Converter）
- `ezdxf.addons.odafc.export_dwg(doc, path)` — 导出 DWG（需 ODA File Converter）
- `ezdxf.addons.odafc.convert(src, dst)` — 直接转换格式

### 文字实体
| 实体类型 | 文字属性 | 文件 |
|---------|---------|------|
| TEXT | `entity.dxf.text` | `src/ezdxf/entities/text.py` |
| MTEXT | `entity.text`（含格式码）| `src/ezdxf/entities/mtext.py` |
| ATTRIB | `entity.dxf.text` + `entity.dxf.tag` | `src/ezdxf/entities/attrib.py` |
| ATTDEF | `entity.dxf.text` + `entity.dxf.tag` | `src/ezdxf/entities/attrib.py` |
| DIMENSION | `entity.dxf.text`（覆盖字符串）| `src/ezdxf/entities/dimension.py` |
| LEADER | 需通过 `annotation_handle` 解析关联实体 | `src/ezdxf/entities/leader.py` |
| MULTILEADER | `entity.get_mtext_content()` | `src/ezdxf/entities/mleader.py` |

### 文字清洗
- `ezdxf.tools.text.plain_text(text)` — 清洗 TEXT 中的 %% 编码
- `ezdxf.tools.text.fast_plain_mtext(text)` — 快速清洗 MTEXT 格式码
- `ezdxf.tools.text.plain_mtext(text)` — 完整清洗 MTEXT 格式码

### 文字样式
- `doc.styles.add(name, font=...)` — 创建 TTF 字体文字样式
- `doc.styles.new(name, dxfattribs={...})` — 创建 SHX 字体文字样式
- `entity.dxf.style = "style_name"` — 设置实体样式
- `doc.header["$TEXTSTYLE"] = "style_name"` — 置为当前文字样式

**SHX 字体样式示例**：
```python
style = doc.styles.new("TONGJI-FONT", dxfattribs={
    "font": "simplex.shx",    # SHX 字体文件
    "bigfont": "",            # 不使用大字体
    "width": 0.65,            # 宽度因子
    "height": 0,              # 不固定高度
    "flags": 0,
})
doc.header["$TEXTSTYLE"] = "TONGJI-FONT"  # 置为当前
```

### 编码处理（重要经验）

中国设计院的 DXF 通常使用 **GBK (ANSI_936)** 编码，ezdxf 会自动从 `$DWGCODEPAGE` 头变量检测编码：

```python
doc = ezdxf.readfile("图纸.dxf")           # 自动检测编码 → gbk，正确
doc = ezdxf.readfile("图纸.dxf", encoding="gbk")  # 手动指定，结果相同
```

**关于"乱码"的注意事项**：
- Git Bash / Windows 终端无法显示中文字符时，输出显示为 `"��"` 或 `"西"` 等乱码
- **这是终端显示问题，不是数据问题**——ezdxf 实际读取的数据完全正确
- 验证中文正确性的可靠方法：`print(repr(entity.dxf.text))` 或将结果写入 UTF-8 文件后查看
- 保存 DXF 时编码自动保持（R2000+ 为 UTF-8，旧版保持原编码）

### 块遍历
- `doc.blocks` — `BlocksSection`，迭代返回 `BlockLayout`
- `block.query("TEXT MTEXT ATTRIB ATTDEF")` — 查询块内文字实体
- `entity.dxftype() == "INSERT"` → `entity.dxf.name` 获取引用的块名

## 测试目录结构

项目根目录下预留以下测试目录，所有测试文件按约定存放：

```
test_0type/        # 原型测试（一次性验证脚本和输出）
test_input/        # 输入测试文件（原始 DWG/DXF 图纸）
test_progress/     # 所有测试过程文件（中间结果、日志、CSV 记录）
  └── {name}_TEXT.csv   # 翻译对记录（见下方格式）
test_output/       # 测试结果文件（翻译后的 DWG/DXF 输出）
```

### 翻译对 CSV 格式 (`test_progress/{input_name}_TEXT.csv`)

| 列名 | 说明 | 示例 |
|------|------|------|
| `handle` | DXF 实体句柄，用于关联回填 | `1B4` |
| `original` | 原文（中文） | `日期` |
| `translated` | 译文（英文） | `Date` |
| `source` | 翻译来源 | `term_table` / `baidu_cloud` / `siliconflow` / `untranslated` |

CSV 文件使用 UTF-8 BOM 编码，以兼容 Excel 直接打开含中文的文件。翻译优先级：**术语表 (terms.csv) → 百度云翻译 API → 保留原文**。
