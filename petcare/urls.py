from django.contrib import admin
from django.contrib.auth import views as auth
from django.urls import include, path

from clinic import clinical_views as clinica
from clinic import purchase_views as compras
from clinic import reports
from clinic import views
from clinic.api import router

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("ingresar/", auth.LoginView.as_view(template_name="clinic/login.html"), name="login"),
    path("salir/", auth.LogoutView.as_view(), name="logout"),
    path("contrasena/", auth.PasswordChangeView.as_view(
        template_name="clinic/password.html", success_url="/"), name="password-change"),
    path("agenda/", views.calendar, name="calendar"),
    path("cuentas/", views.accounts, name="accounts"),
    path("cuentas/<int:pk>/acceso/", views.account_status, name="account-status"),
    path("cuentas/<int:pk>/rol/", views.account_role, name="account-role"),
    path("profesionales/<int:pk>/estado/", views.professional_status, name="professional-status"),
    path("gestion/<slug:slug>/", views.record_list, name="record-list"),
    path("gestion/<slug:slug>/nuevo/", views.record_form, name="record-create"),
    path("gestion/<slug:slug>/<int:pk>/", views.record_detail, name="record-detail"),
    path("gestion/<slug:slug>/<int:pk>/editar/", views.record_form, name="record-edit"),
    path("gestion/<slug:slug>/<int:pk>/eliminar/", views.record_delete, name="record-delete"),
    path("compras/", compras.purchase_list, name="purchase-list"),
    path("compras/nueva/", compras.purchase_form, name="purchase-create"),
    path("compras/<int:pk>/", compras.purchase_detail, name="purchase-detail"),
    path("compras/<int:pk>/editar/", compras.purchase_form, name="purchase-edit"),
    path("compras/<int:pk>/pagar/", compras.purchase_pay, name="purchase-pay"),
    path("compras/<int:pk>/anular/", compras.purchase_cancel, name="purchase-cancel"),
    path("compras/webpay/retorno/", compras.webpay_return, name="webpay-return"),
    path("atenciones/<int:pk>/adjuntos/", clinica.attachment_upload, name="attachment-upload"),
    path("adjuntos/<int:pk>/", clinica.attachment_file, name="attachment-file"),
    path("adjuntos/<int:pk>/eliminar/", clinica.attachment_delete, name="attachment-delete"),
    path("citas/<int:pk>/enviar-enlace/", clinica.appointment_send_link, name="appointment-send-link"),
    path("consentimientos/", clinica.consent_list, name="consent-list"),
    path("consentimientos/nuevo/", clinica.consent_create, name="consent-create"),
    path("consentimientos/<int:pk>/", clinica.consent_detail, name="consent-detail"),
    path("tutor/cita/<str:token>/", clinica.tutor_appointment, name="tutor-appointment"),
    path("tutor/consentimiento/<str:token>/", clinica.tutor_consent, name="tutor-consent"),
    path("estadisticas/", reports.dashboard, name="reports"),
    path("reportes/", reports.export_form, name="reports-export-form"),
    path("reportes/descargar/", reports.export, name="reports-export"),
    path("api/", include(router.urls)),
    path("admin/", admin.site.urls),
]

