"""Almacenamiento en la rama `data` del repositorio de GitHub.

- Lectura: pide el último commit de la rama y descarga ese commit completo en
  un solo paquete (tarball). Descargar por commit, y no por nombre de rama,
  evita recibir una copia en caché anterior al último guardado.
- Escritura: crea o reemplaza un archivo con la API de contenidos. Cada
  escritura es un commit en la rama `data`; la rama `main` (el código) no se
  toca, así que la app no se reinicia al guardar.
"""

from __future__ import annotations

import base64
import io
import tarfile
from urllib.parse import quote

import requests

from storage.base import StorageError, Store

API = "https://api.github.com"
TIMEOUT = 30


class GitHubStore(Store):
    def __init__(self, token: str, repo: str, branch: str = "data") -> None:
        super().__init__()
        if not token or "/" not in repo:
            raise StorageError("Configuración de GitHub incompleta (token o repo).")
        self.repo = repo.strip()
        self.branch = branch.strip() or "data"
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token.strip()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    @property
    def label(self) -> str:
        return f"GitHub · {self.repo}@{self.branch}"

    # ── Errores legibles ────────────────────────────────────────────────
    def _check(self, resp: requests.Response, action: str) -> None:
        if resp.ok:
            return
        hints = {
            401: "El token no es válido o venció. Genera uno nuevo y actualiza los secretos.",
            403: "El token no tiene permiso de escritura (Contents: Read and write) o se alcanzó el límite de la API.",
            404: f"No se encontró el repositorio «{self.repo}» o la rama «{self.branch}», o el token no tiene acceso.",
        }
        detail = hints.get(resp.status_code, resp.text[:200])
        raise StorageError(f"GitHub ({action}) respondió {resp.status_code}: {detail}")

    def _contents_url(self, path: str) -> str:
        return f"{API}/repos/{self.repo}/contents/{quote(path)}"

    # ── Lectura ─────────────────────────────────────────────────────────
    def _head_sha(self) -> str | None:
        """SHA del último commit de la rama (una petición liviana); None si no se puede obtener."""
        try:
            resp = self.session.get(f"{API}/repos/{self.repo}/commits/{quote(self.branch)}",
                                    headers={"Accept": "application/vnd.github.sha"}, timeout=TIMEOUT)
        except requests.RequestException:
            return None
        sha = resp.text.strip() if resp.ok else ""
        return sha if len(sha) == 40 and all(c in "0123456789abcdef" for c in sha) else None

    def read_all(self) -> dict[str, bytes]:
        ref = self._head_sha() or self.branch
        try:
            resp = self.session.get(f"{API}/repos/{self.repo}/tarball/{quote(ref)}", timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise StorageError(f"No hay conexión con GitHub: {exc}") from exc
        self._check(resp, "leer datos")
        files: dict[str, bytes] = {}
        with tarfile.open(fileobj=io.BytesIO(resp.content), mode="r:gz") as tar:
            for member in tar.getmembers():
                if not member.isfile():
                    continue
                # El primer nivel es "<owner>-<repo>-<sha>/"; se descarta.
                parts = member.name.split("/", 1)
                if len(parts) < 2 or parts[1].rsplit("/", 1)[-1].startswith("."):
                    continue
                handle = tar.extractfile(member)
                if handle is not None:
                    files[parts[1]] = handle.read()
        return files

    # ── Escritura ───────────────────────────────────────────────────────
    def _current_sha(self, path: str) -> str | None:
        resp = self.session.get(self._contents_url(path), params={"ref": self.branch}, timeout=TIMEOUT)
        if resp.status_code == 404:
            return None
        self._check(resp, "consultar archivo")
        return resp.json().get("sha")

    def _write(self, path: str, content: bytes, message: str) -> None:
        body = {
            "message": message,
            "content": base64.b64encode(content).decode(),
            "branch": self.branch,
        }
        try:
            for attempt in range(3):
                resp = self.session.put(self._contents_url(path), json=body, timeout=TIMEOUT)
                # 409/422: el archivo ya existe o cambió mientras tanto → pedir su SHA y reintentar
                if resp.status_code in (409, 422) and attempt < 2:
                    sha = self._current_sha(path)
                    if sha:
                        body["sha"] = sha
                    continue
                break
        except requests.RequestException as exc:
            raise StorageError(f"No hay conexión con GitHub: {exc}") from exc
        self._check(resp, "guardar")
