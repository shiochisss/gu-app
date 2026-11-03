"""Shared physical column definitions; time values are supplied through Clock."""

from uuid import uuid4

from sqlalchemy import Boolean, CheckConstraint, Column, Integer, String, text
from sqlalchemy.dialects.mysql import CHAR

UUID = CHAR(36, charset="ascii", collation="ascii_bin")
HASH = CHAR(64, charset="ascii", collation="ascii_bin")
OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_bin",
}


def string(length):
    return String(length, collation="utf8mb4_0900_bin")


def new_id():
    return Column(UUID, primary_key=True, default=lambda: str(uuid4()))


def version():
    return Column(Integer, nullable=False, default=0, server_default=text("0"))


def flag(default):
    return Column(
        Boolean(create_constraint=True),
        nullable=False,
        default=default,
        server_default=text("1" if default else "0"),
    )


def choice(column, values, name):
    quoted = ", ".join(repr(value) for value in values)
    return CheckConstraint(f"{column} IN ({quoted})", name=name)
