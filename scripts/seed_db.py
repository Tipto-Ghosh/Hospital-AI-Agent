"""
One-command database seeder for Our Hospital Database.

Reads and executes all SQL files from data/seed/ in the correct dependency order:
    1. departments.sql  — no FK dependencies
    2. doctors.sql      — depends on departments
    3. hospital_info.sql — no FK dependencies (static lookup)
    4. medications.sql  — no FK dependencies (static lookup + interactions)

Idempotency:
Before running each SQL file the script checks whether the target table
already has rows.  If it does, the file is skipped (unless --force is
passed).  This means it is safe to run the script multiple times without
creating duplicate data.

    First run:  seeds all four tables
    Re-run:     skips all four (data already present)
    With --force: truncates and re-seeds all tables

Usage:
    # Normal run (idempotent)
    python scripts/seed_db.py

    # Force re-seed (destructive — truncates before inserting)
    python scripts/seed_db.py --force

    # Seed only specific files
    python scripts/seed_db.py --only departments doctors

    # Dry-run (shows what would be executed, no DB writes)
    python scripts/seed_db.py --dry-run

Environment:
Reads DATABASE_URL from .env via app/config.py.
The async engine from app/db/base.py is used so this script respects
the same pool settings as the application.

Exit codes:
0 — success (all target files seeded or already present)
1 — one or more files failed
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path

# ── Bootstrap — make sure `app` is importable from project root ──────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ── Load .env BEFORE importing any app module ────────────────────────────
# pydantic-settings reads .env automatically, but only when the Settings
# class is instantiated.  Scripts run outside uvicorn/FastAPI need to load
# the file explicitly so environment variables are available at import time.


def _load_dotenv(dotenv_path: Path) -> None:
    """
    Minimal .env loader — no external dependency required.

    Reads KEY=VALUE lines, strips quotes, and calls os.environ.setdefault()
    so that already-set shell variables are never overridden.
    Variable interpolation (e.g. REDIS_URL=redis://:${REDIS_PASSWORD}@...)
    is resolved against values already present in the environment or
    earlier lines in the same file.
    """
    if not dotenv_path.exists():
        return

    loaded: dict[str, str] = {}
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # Resolve ${VAR} references against already-loaded values + os.environ
        def _expand(m: re.Match[str]) -> str:
            var = m.group(1)
            return loaded.get(var) or os.environ.get(var) or ""

        value = re.sub(r"\$\{(\w+)\}", _expand, value)
        loaded[key] = value
        os.environ.setdefault(key, value)


_load_dotenv(PROJECT_ROOT / ".env")

# Minimal fallback for essential environment variables (required by config)
for _key, _default in [
    ("DATABASE_URL", ""),
    ("REDIS_URL", "redis://localhost:6379/0"),
    ("REDIS_PASSWORD", ""),
    ("CELERY_BROKER_URL", "redis://localhost:6379/1"),
    ("GROQ_API_KEY", "gsk_placeholder"),
    ("JWT_SECRET_KEY", "a" * 64),
]:
    os.environ.setdefault(_key, _default)

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import close_db, get_engine, get_session_factory
from app.logger import logging

# ── Seed files in dependency order ───────────────────────────────────────
# Each entry: (sql_filename, guard_table)
# guard_table: the table we check for existing rows before seeding
# If the table has rows → skip (unless --force)

SEED_FILES: list[tuple[str, str]] = [
    ("departments.sql",   "departments"),
    ("doctors.sql",       "doctors"),
    ("hospital_info.sql", "hospital_info"),
    ("medications.sql",   "medications"),
]

SEED_DIR = PROJECT_ROOT / "data" / "seed"


# ── SQL statement splitter ────────────────────────────────────────────────

def _split_statements(sql: str) -> list[str]:
    """
    Split a SQL file into individual executable statements.

    Handles:
    - Single-line comments (-- ...)
    - Multi-line comments (/* ... */) — stripped
    - Statement delimiter: semicolon
    - Empty statements after stripping
    - MySQL USE and SET statements (kept as-is)

    Returns a list of non-empty SQL statement strings.
    """
    # Remove block comments
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)

    statements: list[str] = []
    current: list[str] = []

    for line in sql.splitlines():
        stripped = line.rstrip()

        # Skip pure comment lines and empty lines
        if stripped.lstrip().startswith("--") or not stripped.strip():
            continue

        current.append(stripped)

        # Statement ends at semicolon
        if stripped.rstrip().endswith(";"):
            stmt = " ".join(current).strip()
            if stmt and stmt != ";":
                statements.append(stmt)
            current = []

    # Flush any unterminated statement (shouldn't happen in well-formed SQL)
    if current:
        stmt = " ".join(current).strip()
        if stmt:
            statements.append(stmt)

    return statements


# ── Row-count check ───────────────────────────────────────────────────────

async def _table_has_rows(session: AsyncSession, table: str) -> bool:
    """Return True if the target table already contains at least one row."""
    try:
        result = await session.execute(
            text(f"SELECT COUNT(*) FROM `{table}`")  # noqa: S608
        )
        count = result.scalar_one()
        return int(count) > 0
    except Exception:
        # Table doesn't exist yet (pre-migration run) — treat as empty
        return False


async def _truncate_table(session: AsyncSession, table: str) -> None:
    """Truncate a table (used with --force)."""
    # Disable FK checks temporarily so we can truncate in any order
    await session.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
    await session.execute(text(f"TRUNCATE TABLE `{table}`"))  # noqa: S608
    await session.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
    logging.info("  Truncated table: %s", table)


# ── Per-file seed runner ──────────────────────────────────────────────────

async def _seed_file(
    session: AsyncSession,
    sql_file: Path,
    guard_table: str,
    force: bool = False,
    dry_run: bool = False,
) -> tuple[str, str]:
    """
    Execute a single SQL seed file.

    Returns (filename, status) where status is one of:
        'seeded'   — rows inserted successfully
        'skipped'  — table already had rows and force=False
        'dry_run'  — would have seeded (dry_run=True)
        'error'    — an exception occurred
    """
    filename = sql_file.name

    if not sql_file.exists():
        logging.error("Seed file not found: %s", sql_file)
        return filename, "error"

    already_seeded = await _table_has_rows(session, guard_table)

    if already_seeded and not force:
        logging.info("  [SKIP] %s — %s already has data", filename, guard_table)
        return filename, "skipped"

    if dry_run:
        logging.info("  [DRY-RUN] %s — would seed %s", filename, guard_table)
        return filename, "dry_run"

    sql_content = sql_file.read_text(encoding="utf-8")
    statements = _split_statements(sql_content)

    if force and already_seeded:
        await _truncate_table(session, guard_table)
        # For doctors.sql we also need to truncate doctor_schedules
        if guard_table == "doctors":
            await _truncate_table(session, "doctor_schedules")

    logging.info("  [SEED] %s — executing %d statements ...", filename, len(statements))

    executed = 0
    skipped_statements = 0
    for stmt in statements:
        # Skip USE <database> statements — the connection is already on the right DB
        if re.match(r"^\s*USE\s+\w+\s*;?\s*$", stmt, re.IGNORECASE):
            skipped_statements += 1
            continue
        try:
            await session.execute(text(stmt))
            executed += 1
        except Exception as exc:
            logging.error(
                "  Error in %s:\n  Statement: %.120s\n  Error: %s",
                filename, stmt, exc
            )
            raise

    await session.commit()
    logging.info(
        "  [OK] %s — %d statements executed (%d skipped).",
        filename, executed, skipped_statements,
    )
    return filename, "seeded"


# ── Main async runner ─────────────────────────────────────────────────────

async def run_seed(
    force: bool = False,
    dry_run: bool = False,
    only: list[str] | None = None,
) -> bool:
    """
    Run all seed files in order.

    Parameters
    ----------
    force    : Truncate and re-seed even if data already exists.
    dry_run  : Show what would be done without writing to DB.
    only     : If provided, seed only files whose base names (without .sql)
               are in this list. E.g. ['departments', 'doctors'].

    Returns True if all targeted files succeeded.
    """
    logging.info("=" * 60)
    logging.info("City General Hospital — Database Seed Runner")
    logging.info("Seed directory : %s", SEED_DIR)
    logging.info("Force re-seed  : %s", force)
    logging.info("Dry run        : %s", dry_run)
    if only:
        logging.info("Only files     : %s", only)
    logging.info("=" * 60)

    results: dict[str, str] = {}
    success = True

    async with get_session_factory()() as session:
        for sql_filename, guard_table in SEED_FILES:
            base_name = sql_filename.replace(".sql", "")

            # Filter by --only if specified
            if only and base_name not in only:
                logging.info("  [SKIP] %s — not in --only list", sql_filename)
                continue

            sql_file = SEED_DIR / sql_filename

            try:
                name, status = await _seed_file(
                    session=session,
                    sql_file=sql_file,
                    guard_table=guard_table,
                    force=force,
                    dry_run=dry_run,
                )
                results[name] = status
            except Exception as exc:
                logging.error("  [FAIL] %s — %s", sql_filename, exc)
                results[sql_filename] = "error"
                success = False
                # Rollback the current session and continue with remaining files
                await session.rollback()

    # ── Summary ───────────────────────────────────────────────────────────
    logging.info("")
    logging.info("── Seed Summary " + "─" * 44)
    status_icons = {
        "seeded":   "✓",
        "skipped":  "–",
        "dry_run":  "~",
        "error":    "✗",
    }
    for fname, status in results.items():
        icon = status_icons.get(status, "?")
        logging.info("  %s  %-35s  %s", icon, fname, status.upper())
    logging.info("─" * 60)

    counts = {s: sum(1 for v in results.values() if v == s)
              for s in ("seeded", "skipped", "dry_run", "error")}
    logging.info(
        "  Seeded: %d  |  Skipped: %d  |  Dry-run: %d  |  Errors: %d",
        counts["seeded"], counts["skipped"], counts["dry_run"], counts["error"],
    )

    if not success:
        logging.error("One or more seed files failed. Check logs above.")

    return success


# ── Entry point ───────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed the City General Hospital database with reference data.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/seed_db.py                          # Normal idempotent run
  python scripts/seed_db.py --force                  # Truncate and re-seed all
  python scripts/seed_db.py --only departments doctors
  python scripts/seed_db.py --dry-run                # Preview only
""",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Truncate tables and re-seed even if data already exists.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Show what would be seeded without writing to the database.",
    )
    parser.add_argument(
        "--only",
        nargs="+",
        metavar="FILE",
        help="Seed only the named files (without .sql extension). "
             "e.g. --only departments doctors",
    )
    return parser.parse_args()


async def _main() -> None:
    args = _parse_args()
    try:
        success = await run_seed(
            force=args.force,
            dry_run=args.dry_run,
            only=args.only,
        )
    finally:
        await close_db()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(_main())