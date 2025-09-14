import os
# fix_indent_iter2.py
from pathlib import Path
import py_compile, re, time

p = Path("moonshot_agent.py")
backup = p.with_suffix(p.suffix + f".indentauto.{int(time.time())}.bak")
backup.write_bytes(p.read_bytes())
print(f"[backup] {backup.name}")

def compile_or_err():
    try:
        py_compile.compile(str(p), doraise=True)
        return None
    except py_compile.PyCompileError as e:
        return str(e)

def load_lines():
    return p.read_text(encoding="utf-8").splitlines()

def save_lines(lines):
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")

def dedent_line(lines, ln):
    i = ln - 1
    s = lines[i]
    if s.startswith("    "):
        lines[i] = s[4:]
    elif s.startswith("  "):
        lines[i] = s[2:]
    else:
        lines[i] = s.lstrip()
    return lines

# laço: compila; se IndentationError, dedenta a linha indicada e tenta de novo
for _ in range(120):
    msg = compile_or_err()
    if msg is None:
        print("[ok] Sintaxe OK.")
        break
    # procurar "line N" e o tipo
    m = re.search(r"line\s+(\d+)\)", msg)
    if not m:
        print("[err] Não consegui identificar a linha do erro:\n", msg)
        raise SystemExit(1)
    ln = int(m.group(1))
    if "IndentationError: unexpected indent" in msg:
        print(f"[fix] unexpected indent na linha {ln} → dedent -4")
        lines = load_lines()
        lines = dedent_line(lines, ln)
        save_lines(lines)
        continue
    elif "expected an indented block" in msg:
        print(f"[fix] expected indented block em {ln} → inserir 'pass'")
        lines = load_lines()
        indent = len(lines[ln-1]) - len(lines[ln-1].lstrip(" "))
        lines.insert(ln, " "*(indent+4) + "pass")
        save_lines(lines)
        continue
    elif "unindent does not match any outer indentation level" in msg:
        print(f"[fix] unindent mismatch em {ln} → alinhar com linha anterior não vazia")
        lines = load_lines()
        # achar indent da linha anterior não vazia
        k = ln-2
        while k >= 0 and not lines[k].strip():
            k -= 1
        tgt = 0 if k < 0 else len(lines[k]) - len(lines[k].lstrip(" "))
        lines[ln-1] = " "*tgt + lines[ln-1].lstrip()
        save_lines(lines)
        continue
    else:
        print("[err] Erro não tratado automaticamente:\n", msg)
        raise SystemExit(1)
else:
    raise SystemExit("[fail] Muitas iterações; interrompido.")
