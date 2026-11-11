import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DEBUG = os.getenv("PETCARE_DEBUG", "1") == "1"
SECRET_KEY = (
    os.getenv("PETCARE_SECRET_KEY", "django-insecure-petcare-local-development-only")
    if DEBUG
    else os.environ["PETCARE_SECRET_KEY"]
)
ALLOWED_HOSTS = os.getenv("PETCARE_HOSTS", "localhost,127.0.0.1").split(",")
INSTALLED_APPS = [
    "django.contrib.auth", "django.contrib.contenttypes", "django.contrib.sessions",
    "django.contrib.messages", "django.contrib.staticfiles", "rest_framework",
    # clinic goes before admin so its admin/base_site.html template takes precedence.
    "clinic", "django.contrib.admin",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "petcare.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
WSGI_APPLICATION = "petcare.wsgi.application"

if DEBUG and os.getenv("PETCARE_DB") == "sqlite":
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.getenv("PETCARE_SQLITE_PATH", BASE_DIR / "local.sqlite3"),
        "OPTIONS": {"transaction_mode": "IMMEDIATE"},
    }}
else:
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("PGDATABASE", "petcare"),
        "USER": os.getenv("PGUSER", "petcare"),
        "PASSWORD": os.getenv("PGPASSWORD", ""),
        "HOST": os.getenv("PGHOST", "127.0.0.1"),
        "PORT": os.getenv("PGPORT", "5432"),
    }}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": f"django.contrib.auth.password_validation.{validator}"}
    for validator in ("UserAttributeSimilarityValidator", "MinimumLengthValidator",
                      "CommonPasswordValidator", "NumericPasswordValidator")
]
LANGUAGE_CODE = "es"
TIME_ZONE = "America/Santiago"
USE_TZ = True
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

# HTTPS is on by default in production. An EC2 instance reached by its bare
# public IP has no certificate, so PETCARE_HTTPS=0 keeps sessions working over HTTP.
HTTPS = not DEBUG and os.getenv("PETCARE_HTTPS", "1") == "1"
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = SECURE_SSL_REDIRECT = HTTPS
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_AGE = int(os.getenv("PETCARE_SESSION_SECONDS", str(8 * 3600)))
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
CSRF_TRUSTED_ORIGINS = [o for o in os.getenv("PETCARE_CSRF_ORIGINS", "").split(",") if o]
if os.getenv("PETCARE_TRUST_PROXY") == "1":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

EMAIL_BACKEND = os.getenv(
    "PETCARE_EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend" if DEBUG
    else "django.core.mail.backends.smtp.EmailBackend",
)
EMAIL_HOST = os.getenv("PETCARE_SMTP_HOST", "localhost")
EMAIL_PORT = int(os.getenv("PETCARE_SMTP_PORT", "587"))
EMAIL_HOST_USER = os.getenv("PETCARE_SMTP_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("PETCARE_SMTP_PASSWORD", "")
EMAIL_USE_TLS = os.getenv("PETCARE_SMTP_TLS", "1") == "1"
EMAIL_TIMEOUT = 15
DEFAULT_FROM_EMAIL = os.getenv("PETCARE_FROM_EMAIL", "petcare@example.test")

# Webpay Plus. Los valores por defecto son las credenciales públicas del ambiente
# de integración de Transbank: pagos simulados con tarjetas de prueba.
WEBPAY_BASE_URL = os.getenv("PETCARE_WEBPAY_URL", "https://webpay3gint.transbank.cl")
WEBPAY_COMMERCE_CODE = os.getenv("PETCARE_WEBPAY_COMMERCE_CODE", "597055555532")
WEBPAY_API_KEY = os.getenv(
    "PETCARE_WEBPAY_API_KEY", "579B532A7440BB0C9079DED94D31EA1615BACEB56610332264630D42D0A36B1C",
)

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAdminUser"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
}
