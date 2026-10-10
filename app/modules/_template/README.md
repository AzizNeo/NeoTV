# Module skeleton (`_template`)

`flask kernel new-module <name>` copies this folder and replaces `_template` with `<name>`.

| File | Contains | Rule |
|---|---|---|
| `manifest.py` | the module's contract with the kernel | the **only** file the kernel reads |
| `api.py` | public Protocols / DTOs other modules may import | everything else is private |
| `domain.py` | pure rules + named errors | no Flask / SQLAlchemy |
| `models.py` | tables, all prefixed `<name>_` | never referenced by another module |
| `services.py` | use cases, one `UnitOfWork` per use case | events via `uow.outbox.add(...)` |
| `http.py` | blueprint + Pydantic schemas, `@endpoint(...)` only | no business logic |
| `handlers.py` | event consumers `fn(event, *, uow)` | idempotent, no commits |
| `tasks.py` | Celery `shared_task`s named `<name>.*` | resolve services from the container |

Checklist:
1. Add `"app.modules.<name>"` to `INSTALLED_MODULES` (`app/modules/__init__.py`).
2. `flask db migrate -m "<name>: initial"` → review → `flask db upgrade`.
3. Declare permissions (`<name>:<action>`) and give them to roles in `identity/domain.py` if needed.
4. `pytest tests/fitness` must stay green (manifest contract, import boundaries).
5. Frontend: add a feature folder with `backendModule: "<name>"`.
