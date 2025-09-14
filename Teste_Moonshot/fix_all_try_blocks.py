import os
# fix_all_try_blocks.py
from pathlib import Path
import py_compile, sys, time

p = Path("moonshot_agent.py")
src = p.read_text(encoding="utf-8").splitlines(True)
backup = p.with_suffix(p.suffix + f".autofix.{int(time.time())}.bak")
backup.write_bytes(p.read_bytes())

def indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))

def is_same_level_kw(line: str, kw: str, level: int) -> bool:
    return line.lstrip().startswith(kw) and indent_of(line) == level

i = 0
patched = 0

while i < len(src):
    line = src[i]
    if line.lstrip().startswith("try:"):
        lvl = indent_of(line)
        has_handler = False
        else_idx = None
        j = i + 1
        while j < len(src):
            lj = src[j]
            # Fim lógico do bloco: dedent <= lvl com linha não-vazia e não-comentário
            if lj.strip() and not lj.lstrip().startswith(("#",)):
                if indent_of(lj) <= lvl and not is_same_level_kw(lj, ("except", "finally", "else:"), lvl):
                    break
            # Handlers no mesmo nível
            if is_same_level_kw(lj, "except", lvl) or is_same_level_kw(lj, "finally", lvl):
                has_handler = True
                break
            # else: no mesmo nível (só é válido se houver except; se não houver, vamos inserir antes do else)
            if is_same_level_kw(lj, "else:", lvl) and else_idx is None:
                else_idx = j
            j += 1

        if not has_handler:
            insert_at = else_idx if else_idx is not None else j
            pad = " " * lvl
            patch = [pad + "except Exception:\n", pad + "    pass\n"]
            src[insert_at:insert_at] = patch
            patched += 1
            # pular o que acabamos de inserir
            i = insert_at + len(patch)
        else:
            i = j  # já tem handler, segue adiante
    else:
        i += 1

p.write_text("".join(src), encoding="utf-8")

# valida sintaxe
py_compile.compile(str(p), doraise=True)
print(f"[ok] Sintaxe OK. try-blocks corrigidos: {patched}. Backup: {backup.name}")
