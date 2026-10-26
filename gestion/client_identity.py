"""Shared rules for matching customers and searching their contact details."""
import re
import unicodedata


def normalized_text(value):
    text = unicodedata.normalize("NFKD", value or "")
    return " ".join("".join(c for c in text if not unicodedata.combining(c)).casefold().split())


def normalized_phone(value):
    digits = re.sub(r"\D", "", value or "")
    return digits[2:] if len(digits) == 12 and digits.startswith("57") else digits


def client_key(nombre, telefono):
    name, phone = normalized_text(nombre), normalized_phone(telefono)
    return (name, phone) if name and phone else None


def matching_client_ids(records, query):
    words = normalized_text(query).split()
    phone = normalized_phone(query)
    phone_query = bool(phone) and not any(c.isalpha() for c in query)
    return [row["pk"] for row in records.values("pk", "nombre", "telefono", "ciudad", "direccion")
            if (phone_query and phone in normalized_phone(row["telefono"]))
            or (not phone_query and all(word in normalized_text(" ".join(
                row[field] or "" for field in ("nombre", "telefono", "ciudad", "direccion")
            )) for word in words))]
