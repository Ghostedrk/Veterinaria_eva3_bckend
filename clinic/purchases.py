"""Órdenes de compra de insumos pagadas con Webpay (ambiente de integración)."""
import time

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from . import webpay
from .models import Movimiento, OrdenCompra
from .services import save_record


def update_total(order):
    order.total = order.items.aggregate(total=Sum(F("cantidad") * F("precio_unitario")))["total"] or 0
    order.save(update_fields=["total"])


@transaction.atomic
def start_payment(order, *, user, return_url):
    order = OrdenCompra.objects.select_for_update().get(pk=order.pk)
    if not order.editable:
        raise ValidationError("Esta orden no se puede pagar en su estado actual.")
    update_total(order)
    if not order.total:
        raise ValidationError("Agrega al menos un insumo antes de pagar.")
    # Cada intento usa una orden distinta en Webpay para permitir reintentos.
    buy_order = f"OC{order.pk}T{int(time.time())}"[:26]
    data = webpay.create_transaction(buy_order, f"U{user.pk}", order.total, return_url)
    order.estado = OrdenCompra.Estado.PENDIENTE
    order.orden_webpay = buy_order
    order.token_webpay = data["token"]
    order.pagada_por = user
    order.detalle_pago = "Esperando respuesta de Webpay."
    order.save()
    return data


@transaction.atomic
def confirm_payment(token):
    order = OrdenCompra.objects.select_for_update().filter(token_webpay=token).first()
    if order is None or order.estado != OrdenCompra.Estado.PENDIENTE:
        return order
    try:
        result = webpay.commit_transaction(token)
    except webpay.WebpayError as exc:
        return _reject(order, f"No se pudo confirmar el pago. {exc}")

    approved = (
        result.get("status") == "AUTHORIZED" and result.get("response_code") == 0
        and result.get("amount") == order.total and result.get("buy_order") == order.orden_webpay
    )
    if not approved:
        return _reject(order, f"Webpay no aprobó el pago (código {result.get('response_code')}).")

    order.estado = OrdenCompra.Estado.PAGADA
    order.pagada_en = timezone.now()
    order.codigo_autorizacion = str(result.get("authorization_code", ""))[:20]
    order.tarjeta = str((result.get("card_detail") or {}).get("card_number", ""))[-4:]
    order.detalle_pago = "Pago aprobado. Los insumos ingresaron al inventario."
    order.save()
    for item in order.items.select_related("insumo"):
        save_record(Movimiento(insumo=item.insumo, tipo=Movimiento.Tipo.ENTRADA, cantidad=item.cantidad,
                               motivo=f"Compra {order.numero} pagada con Webpay"), user=order.pagada_por)
    return order


@transaction.atomic
def cancel_payment(*, token=None, buy_order=None, reason):
    orders = OrdenCompra.objects.select_for_update().filter(estado=OrdenCompra.Estado.PENDIENTE)
    if token:
        order = orders.filter(token_webpay=token).first()
    elif buy_order:
        order = orders.filter(orden_webpay=buy_order).first()
    else:
        order = None
    return _reject(order, reason) if order else None


def _reject(order, reason):
    order.estado = OrdenCompra.Estado.RECHAZADA
    order.detalle_pago = reason[:200]
    order.save(update_fields=["estado", "detalle_pago"])
    return order
