"""CAD 图纸翻译交互菜单."""
import os
import sys
import subprocess
from pathlib import Path

INPUT_DIR = Path("test_input")
TERM_TABLE = "terms.csv"
OUTPUT_DIR = "test_output"

def list_dwg_files():
    files = []
    for ext in ("*.dwg", "*.dxf", "*.DWG", "*.DXF"):
        files.extend(sorted(INPUT_DIR.glob(ext)))
    return files


def show_menu():
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
        print("  [Q] 退出")
        print()
        sel = input("  请输入编号 (1-{}), 或 A / Q: ".format(len(files))).strip().upper()

        if sel == "Q":
            return
        if sel == "A":
            run_translate(None, files)
            continue

        if sel.isdigit():
            idx = int(sel)
            if 1 <= idx <= len(files):
                run_translate(files[idx - 1])
                continue

        # invalid input, loop again


def run_translate(single_file: Path | None, all_files: list[Path] | None = None):
    if single_file:
        cmd = [
            sys.executable, "-m", "cad_translator",
            "-i", str(single_file),
            "-t", TERM_TABLE,
            "-o", OUTPUT_DIR,
        ]
        print(f"\n  翻译: {single_file.name}")
        print("  " + " ".join(cmd))
        print()
        subprocess.run(cmd, cwd=os.path.dirname(os.path.abspath(__file__)))
    else:
        cmd = [
            sys.executable, "-m", "cad_translator",
            "-d", str(INPUT_DIR),
            "-t", TERM_TABLE,
            "-o", OUTPUT_DIR,
        ]
        print(f"\n  批量翻译 {len(all_files)} 个文件...")
        print("  " + " ".join(cmd))
        print()
        subprocess.run(cmd, cwd=os.path.dirname(os.path.abspath(__file__)))

    print()
    input("  按 Enter 返回菜单...")


if __name__ == "__main__":
    show_menu()
