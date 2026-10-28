# HMCZ Truck Modification

App web (Streamlit) para controlar la ejecución de las modificaciones de **12 camiones EH5000 (RD 220 a RD 231)**. La interfaz está en **inglés y japonés**.

- **Supervisores:** registran el avance por tarea de los SOP, las horas-hombre, el supervisor, los técnicos, comentarios y notas de atraso.
- **Administradores:** ven el resumen y las alertas, el Gantt interactivo (por camión o por actividad), ajustan las fechas del pronóstico, registran el avance de cualquier camión, agregan o eliminan camiones, agregan o quitan actividades y subtareas SOP (pestaña **Trucks**), revisan los atrasos y generan el reporte ejecutivo en PDF y la exportación de datos.

---

## Cómo funciona

| Tema                        | Regla                                                                                                                                                                                                      |
| --------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Actividades ↔ SOP**       | High arch → SOP 23 & 24 · Nose cone → SOP 4 · RHS seat screw → SOP 18 · LHS seat screw → SOP 16 **+** SOP 19. Trailing arm lowering/assembly y Trunnion cap/modification no tienen SOP: avance manual en % |
| **Avance de una actividad** | Tareas terminadas ÷ tareas aplicables. Las tareas condicionales (p. ej. reparación de grietas) se pueden marcar **N/A** y dejan de contar                                                                  |
| **Avance de un camión**     | Promedio simple de sus actividades. Del proyecto: promedio de los 12 camiones                                                                                                                              |
| **Avance importado**        | Mientras una actividad no tenga registros en la app, se usa el % del Gantt (RD220 y RD221 aparecen completos)                                                                                              |
| **Puntos HOLD**             | Una tarea HOLD solo puede quedar _Done_ con el resultado de QC _Accepted_                                                                                                                                  |
| **Fechas**                  | **Plan original** fijo (del Gantt) + **pronóstico** editable. El atraso se mide en días hábiles entre ambos                                                                                                |
| **Calendario**              | Lunes a viernes. Sábado y domingo solo si el administrador los habilita para ese camión. Los festivos se configuran                                                                                        |
| **Visibilidad**             | Un camión aparece (y su plan se puede editar) cuando faltan **14 días** o menos para su inicio (configurable). Antes queda oculto                                                                          |
| **Límite de 5 días**        | Se cuentan los días hábiles con trabajo propio programado (sin la espera por el trabajo externo de trunnion). Más de 5 genera una alerta                                                                   |
| **Alerta de trunnion**      | Cuando un camión se activa, el administrador ve una alerta para coordinar con el contratista externo el _Trunnion cap machining_ y la _Trunnion modification_. Se marca como atendida con una nota         |

Todas las reglas están en `core/project.py`. Los valores por defecto están en `core/config.py`.

---

## Estructura

```text
App-Modification-HMCZ-/
├── app.py                    ← Punto de entrada: inicio de sesión, barra lateral y rutas
├── core/                     ← Lógica del negocio (sin interfaz)
│   ├── config.py             ← Actividades, SOP, colores y valores por defecto
│   ├── project.py            ← Calcula el estado actual: avance, estados, atrasos y alertas
│   ├── events.py             ← Registro de cambios (un archivo JSON por acción)
│   ├── workdays.py           ← Calendario laboral (días hábiles, fines de semana, festivos)
│   ├── catalog.py            ← Catálogo de tareas de los SOP
│   ├── auth.py               ← Usuarios y contraseñas (bcrypt)
│   ├── reports.py            ← Exportación de datos en Excel y CSV
│   ├── executive_report.py   ← Reporte ejecutivo en PDF con membrete LANDCROS (fpdf2)
│   └── i18n.py               ← Textos en inglés y japonés
├── storage/                  ← Dónde se guardan los datos
│   ├── github_store.py       ← Rama `data` del repositorio (producción)
│   └── local_store.py        ← Carpeta local_data/ (pruebas, sin token)
├── ui/                       ← Interfaz de Streamlit
│   ├── supervisor.py         ← Vista del supervisor
│   ├── admin.py              ← Vista del administrador (7 pestañas)
│   ├── gantt.py              ← Gantt interactivo (Plotly)
│   ├── common.py             ← Piezas compartidas
│   └── theme.py              ← Estilo LANDCROS
├── seed/                     ← Datos de origen
│   ├── *.xlsx                ← Gantt y SOP originales
│   ├── build_seed.py         ← Convierte los Excel en los CSV de abajo
│   ├── activities_seed.csv   ← Plan original por camión y actividad
│   ├── tasks_catalog.csv     ← 97 tareas de los 5 SOP (EN/JP)
│   └── sop_notes.csv         ← Notas de ingeniería de cada SOP
├── assets/                   ← Logo LANDCROS e imagen del EH5000
├── scripts/users.py          ← Gestión de usuarios (solo el dueño, desde la terminal)
└── tests/                    ← Pruebas automáticas (pytest)
```

### Rama `data` (la escribe la app, no se edita a mano)

```text
plan/baseline.csv             ← Plan original (se copia una vez desde seed/)
plan/settings.json            ← Configuración inicial
users/users.json              ← Usuarios con contraseña cifrada
log/task/AAAA-MM/…json        ← Avance de tareas (un archivo por guardado)
log/delay/…  log/plan/…  log/ack/…  log/settings/…  log/scope/… ← camiones, actividades y tareas SOP agregadas o quitadas
reports/                      ← Reportes publicados desde la app
```

Cada acción crea un archivo nuevo, que nunca se modifica después. Así, dos personas pueden guardar al mismo tiempo sin conflictos y queda el historial completo de quién hizo qué y cuándo. El estado actual se calcula leyendo esos archivos en orden.

---

## Ejecutar en tu Mac (modo local, sin token)

```bash
cd ~/Proyectos/App-Modification-HMCZ-
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
streamlit run app.py
```

Sin archivo de secretos, la app guarda todo en `local_data/` (está en `.gitignore`). Al abrirla por primera vez pide crear el **primer administrador** y carga el plan desde el Gantt.

Pruebas: `pytest -q`

Para empezar de cero en modo local, borra la carpeta `local_data/`.

---

## Conectar con GitHub (producción)

1. El dueño del repositorio crea un **token fine-grained**: _Settings → Developer settings → Personal access tokens → Fine-grained tokens_.
   - **Repository access:** _Only select repositories_ → este repositorio.
   - **Permissions → Repository → Contents:** _Read and write_.
   - **Expiration:** 1 año (GitHub avisa por correo antes de que venza).
2. Copia `.streamlit/secrets.toml.example` como `.streamlit/secrets.toml` y pega el token.
3. En Streamlit Community Cloud, pega el mismo contenido en _App settings → Secrets_.

El token **nunca** se sube al repositorio: `.streamlit/secrets.toml` está en `.gitignore`.

Si el token vence, la app muestra un aviso al guardar. Se genera uno nuevo y se reemplaza en los secretos.

---

## Usuarios

- La app siempre abre en **inicio de sesión**. No tiene pantalla de registro ni gestión de usuarios.
- **Roles:** cada rol ve solo su vista.
  - **Admin:** resumen, Gantt, plan, camiones, atrasos, reportes y configuración del proyecto.
  - **Supervisor:** registro de avance de tareas, horas-hombre, personal y atrasos.
  - **Maestro** (dueño de la app): alterna entre ambas vistas y puede modificar datos en las dos. Se define en los secretos (sección `[master]`), nunca en el archivo de usuarios.
- Los usuarios los crea y modifica **solo el dueño** con `scripts/users.py` desde la terminal. Las contraseñas se guardan cifradas (bcrypt) en `users/users.json`, en el mismo lugar donde lee la app.

```bash
python scripts/users.py list                          # ver usuarios
python scripts/users.py add                           # crear usuario (pregunta usuario, nombre, rol y contraseña)
python scripts/users.py password <usuario>            # restablecer contraseña olvidada
python scripts/users.py role <usuario> admin|supervisor
python scripts/users.py rename <usuario> "Nombre completo"
python scripts/users.py deactivate <usuario>          # quitar acceso (conserva su historial)
python scripts/users.py activate <usuario>
python scripts/users.py clear                         # borrar todos los usuarios
python scripts/users.py master-hash                   # generar la sección [master] de los secretos
```

- Con `.streamlit/secrets.toml` y la sección `[github]`, el script trabaja sobre los **datos reales** (rama `data`); sin ella, sobre `local_data/`. Siempre muestra dónde está escribiendo.
- La app toma los cambios en unos 30 segundos, o al pulsar **Refresh data**. Un usuario desactivado pierde el acceso en su siguiente clic.
- Cada usuario puede cambiar su propia contraseña: los administradores en la pestaña **Settings** y los supervisores en la barra lateral.

---

## Cómo adaptar

| Quiero cambiar…                                                       | Archivo                                                                                       |
| --------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| Días de anticipación, límite de días hábiles, zona horaria o festivos | Desde la app: pestaña **Settings**                                                            |
| Textos en inglés o japonés                                            | `core/i18n.py`                                                                                |
| Actividades o asociación con los SOP                                  | `core/config.py`                                                                              |
| Reglas de avance, estados o alertas                                   | `core/project.py`                                                                             |
| SOP actualizados                                                      | Reemplazar el Excel en `seed/` y ejecutar `python seed/build_seed.py`                         |
| Fechas de un camión en curso                                          | Desde la app: pestaña **Plan** (el plan original ya cargado no cambia al reemplazar el Gantt) |
| Camiones, actividades generales o subtareas SOP de un camión          | Desde la app: pestaña **Trucks** → *Add truck* / *Manage activities* / *Remove truck*                       |
