import json
from collections import defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection, transaction
from django.utils import timezone

from gestion.client_identity import client_key
from gestion.models import Clientes


class Command(BaseCommand):
    help = "Preview or merge customers with the same normalized name and phone, with a backup."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--backup", default="artifacts/client-merge-backup.json")

    @transaction.atomic
    def handle(self, *args, **options):
        if connection.vendor == "postgresql" and options["apply"]:
            with connection.cursor() as cursor:
                cursor.execute('LOCK TABLE "clientes" IN SHARE ROW EXCLUSIVE MODE')
        groups = defaultdict(list)
        for row in Clientes.objects.order_by("pk").values():
            key = client_key(row["nombre"], row["telefono"])
            if key:
                groups[key].append(row)
        groups = [rows for rows in groups.values() if len(rows) > 1]
        relations = []
        with connection.cursor() as cursor:
            for table in connection.introspection.table_names(cursor):
                for constraint in connection.introspection.get_constraints(cursor, table).values():
                    if constraint.get("foreign_key") == ("clientes", "id"):
                        if len(constraint["columns"]) != 1:
                            raise CommandError("Unsupported composite customer reference")
                        reference = (table, constraint["columns"][0])
                        if reference not in relations:
                            relations.append(reference)
        quote = connection.ops.quote_name
        backup = {"created_at": timezone.now(), "groups": groups, "references": []}
        for rows in groups:
            ids = [row["id"] for row in rows]
            self.stdout.write(f'{rows[0]["nombre"]}: {ids} -> {ids[0]}')
            for table, column in relations:
                with connection.cursor() as cursor:
                    cursor.execute(f'SELECT * FROM {quote(table)} WHERE {quote(column)} IN ({", ".join(["%s"] * len(ids))})', ids)
                    columns = [col[0] for col in cursor.description]
                    backup["references"].append({"table": table, "column": column,
                                                  "rows": [dict(zip(columns, row)) for row in cursor.fetchall()]})
        if not options["apply"]:
            self.stdout.write(f"Preview: {len(groups)} groups. Use --apply to merge.")
            return
        if not groups:
            self.stdout.write("No duplicate customers.")
            return
        path = Path(options["backup"])
        path.parent.mkdir(parents=True, exist_ok=True)
        # Never overwrite the original pre-merge snapshot.
        with path.open("x", encoding="utf-8") as file:
            json.dump(backup, file, cls=DjangoJSONEncoder, ensure_ascii=False, indent=2)
        moved = 0
        for rows in groups:
            canonical, duplicates = rows[0], rows[1:]
            changes = {}
            notes = [canonical["observaciones"]] if canonical["observaciones"] else []
            for row in duplicates:
                for field in ("ciudad", "direccion"):
                    value, current = row[field], changes.get(field, canonical[field])
                    if value and value != current:
                        if not current or current.strip().casefold() in ("n/a", "sin registrar"):
                            changes[field] = value
                        else:
                            notes.append(f'Registro unificado {row["id"]}, {field}: {value}')
                if row["observaciones"] and row["observaciones"] not in notes:
                    notes.append(row["observaciones"])
                for table, column in relations:
                    with connection.cursor() as cursor:
                        cursor.execute(f'UPDATE {quote(table)} SET {quote(column)} = %s WHERE {quote(column)} = %s', [canonical["id"], row["id"]])
                        moved += cursor.rowcount
                with connection.cursor() as cursor:
                    cursor.execute('DELETE FROM clientes WHERE id = %s', [row["id"]])
            changes["observaciones"] = "\n".join(notes) or None
            changes["actualizado_en"] = timezone.now()
            Clientes.objects.filter(pk=canonical["id"]).update(**changes)
        self.stdout.write(self.style.SUCCESS(f'Merged {sum(len(rows)-1 for rows in groups)} duplicates; moved {moved} references. Backup: {path}'))
