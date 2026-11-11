from django.contrib import admin
from django.contrib.auth import views as auth
from django.urls import include, path

from clinic import purchase_views as compras
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
    path("api/", include(router.urls)),
    path("admin/", admin.site.urls),
]

