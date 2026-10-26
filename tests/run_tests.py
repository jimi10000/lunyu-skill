#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lunyu 单元测试运行入口（零依赖）

用法:
    python scripts/../tests/run_tests.py        # 或
    python -m unittest discover -s tests -v
"""
import os
import shutil
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)


def purge_pycache():
    """跑测试前清掉 __pycache__。

    血泪教训：stale .pyc 会让 unittest 加载到旧版本测试代码，
    表现为「明明改过了却还在报老错」或「测试数对不上」，
    甚至能让一批坏测试伪装成全绿。清一次几十毫秒，值。
    """
    for base in (HERE, os.path.join(ROOT, "scripts")):
        for dirpath, dirnames, _ in os.walk(base):
            for d in list(dirnames):
                if d == "__pycache__":
                    shutil.rmtree(os.path.join(dirpath, d), ignore_errors=True)
                    dirnames.remove(d)


def main():
    purge_pycache()
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=HERE, pattern="test_*.py")
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()