from rest_framework.pagination import PageNumberPagination


class Pagination(PageNumberPagination):
    """Permite ?page_size= (hasta 200) para llenar listas desplegables del frontend."""

    page_size_query_param = "page_size"
    max_page_size = 200
