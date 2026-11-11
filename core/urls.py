from django.contrib.auth import views as auth_views
from django.urls import path
from django.views.generic import RedirectView

from . import views as v

urlpatterns = [
    path("favicon.ico", RedirectView.as_view(url="/static/favicon.svg", permanent=True)),
    path("login/", auth_views.LoginView.as_view(redirect_authenticated_user=True), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", v.dashboard, name="dashboard"),

    path("inventory/", v.MaterialList.as_view(), name="material_list"),
    path("inventory/new/", v.MaterialCreate, name="material_create"),
    path("inventory/<int:pk>/", v.MaterialDetail.as_view(), name="material_detail"),
    path("inventory/<int:pk>/edit/", v.MaterialUpdate, name="material_update"),
    path("inventory/<int:pk>/delete/", v.MaterialDelete, name="material_delete"),
    path("inventory/<int:pk>/movement/", v.MovementCreate.as_view(), name="movement_create"),

    path("orders/", v.OrderList.as_view(), name="order_list"),
    path("orders/new/", v.OrderCreate, name="order_create"),
    path("orders/<int:pk>/", v.OrderDetail.as_view(), name="order_detail"),
    path("orders/<int:pk>/edit/", v.OrderUpdate, name="order_update"),
    path("orders/<int:pk>/delete/", v.OrderDelete, name="order_delete"),
    path("orders/<int:pk>/advance/", v.order_advance, name="order_advance"),

    path("production/", v.ProductionList.as_view(), name="production_list"),
    path("production/new/", v.ProductionCreate, name="production_create"),
    path("production/<int:pk>/edit/", v.ProductionUpdate, name="production_update"),
    path("production/<int:pk>/delete/", v.ProductionDelete, name="production_delete"),

    path("targets/", v.TargetList.as_view(), name="target_list"),
    path("targets/new/", v.TargetCreate, name="target_create"),
    path("targets/<int:pk>/edit/", v.TargetUpdate, name="target_update"),
    path("targets/<int:pk>/delete/", v.TargetDelete, name="target_delete"),

    path("machines/", v.MachineList.as_view(), name="machine_list"),
    path("machines/new/", v.MachineCreate, name="machine_create"),
    path("machines/<int:pk>/edit/", v.MachineUpdate, name="machine_update"),
    path("machines/<int:pk>/delete/", v.MachineDelete, name="machine_delete"),

    path("downtime/", v.DowntimeList.as_view(), name="downtime_list"),
    path("downtime/new/", v.DowntimeCreate, name="downtime_create"),
    path("downtime/<int:pk>/edit/", v.DowntimeUpdate, name="downtime_update"),
    path("downtime/<int:pk>/delete/", v.DowntimeDelete, name="downtime_delete"),
    path("downtime/<int:pk>/resolve/", v.downtime_resolve, name="downtime_resolve"),

    path("defects/", v.DefectList.as_view(), name="defect_list"),
    path("defects/new/", v.DefectCreate, name="defect_create"),
    path("defects/<int:pk>/edit/", v.DefectUpdate, name="defect_update"),
    path("defects/<int:pk>/delete/", v.DefectDelete, name="defect_delete"),

    path("reports/", v.reports, name="reports"),
]
