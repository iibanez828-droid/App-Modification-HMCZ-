"""Gestión de usuarios de la app (solo el dueño, desde la terminal).

Lee y escribe `users/users.json` en el mismo lugar que la app:
- con `.streamlit/secrets.toml` y sección [github] → rama `data` de GitHub;
- sin ella → carpeta local `local_data/` (modo de prueba).

Las contraseñas se piden sin mostrarse en pantalla y se guardan cifradas (bcrypt).

    python scripts/users.py list                         ver usuarios
    python scripts/users.py add                          crear usuario (pregunta los datos)
    python scripts/users.py password <usuario>           restablecer contraseña
    python scripts/users.py role <usuario> <admin|supervisor>
    python scripts/users.py rename <usuario> "<Nombre completo>"
    python scripts/users.py deactivate <usuario>         quitar acceso (conserva el historial)
    python scripts/users.py activate <usuario>           devolver acceso
    python scripts/users.py clear                        borrar TODOS los usuarios
    python scripts/users.py master-hash                  generar la sección [master] de los secretos
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from getpass import getpass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.auth import (MIN_PASSWORD, USERS_PATH, User, dump_users, hash_password, load_users,  # noqa: E402
                       master_account, stamp, validate_new)
from storage import StorageError, make_store  # noqa: E402

ROLES = ("admin", "supervisor")
ERRORS = {
    "err_username": "Usuario inválido: 3 a 30 caracteres, solo minúsculas, números, punto, guion o guion bajo.",
    "err_user_exists": "Ese usuario ya existe.",
    "err_password_short": f"La contraseña debe tener al menos {MIN_PASSWORD} caracteres.",
}


def _secrets() -> dict:
    path = ROOT / ".streamlit" / "secrets.toml"
    return tomllib.loads(path.read_text()) if path.exists() else {}


def _ask_password() -> str:
    pw = getpass("Contraseña (no se muestra al escribir): ")
    if len(pw) < MIN_PASSWORD:
        raise SystemExit(ERRORS["err_password_short"])
    if pw != getpass("Repite la contraseña: "):
        raise SystemExit("Las contraseñas no coinciden.")
    return pw


def _get(users: dict[str, User], username: str) -> User:
    user = users.get(username.strip().lower())
    if not user:
        raise SystemExit(f"No existe el usuario «{username}». Usa: python scripts/users.py list")
    return user


def _print(users: dict[str, User]) -> None:
    if not users:
        print("No hay usuarios.")
        return
    print(f"{'USUARIO':<20} {'NOMBRE':<35} {'ROL':<12} ESTADO")
    for u in sorted(users.values(), key=lambda u: (u.role, u.username)):
        print(f"{u.username:<20} {u.name:<35} {u.role:<12} {'activo' if u.active else 'DESACTIVADO'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Gestión de usuarios HCMZ", formatter_class=argparse.RawDescriptionHelpFormatter,
                                     epilog=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sub.add_parser("add")
    sub.add_parser("clear")
    sub.add_parser("master-hash")
    for name in ("password", "deactivate", "activate"):
        sub.add_parser(name).add_argument("username")
    p = sub.add_parser("role")
    p.add_argument("username")
    p.add_argument("role", choices=ROLES)
    p = sub.add_parser("rename")
    p.add_argument("username")
    p.add_argument("name")
    args = parser.parse_args()

    if args.cmd == "master-hash":
        username = input("Usuario maestro: ").strip().lower()
        name = input("Nombre completo: ").strip() or username
        pw_hash = hash_password(_ask_password())
        print("\nPega esto en .streamlit/secrets.toml y en Streamlit Cloud → App settings → Secrets:\n")
        print(f'[master]\nusername = "{username}"\nname = "{name}"\npassword_hash = "{pw_hash}"')
        return

    secrets = _secrets()
    store = make_store(secrets)
    master = master_account(secrets)
    print(f"Datos en: {store.label}\n")
    try:
        users = load_users(store.snapshot())
    except StorageError as exc:
        raise SystemExit(f"No se pudieron leer los usuarios: {exc}")

    if args.cmd == "list":
        _print(users)
        if master:
            print(f"\nUsuario maestro (secretos): {master.username}")
        return

    if args.cmd == "add":
        username = input("Usuario (para iniciar sesión, ej. jperez): ").strip().lower()
        if master and username == master.username:
            raise SystemExit("Ese nombre está reservado para el usuario maestro.")
        err = validate_new(username, "x" * MIN_PASSWORD, users)
        if err:
            raise SystemExit(ERRORS[err])
        name = input("Nombre completo (aparece en la app y en los registros): ").strip()
        if not name:
            raise SystemExit("El nombre completo es obligatorio.")
        role = input("Rol [admin / supervisor]: ").strip().lower()
        if role not in ROLES:
            raise SystemExit("El rol debe ser admin o supervisor.")
        users[username] = stamp(User(username, name, role, hash_password(_ask_password())))
        msg = f"alta de usuario {username} ({role})"
    elif args.cmd == "clear":
        if not users:
            raise SystemExit("No hay usuarios que borrar.")
        _print(users)
        if input("\nEsto borra TODOS los usuarios anteriores. Escribe BORRAR para confirmar: ").strip() != "BORRAR":
            raise SystemExit("Cancelado.")
        users = {}
        msg = "se eliminan todos los usuarios"
    else:
        user = _get(users, args.username)
        if args.cmd == "password":
            user.hash = hash_password(_ask_password())
            msg = f"nueva contraseña para {user.username}"
        elif args.cmd == "role":
            user.role = args.role
            msg = f"rol de {user.username} → {args.role}"
        elif args.cmd == "rename":
            user.name = args.name.strip() or user.name
            msg = f"nombre de {user.username} → {user.name}"
        else:
            user.active = args.cmd == "activate"
            msg = f"{'activación' if user.active else 'desactivación'} de {user.username}"
        users[user.username] = stamp(user)

    try:
        store.write(USERS_PATH, dump_users(users), f"[usuarios] {msg}")
    except StorageError as exc:
        raise SystemExit(f"No se pudo guardar: {exc}")
    print(f"Listo: {msg}.\n")
    _print(users)


if __name__ == "__main__":
    main()
