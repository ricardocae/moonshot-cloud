agent: python -u Teste_Moonshot/moonshot_agent.py
report: bash -lc 'while true; do python -u Teste_Moonshot/open_trades_cli.py; sleep 3600; done'

web: gunicorn -w 2 -k gthread -b 0.0.0.0:$PORT web.app:app
