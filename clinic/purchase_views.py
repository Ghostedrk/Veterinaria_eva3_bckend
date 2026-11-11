from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, F
from django.forms import inlineformset_factory
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from . import purchases, webpay
from .models import Insumo, ItemOrden, OrdenCompra
from .views import staff_required

OrderForm = forms.modelform_factory(OrdenCompra, fields=("proveedor", "observacion"))


def item_formset(extra):
    return inlineformset_factory(
        OrdenCompra, ItemOrden, fields=("insumo", "cantidad", "precio_unitario"),
        extra=extra, min_num=1, validate_min=True, can_delete=True,
    )


@staff_required
@require_safe
def purchase_list(request):
    orders = OrdenCompra.objects.annotate(n_items=Count("items"))
    state = request.GET.get("estado", "")
    if state in OrdenCompra.Estado.values:
        orders = orders.filter(estado=state)
    page = Paginator(orders, 20).get_page(request.GET.get("page"))
    return render(request, "clinic/purchase_list.html", {
        "page": page, "state": state, "states": OrdenCompra.Estado.choices,
    })


@staff_required
@require_http_methods(["GET", "HEAD", "POST"])
def purchase_form(request, pk=None):
    order = get_object_or_404(OrdenCompra, pk=pk) if pk else None
    if order is not None and not order.editable:
        messages.error(request, "Solo se pueden editar órdenes en borrador o con pago no realizado.")
        return redirect("purchase-detail", pk=order.pk)

    initial = []
    if order is None and request.GET.get("reponer"):
        # Prellena con los insumos en stock mínimo para llevarlos al doble del mínimo.
        for item in Insumo.objects.filter(stock__lte=F("minimo")):
            initial.append({"insumo": item.pk, "cantidad": max(item.minimo * 2 - item.stock, 1)})
    Formset = item_formset(extra=max(len(initial), 3) if order is None else 2)

    form = OrderForm(request.POST or None, instance=order)
    formset = Formset(request.POST or None, instance=order or OrdenCompra(), initial=initial or None,
                      prefix="items")
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        with transaction.atomic():
            saved = form.save(commit=False)
            if order is None:
                saved.creada_por = request.user
            saved.save()
            formset.instance = saved
            formset.save()
            purchases.update_total(saved)
        messages.success(request, "Orden de compra guardada.")
        return redirect("purchase-detail", pk=saved.pk)
    return render(request, "clinic/purchase_form.html", {"form": form, "formset": formset, "order": order})


@staff_required
@require_safe
def purchase_detail(request, pk):
    order = get_object_or_404(OrdenCompra.objects.select_related("creada_por", "pagada_por"), pk=pk)
    return render(request, "clinic/purchase_detail.html", {
        "order": order, "items": order.items.select_related("insumo"),
    })


@staff_required
@require_POST
def purchase_pay(request, pk):
    order = get_object_or_404(OrdenCompra, pk=pk)
    return_url = request.build_absolute_uri(reverse("webpay-return"))
    try:
        data = purchases.start_payment(order, user=request.user, return_url=return_url)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    except webpay.WebpayError as exc:
        messages.error(request, f"No se pudo iniciar el pago. {exc}")
    else:
        return render(request, "clinic/webpay_redirect.html", {"order": order, "webpay": data})
    return redirect("purchase-detail", pk=order.pk)


@staff_required
@require_POST
def purchase_cancel(request, pk):
    with transaction.atomic():
        order = get_object_or_404(OrdenCompra.objects.select_for_update(), pk=pk)
        if order.editable:
            order.estado = OrdenCompra.Estado.ANULADA
            order.save(update_fields=["estado"])
            messages.success(request, "Orden anulada.")
        else:
            messages.error(request, "Esta orden ya no se puede anular.")
    return redirect("purchase-detail", pk=order.pk)


@csrf_exempt  # Webpay regresa con un POST desde su dominio; el token se valida con Transbank.
@require_http_methods(["GET", "POST"])
def webpay_return(request):
    data = request.POST if request.method == "POST" else request.GET
    token, aborted, buy_order = data.get("token_ws"), data.get("TBK_TOKEN"), data.get("TBK_ORDEN_COMPRA")
    order = None
    if aborted and webpay.valid_token(aborted):
        order = purchases.cancel_payment(token=aborted, reason="El pago se canceló en Webpay.")
    elif token and webpay.valid_token(token):
        order = purchases.confirm_payment(token)
    elif buy_order:
        order = purchases.cancel_payment(buy_order=buy_order[:26],
                                         reason="Se agotó el tiempo para completar el pago.")
    if order is None:
        messages.error(request, "No se encontró una orden pendiente para esta respuesta de Webpay.")
        return redirect("purchase-list")
    if order.estado == OrdenCompra.Estado.PAGADA:
        messages.success(request, "Pago aprobado. El stock se actualizó.")
    else:
        messages.error(request, order.detalle_pago)
    return redirect("purchase-detail", pk=order.pk)
