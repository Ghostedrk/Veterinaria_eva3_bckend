from pathlib import Path

from django.core.files import File
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Copia los archivos de una carpeta local al almacenamiento por defecto (S3), con la misma ruta."

    def add_arguments(self, parser):
        parser.add_argument("carpeta", help="Carpeta local con los adjuntos, por ejemplo /var/lib/petcare/media")

    def handle(self, *args, **options):
        root = Path(options["carpeta"])
        if not root.is_dir():
            raise CommandError(f"No existe la carpeta {root}.")
        copied = skipped = 0
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            name = path.relative_to(root).as_posix()
            if default_storage.exists(name):
                skipped += 1
                continue
            with path.open("rb") as handle:
                saved = default_storage.save(name, File(handle))
            if saved != name:
                raise CommandError(f"S3 guardó {name} como {saved}; revisa los nombres antes de continuar.")
            copied += 1
        self.stdout.write(self.style.SUCCESS(f"Copiados {copied} archivos; {skipped} ya estaban en S3."))
