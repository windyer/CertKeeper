#!/usr/bin/env python3
"""CertKeeper 打包脚本。

在 Linux 上构建独立可执行文件：
    python build.py

使用 Docker 构建（无需本地 Python 环境）：
    docker build -f Dockerfile.build -t certkeeper-builder .
    docker run --rm -v "$(pwd)/dist:/output" certkeeper-builder
"""

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    spec_file = ROOT / "certkeeper.spec"
    if not spec_file.exists():
        print(f"错误：找不到 {spec_file}")
        return

    dist_dir = ROOT / "dist"
    build_dir = ROOT / "build"

    # 清理旧构建
    for d in (dist_dir, build_dir):
        if d.exists():
            shutil.rmtree(d)

    print("开始构建 certkeeper ...")
    subprocess.check_call([
        "pyinstaller",
        "--clean",
        "--noconfirm",
        str(spec_file),
    ], cwd=str(ROOT))

    output_dir = dist_dir / "certkeeper"
    if output_dir.exists():
        # 复制示例配置到输出目录
        example_config = ROOT / "certkeeper.yaml.example"
        if example_config.exists():
            shutil.copy2(example_config, output_dir / "certkeeper.yaml.example")
        print(f"\n构建成功！输出目录：{output_dir}")
        print(f"可执行文件：{output_dir / 'certkeeper'}")
        print(f"\n部署步骤：")
        print(f"  1. 打包：tar czf certkeeper.tar.gz -C dist certkeeper")
        print(f"  2. 上传到目标机器并解压：tar xzf certkeeper.tar.gz")
        print(f"  3. 复制并编辑配置：cp certkeeper/certkeeper.yaml.example certkeeper.yaml")
        print(f"  4. 运行：./certkeeper/certkeeper --config certkeeper.yaml start")
    else:
        print("\n构建失败，请检查上方错误信息。", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
