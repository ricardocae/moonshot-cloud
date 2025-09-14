#!/usr/bin/env python3
import os, sys, time, signal, subprocess
from pathlib import Path

LOCK = Path("/tmp/moonshot_agent.lock")
BASE = Path(__file__).resolve().parent
LOGS = BASE / "logs"

def is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False

def setup_env():
    # Carrega .env (se python-dotenv estiver instalado)
    try:
        from dotenv import load_dotenv
        load_dotenv(BASE / ".env")
    except Exception:
        pass
    # Garante SSL_CERT_FILE do certifi (evita erros de CA)
    if not os.getenv("SSL_CERT_FILE"):
        try:
            import certifi
            os.environ["SSL_CERT_FILE"] = certifi.where()
        except Exception:
            pass
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    os.environ.setdefault("TZ", "America/Sao_Paulo")


def acquire_lock():
    import os, errno
    # Tenta criar o lock de forma atômica; se já existir, sai.
    try:
        fd = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        with os.fdopen(fd, "w") as f:
            f.write(str(os.getpid()))
    except OSError as e:
        if getattr(e, "errno", None) == errno.EEXIST:
            try:
                pid = int(LOCK.read_text().strip())
            except Exception:
                pid = "?"
            print(f"[wrapper] já existe instância rodando (PID={pid}). Saindo.")
            sys.exit(0)
        else:
            raise
def release_lock():
    try:
        if LOCK.exists():
            LOCK.unlink()
    except Exception:
        pass

def main():
    setup_env()
    LOGS.mkdir(exist_ok=True, parents=True)
    acquire_lock()

    backoff = 5
    max_backoff = 60

    def handle_sigterm(signum, frame):
        print("[wrapper] SIGTERM recebido. Encerrando…")
        release_lock()
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    print("[wrapper] Moonshot wrapper iniciando…")
    while True:
        try:
            # roda o agent em modo unbuffered
            cmd = [sys.executable, "-u", str(BASE / "moonshot_agent.py")]
            print(f"[wrapper] start agent: {' '.join(cmd)}")
            p = subprocess.Popen(cmd, cwd=str(BASE))
            rc = p.wait()
            print(f"[wrapper] agent saiu com rc={rc}")
            if rc == 0:
                print("[wrapper] saída normal. Encerrando wrapper.")
                break
            # crash: espera com backoff e tenta de novo
            time.sleep(backoff)
            backoff = min(max_backoff, backoff * 2)  # 5 -> 10 -> 20 -> 40 -> 60
        except Exception as e:
            print("[wrapper] exceção:", repr(e))
            time.sleep(backoff)
            backoff = min(max_backoff, backoff * 2)
        except KeyboardInterrupt:
            print("[wrapper] interrompido pelo usuário.")
            break

    release_lock()

if __name__ == "__main__":
    try:
        main()
    finally:
        release_lock()
