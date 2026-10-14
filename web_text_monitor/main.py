"""Punto de entrada del monitor de textos web.

    python main.py run                          # inicia el monitor con config.toml
    python main.py --config otra.toml run       # con otro archivo de configuración
    python main.py check | probe | login | demo-server
    python main.py --help
"""

import sys

if sys.version_info < (3, 11):
    sys.stderr.write(
        "Este programa necesita Python 3.11 o posterior y se está ejecutando con Python %d.%d.\n"
        "Instala Python desde https://www.python.org/downloads/macos/ y crea el entorno virtual con él "
        "(consulta el README).\n" % sys.version_info[:2]
    )
    sys.exit(2)

from textmonitor.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
