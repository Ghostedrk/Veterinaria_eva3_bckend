from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models.deletion import ProtectedError
from django.http import Http404
from rest_framework import filters, permissions, serializers, viewsets
from rest_framework.exceptions import APIException, PermissionDenied
from rest_framework.routers import DefaultRouter

from .resources import RESOURCES, is_readonly
from .roles import RolePermission
from .services import delete_record, save_record, set_professional_active
from .views import CONFLICT_MESSAGE, PROTECTED_MESSAGE


class Conflict(APIException):
    status_code = 409
    default_detail = CONFLICT_MESSAGE


def persist(obj, user, *, changed_fields=None):
    try:
        return save_record(obj, user=user, changed_fields=changed_fields)
    except ValidationError as exc:
        raise serializers.ValidationError(getattr(exc, "message_dict", exc.messages)) from exc
    except IntegrityError as exc:
        raise Conflict() from exc
    except type(obj).DoesNotExist as exc:
        raise Http404 from exc


class ClinicSerializer(serializers.ModelSerializer):
    def create(self, validated_data):
        return persist(self.Meta.model(**validated_data), self.context["request"].user)

    def update(self, instance, validated_data):
        for field, value in validated_data.items():
            setattr(instance, field, value)
        return persist(instance, self.context["request"].user, changed_fields=validated_data)


class ClinicViewSet(viewsets.ModelViewSet):
    filter_backends = [filters.SearchFilter]
    permission_classes = [permissions.IsAdminUser, RolePermission]

    def get_queryset(self):
        return self.resource.queryset()

    def perform_update(self, serializer):
        if is_readonly(self.resource, serializer.instance):
            raise PermissionDenied("El registro forma parte del historial.")
        serializer.save()

    def perform_destroy(self, instance):
        if is_readonly(self.resource, instance):
            raise PermissionDenied("El registro forma parte del historial.")
        if self.resource.soft_delete:
            # DELETE desactiva el registro y conserva su historial.
            try:
                set_professional_active(instance, False, user=self.request.user)
            except ValidationError as exc:
                raise Conflict(" ".join(exc.messages)) from exc
            return
        try:
            delete_record(instance)
        except ProtectedError as exc:
            raise Conflict(PROTECTED_MESSAGE) from exc
        except ValidationError as exc:
            raise Conflict(" ".join(exc.messages)) from exc
        except IntegrityError as exc:
            raise Conflict() from exc
        except type(instance).DoesNotExist as exc:
            raise Http404 from exc


class LedgerViewSet(ClinicViewSet):
    http_method_names = ["get", "post", "head", "options"]


def viewset_for(resource):
    name = resource.model.__name__
    all_fields = tuple(dict.fromkeys(("id", *resource.fields, *resource.columns)))
    meta = type("Meta", (), {
        "model": resource.model,
        "fields": all_fields,
        "read_only_fields": tuple(field for field in all_fields if field not in resource.fields),
    })
    serializer = type(f"{name}Serializer", (ClinicSerializer,), {"Meta": meta})
    base = LedgerViewSet if resource.append_only else ClinicViewSet
    return type(f"{name}ViewSet", (base,), {
        "resource": resource, "serializer_class": serializer, "search_fields": resource.search,
    })


router = DefaultRouter()
for slug, resource in RESOURCES.items():
    router.register(slug, viewset_for(resource), basename=slug)

