"""Copy the on-disk JSON records into Postgres.

Run this once, after pointing `DATABASE_URL` at your Neon database, to carry an
existing installation across. It is **additive and idempotent**: every write is
an upsert keyed by id, nothing on disk is deleted, and running it twice changes
nothing the second time. If it goes wrong, unset `DATABASE_URL` and the app is
back on the JSON files exactly as they were.

Project *workspaces* are not touched. They stay on disk because they are source
trees the sandbox executes; only the records describing them move.

    cd backend
    python scripts/migrate_json_to_postgres.py            # copy everything
    python scripts/migrate_json_to_postgres.py --dry-run  # report, write nothing
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config.settings import get_settings  # noqa: E402
from app.models.execution import ExecutionRecord  # noqa: E402
from app.models.project import Project  # noqa: E402
from app.models.report import RepairSession  # noqa: E402
from app.models.user import User  # noqa: E402
from app.utils.filesystem import read_json  # noqa: E402


def _load(path: Path, model, label: str):
    payload = read_json(path)
    if payload is None:
        return None
    try:
        return model.model_validate(payload)
    except Exception as exc:  # noqa: BLE001
        print(f"  ! skipping unreadable {label} {path.name}: {exc}")
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report without writing")
    args = parser.parse_args()

    settings = get_settings()
    if not settings.database_url:
        print("DATABASE_URL is not set. Point it at your Neon database and retry.")
        return 2

    from app.db import init_database, redact_dsn
    from app.db.stores import PostgresProjectStore, PostgresRecordStore, PostgresUserStore

    print(f"target : {redact_dsn(settings.database_url)}")
    print(f"source : {settings.data_dir}")
    if args.dry_run:
        print("mode   : DRY RUN — nothing will be written\n")
    else:
        print("mode   : writing (upsert by id; nothing is deleted)\n")

    init_database(settings.database_url)
    users = PostgresUserStore()
    projects = PostgresProjectStore()
    records = PostgresRecordStore()

    counts = {"users": 0, "projects": 0, "sessions": 0, "executions": 0, "skipped": 0}

    # ---- users -----------------------------------------------------------
    users_dir = settings.users_dir
    if users_dir.exists():
        for path in sorted(users_dir.glob("*.json")):
            user = _load(path, User, "user")
            if user is None:
                counts["skipped"] += 1
                continue
            if not args.dry_run:
                users.save(user)
            counts["users"] += 1
            print(f"  user     {user.id}  {user.email}")

    # ---- projects, and everything hanging off them ------------------------
    projects_dir = settings.projects_dir
    if projects_dir.exists():
        for directory in sorted(p for p in projects_dir.iterdir() if p.is_dir()):
            project = _load(directory / "project.json", Project, "project")
            if project is None:
                counts["skipped"] += 1
                continue
            if not args.dry_run:
                projects.save(project)
            counts["projects"] += 1
            print(f"  project  {project.id}  {project.name}  (owner={project.owner})")

            # Sessions and executions reference the project row, so they must
            # be written after it.
            for path in sorted((directory / "sessions").glob("*.json")):
                session = _load(path, RepairSession, "session")
                if session is None:
                    counts["skipped"] += 1
                    continue
                if not args.dry_run:
                    records.save_session(project.id, project.owner, session)
                counts["sessions"] += 1

            for path in sorted((directory / "executions").glob("*.json")):
                record = _load(path, ExecutionRecord, "execution")
                if record is None:
                    counts["skipped"] += 1
                    continue
                if not args.dry_run:
                    records.save_execution(project.id, project.owner, record)
                counts["executions"] += 1

    print(
        "\n{users} user(s), {projects} project(s), {sessions} repair session(s), "
        "{executions} execution(s)".format(**counts)
    )
    if counts["skipped"]:
        print(f"{counts['skipped']} unreadable record(s) skipped — see the lines above")
    if args.dry_run:
        print("\nDry run: nothing was written.")
    else:
        print("\nDone. The JSON files are untouched; delete them once you are satisfied.")

    from app.db import close_pool

    close_pool()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
