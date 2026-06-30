"""
命令行入口：uv run python cli.py <input.docx> [output.md]
"""

import sys
from pathlib import Path

from extractor import extract_file


def main():
    if len(sys.argv) < 2:
        print("用法: uv run python cli.py <input.docx> [output.md]")
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None

    if not Path(input_path).exists():
        print(f"文件不存在: {input_path}")
        sys.exit(1)

    md = extract_file(input_path, output_path)

    if output_path:
        print(f"已写入: {output_path}")
    else:
        print(md)


if __name__ == "__main__":
    main()
