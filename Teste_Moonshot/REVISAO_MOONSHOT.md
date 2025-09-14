# Revisão do Projeto — Teste_Moonshot
**Data:** 2025-09-07 19:41
## Resumo
- Verificação de sintaxe dos arquivos Python.
- `moonshot_agent.py` incluído no bundle.
## Arquivos Python — status de compilação
| arquivo | status | detalhe |
|---|---|---|
| apply_quality_patch.py | OK |  |
| build_blacklist.py | OK |  |
| diag_quase_rompimentos.py | OK |  |
| diag_resumo.py | OK |  |
| get_telegram_chat_id.py | OK |  |
| moonshot_agent.py | ERROR |   File "/mnt/data/Teste_Moonshot_extracted/Teste_Moonshot/moonshot_agent.py", line 621
    try:
    … |
| moonshot_analyze.py | OK |  |
| moonshot_audit.py | OK |  |
| moonshot_blacklist.py | OK |  |
| moonshot_diag.py | OK |  |
| moonshot_tools.py | OK |  |
| repair_quality_patch.py | OK |  |
| report_pnl.py | OK |  |
| test_telegram.py | OK |  |

## Diferença aplicada (se disponível)
```
diff --git a/moonshot_config.yaml b/moonshot_config.yaml
--- a/moonshot_config.yaml
+++ b/moonshot_config.yaml
@@
 poll_seconds: 30
 cache_file: "moonshot_cache.json"
 trades_file: "moonshot_trades.json"
 
 # --- Auditoria ---
 audit:
   stake_usd: 30        # valor fixo por operação
   out_csv: "moonshot_audit.csv"
   out_json: "moonshot_audit.json"
   out_txt: "moonshot_audit_summary.txt"
+
+# --- Debug/Logs ---
+debug: true            # mostra heartbeat, batch, status do BTC, contadores
+log_btc: true          # loga close/EMA20/RSI do BTC 15m a cada ciclo
+log_batch_size: true   # mostra o intervalo de símbolos sendo varridos

```
