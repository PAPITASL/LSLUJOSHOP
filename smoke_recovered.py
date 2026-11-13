"""Manual verification helper: only runs in a recovered installation, rolls back writes."""
import json
import os
import secrets
from unittest.mock import patch

from local_runtime import ROOT, exclusive, database, pg_home, run_status

if not (ROOT / 'installation.json').exists():
    raise RuntimeError('Esta prueba solo puede ejecutarse en una recuperacion independiente.')

with exclusive(), database():
    os.environ['DJANGO_SETTINGS_MODULE'] = 'config.desktop_settings'
    import django
    django.setup()
    from django.contrib.auth import get_user_model
    from django.db import transaction, connections
    from django.test import Client
    from gestion.views import MODULES
    from gestion.excel_import import IMPORT_CONFIG
    from gestion.models import Ordenes, Clientes
    from recovery import inventory
    before = inventory()
    checks = []
    with transaction.atomic():
        client = Client(HTTP_HOST='127.0.0.1')
        assert client.get('/').status_code == 302
        assert client.get('/cuentas/login/').status_code == 200
        # Do not guess or reset the owner's password. A disposable account tests the real backend.
        password = secrets.token_urlsafe(20)
        name = 'verification-' + secrets.token_hex(6)
        user = get_user_model().objects.create_user(username=name, password=password, is_staff=True)
        assert not client.login(username=name, password=password + 'incorrect')
        assert client.login(username=name, password=password)
        checks.append('Password backend: wrong password rejected; temporary correct password accepted')
        paths = ['/', '/reportes/', '/reporte-financiero/', '/pagadas/', '/costos-pendientes/',
                 '/entregas-pendientes/', '/bog/']
        paths += [f'/gestion/{module}/' for module in MODULES]
        paths += [f'/importar/{module}/plantilla/' for module in IMPORT_CONFIG]
        paths += ['/reportes/clientes/pdf/', '/reportes/ordenes/pdf/']
        order = Ordenes.objects.order_by('pk').first()
        if order:
            paths += [f'/ordenes/{order.pk}/vista-previa/', f'/ordenes/{order.pk}/recibo/']
        for path in paths:
            response = client.get(path, follow=True)
            assert response.status_code == 200, (path, response.status_code)
            assert response.wsgi_request.path != '/cuentas/login/'
            if response.streaming:
                content = b''.join(response.streaming_content)
                assert content
                if response.headers.get('Content-Type') == 'application/pdf':
                    assert content.startswith(b'%PDF')
            checks.append(path + ' 200')
        from io import BytesIO
        from openpyxl import Workbook
        book = Workbook()
        book.active.append(['Nombre *'])
        imported_name = 'Prueba Excel ' + secrets.token_hex(8)
        book.active.append([imported_name])
        upload = BytesIO()
        book.save(upload)
        upload.seek(0)
        from django.core.files.uploadedfile import SimpleUploadedFile
        response = client.post('/importar/clientes/', {'archivo': SimpleUploadedFile(
            'verificacion.xlsx', upload.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')})
        assert response.status_code == 302 and Clientes.objects.filter(nombre=imported_name).exists()
        checks.append('Excel: real workbook imported; transaction rolled back after verification')
        with patch('gestion.views.obtener_trm_oficial', side_effect=OSError('Offline')):
            response = client.get('/api/trm/')
            assert response.status_code == 503 and 'manualmente' in response.json()['error']
            checks.append('Offline TRM error offers manual entry')
        client.logout()
        assert client.get('/').status_code == 302
        transaction.set_rollback(True)
    assert inventory() == before, 'La prueba dejo cambios de datos'
    connections.close_all()
assert not run_status(pg_home() / 'bin' / 'pg_ctl.exe', ROOT / 'local-data' / 'postgres')
checks.append('Private PostgreSQL stopped; business data unchanged')
(ROOT / 'SMOKE-RESULTS.json').write_text(json.dumps(checks, indent=2), 'utf-8')
print('\n'.join(checks))
