"""Interfaz común de almacenamiento.

La app solo usa `snapshot()` para leer y `write()` para guardar. Para cambiar
de GitHub a otra base de datos en el futuro basta con escribir otra clase con
`read_all()` y `_write()`.
"""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod

RECENT_SECONDS = 180


class StorageError(RuntimeError):
    """Error al leer o escribir datos (red, permisos, token vencido…)."""


class Store(ABC):
    def __init__(self) -> None:
        # Contador compartido por todas las sesiones del servidor: cambia con
        # cada escritura para que el caché de lectura se renueve al instante.
        self.version = 0
        self._lock = threading.Lock()
        # Escrituras recientes: GitHub puede tardar en mostrar un commit nuevo
        # en la descarga de la rama; mientras tanto se completan los datos
        # leídos con lo que esta app acaba de guardar. Cada una se descarta en
        # cuanto la lectura ya trae ese archivo (así un arreglo manual en la
        # rama de datos no queda tapado) o, como máximo, a los RECENT_SECONDS.
        self._recent: dict[str, tuple[bytes, float]] = {}

    @property
    @abstractmethod
    def label(self) -> str:
        """Descripción corta para mostrar en la app."""

    @abstractmethod
    def read_all(self) -> dict[str, bytes]:
        """Todos los archivos de datos: {ruta relativa: contenido}."""

    @abstractmethod
    def _write(self, path: str, content: bytes, message: str) -> None:
        """Crea o reemplaza un archivo en el almacenamiento real."""

    def write(self, path: str, content: bytes, message: str) -> None:
        self._write(path, content, message)
        with self._lock:
            self._recent[path] = (content, time.time())
            self.version += 1

    def snapshot(self) -> dict[str, bytes]:
        files = self.read_all()
        now = time.time()
        with self._lock:
            for path, (content, ts) in list(self._recent.items()):
                if path in files or now - ts > RECENT_SECONDS:
                    del self._recent[path]  # GitHub ya lo devuelve (o venció el tope)
                else:
                    files[path] = content
        return files
