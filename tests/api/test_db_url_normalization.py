from api.dependencies import _normalize_async_db_url as n
def test_postgresql_plain():
    assert n("postgresql://u:p@host/db") == "postgresql+asyncpg://u:p@host/db"
def test_postgres_legacy():
    assert n("postgres://u:p@host/db") == "postgresql+asyncpg://u:p@host/db"
def test_already_async_passthrough():
    assert n("postgresql+asyncpg://u:p@host/db") == "postgresql+asyncpg://u:p@host/db"
def test_other_scheme_untouched():
    assert n("sqlite+aiosqlite:///x.db") == "sqlite+aiosqlite:///x.db"
