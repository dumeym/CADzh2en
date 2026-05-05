# CADzh2en — CAD 图纸中英文自动翻译工具

基于 [ezdxf](https://github.com/mozman/ezdxf) 与 ODA File Converter 的 CAD 图纸中文→英文自动翻译工具。自动提取 DWG/DXF 图纸中的中文文字，通过术语表 + 百度云翻译 API 完成翻译，并回填生成英文版图纸。

## 功能

- 支持 DWG / DXF 输入，输出英文版 DWG / DXF
- 自动提取 TEXT / MTEXT / ATTRIB / ATTDEF / DIMENSION / LEADER / MULTILEADER 等实体的中文文字
- 术语表优先匹配（`terms.csv`），未命中条目调用百度云翻译 API
- 支持双语模式（译文并列原文，`--mode bilingual`）
- 批量处理目录下所有图纸（`-d` 参数）
- 翻译记录导出为 UTF-8 BOM CSV，可用 Excel 直接打开

## 前置依赖

- Python 3.10+
- [ODA File Converter](https://www.opendesign.com/guestfiles/oda_file_converter)（处理 DWG 文件必需）
- 百度云翻译 API 密钥（可选，仅术语表翻译可不配置）

## 安装

```bash
pip install -e ".[dev]"
```

复制 `.env` 文件并填入 API 密钥（可选）：

```bash
# .env 示例
BAIDU_API_KEY=your_api_key
BAIDU_SECRET_KEY=your_secret_key
BAIDU_APP_ID=your_app_id
```

## 用法

```bash
# 单文件翻译（替换模式）
python -m cad_translator -i test_input/图纸.dwg -t terms.csv -o test_output

# 单文件翻译（双语模式）
python -m cad_translator -i test_input/图纸.dxf -t terms.csv -o test_output -m bilingual

# 批量处理
python -m cad_translator -d ./图纸目录 -t terms.csv -o test_output

# 使用百度云翻译 API
python -m cad_translator -i 图纸.dwg -t terms.csv -o test_output --api baidu

# 从已有 CSV 翻译对直接回填（跳过翻译）
python -m cad_translator -i 图纸.dwg -t terms.csv -o test_output --from-csv previous_TEXT.csv
```

### 参数说明

| 参数 | 说明 |
|------|------|
| `-i` | 输入 DWG/DXF 文件路径 |
| `-d` | 批量处理文件夹路径（与 `-i` 互斥） |
| `-t` | 术语对照表 CSV（UTF-8，两列：中文,英文） |
| `-o` | 输出目录（默认 `./output`） |
| `-m` | 翻译模式：`replace`（替换）/ `bilingual`（双语并列） |
| `--api` | 翻译 API：`null` / `baidu` / `siliconflow` |
| `--from-csv` | 从已有 CSV 回填，跳过 API 翻译 |
| `--style-name` | 英文文字样式名称 |
| `--style-font` | SHX 字体文件（默认 `simplex.shx`） |
| `--skip-odafc` | 跳过 DWG→DXF 转换（输入已是 DXF 格式时使用） |

## 项目结构

```
cad_translator/           # 翻译工具模块
  ├── __init__.py
  ├── __main__.py         # CLI 入口
  ├── converter.py        # DWG↔DXF 转换
  ├── extractor.py        # 文字提取
  ├── translator.py       # 翻译引擎 + 术语表
  ├── backfill.py         # 译文回填
  └── style.py            # 文字样式管理
terms.csv                 # 术语对照表
test_input/               # 输入测试图纸（.dwg / .dxf）
test_output/              # 翻译后输出图纸（_EN.dwg / _EN.dxf）
test_progress/            # 翻译过程记录（_TEXT.csv）
```

## 工作流程

1. DWG → DXF 转换（ODA File Converter）
2. 遍历模型空间与所有块，提取文字实体
3. 去重后依次匹配术语表 → 调用百度云翻译 API
4. 创建英文字体样式
5. 译文回填至对应实体
6. 保存为 _EN.dwg（DXF 输入则输出 _EN.dxf）

## 技术栈

- [ezdxf](https://github.com/mozman/ezdxf) — 纯 Python DXF 读写库
- [ODA File Converter](https://www.opendesign.com/guestfiles/oda_file_converter) — DWG 格式转换
- 百度云翻译 MT API / 硅基流动 API — 机器翻译

## License

本项目基于 MIT 协议开源，ezdxf 部分遵循其原始 MIT License。
