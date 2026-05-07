"""CAD 图纸翻译交互菜单."""
import os
import sys
import argparse
import subprocess
from pathlib import Path

INPUT_DIR = Path("test_input")
TERM_TABLE = "terms.csv"
OUTPUT_DIR = "test_output"
STYLE_WIDTH = 0.65


def list_dwg_files():
    files = []
    for ext in ("*.dwg", "*.dxf"):
        files.extend(sorted(INPUT_DIR.glob(ext)))
    return files


def show_menu():
    global STYLE_WIDTH
    files = list_dwg_files()

    while True:
        os.system("cls" if os.name == "nt" else "clear")
        print("=" * 50)
        print("   CAD 图纸中英文翻译工具")
        print("=" * 50)
        print()

        if not files:
            print("  test_input\\ 下没有 DWG/DXF 文件。")
            print()
            input("  按 Enter 退出...")
            return

        for i, f in enumerate(files, 1):
            print(f"  [{i}] {f.name}")

        print()
        print(f"  [A] ALL — 翻译全部 {len(files)} 个文件")
        print(f"  [S] 设置 — 文字宽高比（当前: {STYLE_WIDTH}）")
        print("  [Q] 退出")
        print()
        sel = input("  请输入编号 (1-{}), 或 A / S / Q: ".format(len(files))).strip().upper()

        if sel == "Q":
            return
        if sel == "S":
            _change_style_width()
            continue
        if sel == "A":
            run_translate(None, files)
            continue

        if sel.isdigit():
            idx = int(sel)
            if 1 <= idx <= len(files):
                run_translate(files[idx - 1])
                continue

        # invalid input, loop again


def _change_style_width():
    global STYLE_WIDTH
    print()
    val = input(f"  请输入新的文字宽高比（当前: {STYLE_WIDTH}）: ").strip()
    if val:
        try:
            STYLE_WIDTH = float(val)
            print(f"  已设置为 {STYLE_WIDTH}")
        except ValueError:
            print("  无效数值，保持原值")
    print()
    input("  按 Enter 返回菜单...")


def run_translate(single_file: Path | None, all_files: list[Path] | None = None):
    global STYLE_WIDTH
    width_str = str(STYLE_WIDTH)

    if single_file:
        cmd = [
            sys.executable, "-m", "cad_translator",
            "-i", str(single_file),
            "-t", TERM_TABLE,
            "-o", OUTPUT_DIR,
            "--style-width", width_str,
        ]
        print(f"\n  翻译: {single_file.name}  (宽高比={STYLE_WIDTH})")
        print()
        subprocess.run(cmd, cwd=os.path.dirname(os.path.abspath(__file__)))
    else:
        cmd = [
            sys.executable, "-m", "cad_translator",
            "-d", str(INPUT_DIR),
            "-t", TERM_TABLE,
            "-o", OUTPUT_DIR,
            "--style-width", width_str,
        ]
        print(f"\n  批量翻译 {len(all_files)} 个文件  (宽高比={STYLE_WIDTH})")
        print()
        subprocess.run(cmd, cwd=os.path.dirname(os.path.abspath(__file__)))

    print()
    input("  按 Enter 返回菜单...")


if __name__ == "__main__":
    show_menu()
