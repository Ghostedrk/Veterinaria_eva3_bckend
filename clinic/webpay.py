"""Cliente mínimo de Webpay Plus (API REST v1.2 de Transbank).

Por defecto usa el ambiente de integración: es la plataforma de pruebas oficial
de Transbank, con tarjetas ficticias y sin movimientos de dinero real.
"""
import json
import re
import urllib.error
import urllib.request

from django.conf import settings

API_PATH = "/rswebpaytransaction/api/webpay/v1.2/transactions"
TOKEN_RE = re.compile(r"[A-Za-z0-9]{1,64}")


class WebpayError(Exception):
    pass


def valid_token(token):
    return bool(token) and TOKEN_RE.fullmatch(token) is not None


def _request(method, path="", body=None):
    request = urllib.request.Request(
        settings.WEBPAY_BASE_URL.rstrip("/") + API_PATH + path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={
            "Tbk-Api-Key-Id": settings.WEBPAY_COMMERCE_CODE,
            "Tbk-Api-Key-Secret": settings.WEBPAY_API_KEY,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise WebpayError(f"Webpay respondió con el código {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise WebpayError("No se pudo conectar con Webpay.") from exc


def create_transaction(buy_order, session_id, amount, return_url):
    """Devuelve {"token": ..., "url": ...} para redirigir al formulario de pago."""
    data = _request("POST", body={
        "buy_order": buy_order, "session_id": session_id, "amount": amount, "return_url": return_url,
    })
    if not valid_token(data.get("token")) or not data.get("url", "").startswith("https://"):
        raise WebpayError("Webpay entregó una respuesta inesperada.")
    return data


def commit_transaction(token):
    """Confirma la transacción y devuelve su resultado (status, response_code, amount...)."""
    if not valid_token(token):
        raise WebpayError("Token de Webpay inválido.")
    return _request("PUT", f"/{token}")
