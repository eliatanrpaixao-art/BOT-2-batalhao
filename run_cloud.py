"""Inicializador para Railway e outras hospedagens cloud.
Credenciais sensíveis somente nas variáveis do ambiente, nunca no repositório.
"""
import json
import os
from pathlib import Path


def main():
    raw = os.getenv("GOOGLE_CREDENTIALS_JSON", "").strip()
    if not raw:
        raise SystemExit("Configure GOOGLE_CREDENTIALS_JSON nas variáveis privadas da hospedagem.")
    try:
        obj = json.loads(raw)
        if obj.get("type") != "service_account" or not obj.get("client_email"):
            raise ValueError("JSON não é uma chave de conta de serviço")
    except (ValueError, TypeError) as exc:
        raise SystemExit("GOOGLE_CREDENTIALS_JSON inválido. Cole o JSON completo da conta de serviço.") from None
    root = Path(__file__).resolve().parent
    credentials = root / ".google-key-runtime.json"
    credentials.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(credentials, 0o600)
    except OSError:
        pass
    os.environ["GOOGLE_CREDENTIALS_FILE"] = credentials.name
    from bot_core import iniciar
    iniciar(str(root / ".env"))


if __name__ == "__main__":
    main()
