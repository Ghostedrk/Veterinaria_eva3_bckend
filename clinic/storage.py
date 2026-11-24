"""Estáticos privados en S3 entregados por la propia aplicación.

El bucket tiene Block Public Access activado, así que los archivos no tienen URL pública.
La EC2 los lee con su rol IAM y Nginx guarda una copia en caché. Las plantillas siguen
usando /static/..., por lo que las rutas relativas dentro del CSS funcionan igual.
"""
import mimetypes
import posixpath
from urllib.parse import quote

from django.conf import settings
from django.contrib.staticfiles.storage import staticfiles_storage
from django.http import FileResponse, Http404
from django.views.decorators.http import require_safe
from storages.backends.s3 import S3ManifestStaticStorage


class PrivateS3StaticStorage(S3ManifestStaticStorage):
    """Sube a s3://bucket/static/ con nombres versionados, pero publica las URL en /static/."""

    location = "static"
    querystring_auth = False
    file_overwrite = True
    object_parameters = {"ServerSideEncryption": "AES256", "CacheControl": "public, max-age=31536000"}

    def url(self, name, force=False):
        return settings.STATIC_URL + quote(self.stored_name(name))


@require_safe
def serve_static(request, path):
    path = posixpath.normpath(path).lstrip("/")
    if path.startswith("..") or path in ("", "."):
        raise Http404
    try:
        handle = staticfiles_storage.open(path, "rb")
    except (FileNotFoundError, OSError) as exc:
        raise Http404 from exc
    except Exception as exc:  # botocore ClientError (NoSuchKey / 404)
        if "404" in str(exc) or "NoSuchKey" in str(exc):
            raise Http404 from exc
        raise
    content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
    response = FileResponse(handle, content_type=content_type)
    # Los nombres llevan hash, así que el contenido de cada URL nunca cambia.
    response["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


def presigned_url(file_field, *, filename, download=False, seconds=120):
    """URL temporal firmada para descargar un archivo privado de S3."""
    disposition = "attachment" if download else "inline"
    return file_field.storage.url(file_field.name, parameters={
        "ResponseContentDisposition": f"{disposition}; filename=\"{quote(filename)}\"",
        "ResponseContentType": mimetypes.guess_type(filename)[0] or "application/octet-stream",
    }, expire=seconds)


def using_s3():
    return bool(getattr(settings, "S3_BUCKET", ""))
