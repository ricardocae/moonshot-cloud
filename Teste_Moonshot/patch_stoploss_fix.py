#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Patcher: corrige f-string sem aspas no Stop Loss caption (linha similar à 1195).
Uso:
  1) Copie este arquivo para a pasta do projeto (onde está moonshot_agent.py)
  2) Rode:  python3 patch_stoploss_fix.py
  3) Confira o resultado e teste: python3 -m py_compile moonshot_agent.py
"""

import re
from pathlib import Path

p = Path("moonshot_agent.py")
if not p.exists():
    raise SystemExit("moonshot_agent.py não encontrado (rode este script dentro da pasta do projeto).")

src = p.read_text(encoding="utf-8")

# 1) Corrige o caso típico: f"🛑 Stop Loss | {tr['symbol']} {side} on {tr['tf']}m\n<continuação..." sem fechar aspas
# Transformamos a quebra física de linha em '\n"'+quebra real, fechando a string no fim da linha.
pattern = r'(f"🛑 Stop Loss \| \{tr\[\'symbol\'\]\} \{side\} on \{tr\[\'tf\'\]\}m)\n'
repl    = r'\1\\n"\n'
new, n1 = re.subn(pattern, repl, src)

# 2) (Opcional) Fazemos o mesmo para algum caption de TP que possa ter sido escrito da mesma forma.
pattern_tp = r'(f"✅ Take Profit \| \{tr\[\'symbol\'\]\} \{side\} on \{tr\[\'tf\'\]\}m)\n'
new, n2 = re.subn(pattern_tp, repl, new)

# 3) Opcional: normaliza tabs para 4 espaços (evita problemas de indent misto)
new = new.replace("\t", "    ")

# 4) Escreve backup e novo arquivo
backup = p.with_suffix(".py.bak")
backup.write_text(src, encoding="utf-8")
p.write_text(new, encoding="utf-8")

print(f"Feito. Ajustes aplicados: StopLoss={n1}, TakeProfit={n2}. Backup -> {backup}")
print("Agora rode: python3 -m py_compile moonshot_agent.py (para checar sintaxe)")
