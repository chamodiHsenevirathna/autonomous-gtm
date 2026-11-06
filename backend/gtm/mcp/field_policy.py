"""Field-ownership check against ops.field_policy (docs/data-model.md section 4). Shared by the MCP tools and the pipeline monitor."""
from __future__ import annotations
from psycopg import Connection
from ..contracts.errors import PolicyDenied


def check_direct_write(conn: Connection, entity: str, field: str, principal: str) -> dict:
    """Return the policy row if `principal` may write (entity, field) directly; otherwise raise PolicyDenied.
    Human-owned fields (write_mode 'proposal') and unknown fields are always denied here: they change only via an approved proposal."""
    row = conn.execute("SELECT * FROM ops.field_policy WHERE entity=%s AND field=%s", (entity, field)).fetchone()
    if row is None:
        raise PolicyDenied(f"no field policy for {entity}.{field}: direct write denied", detail={"entity": entity, "field": field})
    if row["write_mode"] != "direct":
        raise PolicyDenied(f"{entity}.{field} is {row['owner_class']}-owned (write_mode={row['write_mode']}): propose a change instead",
                           detail={"entity": entity, "field": field, "owner_class": row["owner_class"]})
    if principal not in (row["principal_exceptions"] or []):
        raise PolicyDenied(f"{principal} may not write {entity}.{field} directly", detail={"entity": entity, "field": field, "principal": principal})
    return row
