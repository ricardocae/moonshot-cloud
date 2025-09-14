import os
# fix_indent_auto.py
from pathlib import Path
import py_compile, re, time

p = Path("moonshot_agent.py")
backup = p.with_suffix(p.suffix + f".indentfix.{int(time.time())}.bak")
backup.write_bytes(p.read_bytes())
print(f"[backup] {backup.name}")

# 1) normalizar tabs -> 4 espaços
src = p.read_text(encoding="utf-8")
if "\t" in src:
    src = src.replace("\t", "    ")
    p.write_text(src, encoding="utf-8")
    print("[norm] Tabs convertidos para espaços.")

def try_compile():
    py_compile.compile(str(p), doraise=True)

def load_lines():
    return p.read_text(encoding="utf-8").splitlines()

def save_lines(lines):
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")

def indent_of(s: str) -> int:
    return len(s) - len(s.lstrip(" "))

MAX_ITERS = 80
i = 0
while i < MAX_ITERS:
    try:
        try_compile()
        print(f"[ok] Sintaxe OK após {i} ajustes.")
        break
    except py_compile.PyCompileError as e:
        msg = str(e)
        m = re.search(r"moonshot_agent\.py, line (\d+)\)\n\s*(IndentationError:[^\n]+)", msg)
        if not m:
            print("[erro] Não é um erro de indentação:\n", msg)
            raise
        line_no = int(m.group(1))
        kind = m.group(2)
        lines = load_lines()

        print(f"[fix] {kind} na linha {line_no}")

        # Casos principais
        if "unexpected indent" in kind:
            # desloca 2 ou 4 espaços; tenta preservar formatação
            ln = lines[line_no - 1]
            if ln.startswith("    "):
                lines[line_no - 1] = ln[4:]
            elif ln.startswith("  "):
                lines[line_no - 1] = ln[2:]
            else:
                # se não há espaço, tira todos à esquerda (edge case)
                lines[line_no - 1] = ln.lstrip()
            save_lines(lines)

        elif "expected an indented block" in kind:
            # adiciona um pass logo abaixo
            target = line_no
            pad = " " * (indent_of(lines[line_no - 1]) + 4)
            lines.insert(target, pad + "pass")
            save_lines(lines)

        elif "unindent does not match any outer indentation level" in kind:
            # ajusta indent para o do bloco anterior não-vazio
            prev = next((k for k in range(line_no - 2, -1, -1) if lines[k].strip()), None)
            if prev is not None:
                tgt = indent_of(lines[prev])
                cur = indent_of(lines[line_no - 1])
                if cur > tgt:
                    lines[line_no - 1] = " " * tgt + lines[line_no - 1].lstrip()
                else:
                    # se está menor, iguala ao alvo
                    lines[line_no - 1] = " " * tgt + lines[line_no - 1].lstrip()
            else:
                lines[line_no - 1] = lines[line_no - 1].lstrip()
            save_lines(lines)
        else:
            print("[erro] Tipo de indentação não tratado:\n", kind)
            raise
        i += 1
else:
    raise SystemExit("[fail] Não consegui corrigir a indentação automaticamente após várias tentativas.")

print("[done] Arquivo pronto. Se algo ficar estranho, o backup está salvo.")
