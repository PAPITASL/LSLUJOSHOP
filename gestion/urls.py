from django.urls import path
from . import views

urlpatterns = [
    path("ordenes/<int:pk>/vista-previa/", views.order_preview, name="order_preview"),
    path("", views.dashboard, name="dashboard"),
    path("api/trm/", views.trm_actual, name="trm_actual"),
    path("api/productos/nuevo/", views.quick_product_create, name="quick_product_create"),
    path("reportes/", views.reports_dashboard, name="reports_dashboard"),
    path("entregas-pendientes/", views.pending_deliveries, name="pending_deliveries"),
    path("ordenes/<int:pk>/recibo/", views.order_receipt, name="order_receipt"),
    path("ordenes/<int:pk>/entrega/", views.order_delivery, name="order_delivery"),
    path("ordenes/<int:pk>/cancelar/", views.order_cancel, name="order_cancel"),
    path("reportes/<str:module>/pdf/", views.module_report, name="module_report"),
    path("importar/<str:module>/", views.excel_import, name="excel_import"),
    path("importar/<str:module>/plantilla/", views.excel_template, name="excel_template"),
    path("gestion/<str:module>/", views.record_list, name="record_list"),
    path("gestion/<str:module>/nuevo/", views.record_form, name="record_create"),
    path("gestion/<str:module>/<int:pk>/editar/", views.record_form, name="record_update"),
    path("gestion/<str:module>/<int:pk>/eliminar/", views.record_delete, name="record_delete"),
]
