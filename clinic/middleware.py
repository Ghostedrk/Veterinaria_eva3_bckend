import hmac

from django.conf import settings
from django.http import JsonResponse


class SecurityHeadersMiddleware:
    """Cabeceras que OWASP ZAP marcó como ausentes (alertas 10015, 10049 y 90004).

    - Las respuestas de la API contienen datos clínicos: no deben guardarse en cachés.
    - Cross-Origin-Resource-Policy impide que otros sitios incrusten estos recursos
      (no afecta a las llamadas con CORS que hace el frontend autorizado).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith("/api/"):
            response["Cache-Control"] = "no-store"
            response["Pragma"] = "no-cache"
        response.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        return response


class ApiGatewayOnlyMiddleware:
    """La API (/api/) solo responde a solicitudes que pasaron por Amazon API Gateway.

    API Gateway agrega una cabecera con un secreto compartido (mapeo de parámetros de la
    integración). Sin ella la solicitud se rechaza, así el rate limit no se puede saltar
    llamando directo a la IP de la EC2. Si PETCARE_GATEWAY_SECRET no está definido
    (desarrollo local), el control queda desactivado.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        secret = settings.API_GATEWAY_SECRET
        if secret and request.path.startswith("/api/"):
            received = request.META.get(settings.API_GATEWAY_HEADER, "")
            if not hmac.compare_digest(received.encode(), secret.encode()):
                return JsonResponse(
                    {"detail": "La API solo está disponible a través de API Gateway."}, status=403)
        return self.get_response(request)
