import os
# fix_try_block_quality.py
from pathlib import Path
import py_compile, sys

p = Path("moonshot_agent.py")
src = p.read_text(encoding="utf-8").splitlines(True)

# 1) localizar o bloco de regime
blk_start = None
for i, line in enumerate(src):
    if "[QUALITY_PATCH] regime filters" in line:
        blk_start = i
        break
if blk_start is None:
    print("[fix] bloco de regime não encontrado. Nada a fazer.")
    sys.exit(0)

# 2) achar a linha do 'try:' dentro do bloco
def leading_spaces(s): return len(s) - len(s.lstrip(" "))

try_idx = None
for i in range(blk_start, min(blk_start + 200, len(src))):
    if src[i].lstrip().startswith("try:"):
        try_idx = i
        break
if try_idx is None:
    print("[fix] 'try:' não encontrado dentro do bloco. Nada a fazer.")
    sys.exit(0)

# 3) checar se já existe 'except' no mesmo nível de indentação
try_indent = leading_spaces(src[try_idx])
has_except = False
block_end = None

for i in range(try_idx + 1, len(src)):
    line = src[i]
    if line.strip() and not line.lstrip().startswith(("#", "except", "finally")) and leading_spaces(line) <= try_indent:
        block_end = i
        break
    if line.lstrip().startswith("except") and leading_spaces(line) == try_indent:
        has_except = True
        break

if has_except:
    print("[fix] já existe 'except' para este try:. Nenhuma alteração aplicada.")
else:
    if block_end is None:
        block_end = len(src)
    indent = " " * try_indent
    patch = [indent + "except Exception:\n", indent + "    pass\n"]
    src[block_end:block_end] = patch
    p.write_text("".join(src), encoding="utf-8")
    print(f"[fix] inserido 'except Exception: pass' na linha {block_end+1}")

# 4) compilar para validar
py_compile.compile("moonshot_agent.py", doraise=True)
print("[ok] Sintaxe OK após o fix.")
