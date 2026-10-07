r"""Compile every raw-string regex literal passed to re.* in the given files (heredoc patches
halved `\\` inside regexes on 2026-10-07: one would not compile, another silently changed).
A regex built by concatenating a variable is checked by its literal parts only.

Usage: python regex_scan.py <file>...
"""
import re
import sys

CALL = re.compile(r're\.(?:compile|match|search|sub|split|findall|finditer|fullmatch)\(\s*((?:r"(?:[^"\\]|\\.)*"\s*)+)')
LIT = re.compile(r'r"((?:[^"\\]|\\.)*)"')

bad = 0
for p in sys.argv[1:]:
    src = open(p, encoding="utf-8").read()
    n = 0
    for m in CALL.finditer(src):
        pattern = "".join(LIT.findall(m.group(1)))
        n += 1
        try:
            re.compile(pattern)
        except re.error as e:
            bad += 1
            print(f"BAD {p}: {e}: {pattern[:90]}")
    print(f"{p}: {n} regex calls compiled")
sys.exit(1 if bad else 0)
