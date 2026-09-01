import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.core.cache import cache
from django.utils import timezone


TRM_API_URL = "https://www.datos.gov.co/resource/mcec-87by.json"


def obtener_trm_oficial():
    """Obtiene la última TRM publicada y conserva una copia por seis horas."""
    cached = cache.get("trm_oficial_colombia")
    if cached:
        return cached

    query = urlencode({
        "$select": "valor,vigenciadesde,vigenciahasta",
        "$order": "vigenciadesde DESC",
        "$limit": 10,
    })
    request = Request(
        f"{TRM_API_URL}?{query}",
        headers={"User-Agent": "LujoShop/1.0", "Accept": "application/json"},
    )
    with urlopen(request, timeout=8) as response:
        rows = json.load(response)
    if not rows:
        raise ValueError("El servicio oficial no devolvió una tasa vigente.")

    today = timezone.localdate()
    current = rows[0]
    for row in rows:
        try:
            start = timezone.datetime.fromisoformat(row["vigenciadesde"]).date()
            end = timezone.datetime.fromisoformat(row["vigenciahasta"]).date()
            if start <= today <= end:
                current = row
                break
        except (KeyError, ValueError):
            continue

    try:
        value = Decimal(str(current["valor"]))
    except (KeyError, InvalidOperation) as error:
        raise ValueError("La tasa recibida no tiene un formato válido.") from error

    result = {
        "valor": str(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)),
        "vigencia_desde": current.get("vigenciadesde"),
        "vigencia_hasta": current.get("vigenciahasta"),
    }
    cache.set("trm_oficial_colombia", result, 60 * 60 * 6)
    return result
