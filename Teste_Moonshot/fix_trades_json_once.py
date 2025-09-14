import os
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
from pathlib import Path

P = Path("Teste_Moonshot/moonshot_trades.json")
if not P.exists():
    print(f"[ERRO] Não achei {P}")
    raise SystemExit(1)

data = json.loads(P.read_text(encoding="utf-8"))
count = 0
for tr in data.values():
    if isinstance(tr, dict):
        if "notified" not in tr:
            tr["notified"] = {"TP1": False, "TP2": False, "TP3": False, "STOP": False}
            count += 1

P.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"[OK] Normalizado: {count} trades atualizados em {P}")
