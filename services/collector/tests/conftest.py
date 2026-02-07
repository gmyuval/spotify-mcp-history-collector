"""Shared test configuration and fixtures for collector tests."""

from sqlalchemy import BigInteger
from sqlalchemy.ext.compiler import compiles


# Register a compilation rule so BigInteger renders as INTEGER on SQLite,
# which enables autoincrement on primary key columns during tests.
@compiles(BigInteger, "sqlite")  # type: ignore[misc]
def _compile_big_integer_sqlite(type_: BigInteger, compiler: object, **kw: object) -> str:
    return "INTEGER"
