import csv
from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import Count, F, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from . import forms, models
from .models import (
    STAGE_CHOICES, STAGE_ORDER, STAGE_UNITS, DailyTarget, DefectRecord, DowntimeRecord,
    Machine, Material, ProductionOrder, StageLog, StockMovement,
)

STAGE_COLORS = {"spinning": "#D98324", "weaving": "#3149C6", "finishing": "#0F8F7F"}


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------
@login_required
def dashboard(request):
    today = timezone.localdate()
    now = timezone.now()

    # Today's line: output vs target per stage, with machine health.
    targets = {t.stage: t.target_qty for t in DailyTarget.objects.filter(date=today)}
    outputs = {
        r["stage"]: r["t"]
        for r in StageLog.objects.filter(date=today).values("stage").annotate(t=Sum("quantity"))
    }
    waste = {
        r["stage"]: r["t"]
        for r in StageLog.objects.filter(date=today).values("stage").annotate(t=Sum("waste"))
    }
    down_ids = set(
        DowntimeRecord.objects.filter(ended_at__isnull=True).values_list("machine_id", flat=True)
    )
    line = []
    for stage, label in STAGE_CHOICES:
        machines = list(Machine.objects.filter(stage=stage, is_active=True))
        down = sum(1 for m in machines if m.pk in down_ids)
        actual = outputs.get(stage) or Decimal(0)
        target = targets.get(stage)
        pct = int(actual / target * 100) if target else None
        line.append({
            "stage": stage, "label": label, "unit": STAGE_UNITS[stage],
            "actual": actual, "target": target, "pct": pct, "bar": min(pct or 0, 100),
            "waste": waste.get(stage) or Decimal(0),
            "machines": len(machines), "down": down, "running": len(machines) - down,
        })

    # KPIs
    since30 = today - timedelta(days=29)
    weaving30 = StageLog.objects.filter(stage="weaving", date__gte=since30).aggregate(t=Sum("quantity"))["t"] or 0
    rejected30 = DefectRecord.objects.filter(date__gte=since30, disposition="scrap").aggregate(t=Sum("quantity"))["t"] or 0
    defective30 = DefectRecord.objects.filter(date__gte=since30).aggregate(t=Sum("quantity"))["t"] or 0
    low_stock = [m for m in Material.objects.all() if m.is_low]
    active_orders = ProductionOrder.objects.filter(status="in_progress")
    kpis = {
        "active_orders": active_orders.count(),
        "overdue": sum(1 for o in active_orders if o.is_overdue),
        "machines_down": len(down_ids),
        "machines_total": Machine.objects.filter(is_active=True).count(),
        "reject_rate": round(float(rejected30) / float(weaving30) * 100, 2) if weaving30 else 0,
        "defective30": defective30,
        "low_stock": len(low_stock),
    }

    # Chart 1: 14-day output per stage
    days = [today - timedelta(days=i) for i in range(13, -1, -1)]
    daily = {}
    for r in StageLog.objects.filter(date__gte=days[0]).values("date", "stage").annotate(t=Sum("quantity")):
        daily[(r["date"], r["stage"])] = float(r["t"])
    trend = {
        "labels": [d.strftime("%d %b") for d in days],
        "datasets": [
            {
                "label": dict(STAGE_CHOICES)[s] + f" ({STAGE_UNITS[s]})",
                "data": [daily.get((d, s), 0) for d in days],
                "color": STAGE_COLORS[s], "yAxisID": "yKg" if s == "spinning" else "yM",
            }
            for s in STAGE_ORDER
        ],
    }

    # Chart 2: downtime hours by reason (30 days)
    reason_minutes = {}
    for d in DowntimeRecord.objects.filter(started_at__date__gte=since30):
        reason_minutes[d.category] = reason_minutes.get(d.category, 0) + d.duration_minutes
    cat_labels = dict(DowntimeRecord.CATEGORY_CHOICES)
    ordered = sorted(reason_minutes.items(), key=lambda kv: -kv[1])
    downtime_chart = {
        "labels": [cat_labels[k] for k, _ in ordered],
        "data": [round(v / 60, 1) for _, v in ordered],
    }

    # Chart 3: defects by type (30 days)
    type_labels = dict(DefectRecord.TYPE_CHOICES)
    defect_rows = (
        DefectRecord.objects.filter(date__gte=since30).values("defect_type")
        .annotate(t=Sum("quantity")).order_by("-t")
    )
    defect_chart = {
        "labels": [type_labels[r["defect_type"]] for r in defect_rows],
        "data": [float(r["t"]) for r in defect_rows],
    }

    chart_data = {"trend": trend, "downtime": downtime_chart, "defects": defect_chart}
    ctx = {
        "section": "dashboard", "page_title": "Production dashboard", "today": today,
        "line": line, "kpis": kpis, "chart_data": chart_data,
        "open_downtime": DowntimeRecord.objects.filter(ended_at__isnull=True).select_related("machine")[:6],
        "low_stock_items": sorted(low_stock, key=lambda m: m.quantity / (m.reorder_level or 1))[:6],
        "orders": active_orders.order_by("due_date")[:6],
    }
    return render(request, "core/dashboard.html", ctx)


# --------------------------------------------------------------------------
# Generic building blocks
# --------------------------------------------------------------------------
class PageMixin(LoginRequiredMixin):
    section = ""
    page_title = ""

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["section"] = self.section
        ctx["page_title"] = self.page_title
        return ctx


class FilteredList(PageMixin, ListView):
    paginate_by = 12
    search_fields = ()
    filter_fields = ()  # query-string keys that map straight onto model fields

    def get_queryset(self):
        qs = super().get_queryset()
        q = self.request.GET.get("q", "").strip()
        if q and self.search_fields:
            cond = Q()
            for f in self.search_fields:
                cond |= Q(**{f"{f}__icontains": q})
            qs = qs.filter(cond)
        for f in self.filter_fields:
            value = self.request.GET.get(f)
            if value:
                qs = qs.filter(**{f: value})
        return qs

    def filter_defs(self):
        return []

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = self.request.GET.get("q", "")
        ctx["filters"] = [
            {**f, "current": self.request.GET.get(f["param"], "")} for f in self.filter_defs()
        ]
        ctx["has_filters"] = bool(ctx["q"] or any(f["current"] for f in ctx["filters"]))
        ctx["total"] = ctx["paginator"].count
        return ctx


def machine_choices():
    return [(m.pk, m.code) for m in Machine.objects.all()]


def order_choices():
    return [(o.pk, o.order_no) for o in ProductionOrder.objects.all()]


def crud_views(model, form_class, list_name, label, section, extra_create_ctx=None):
    """Create/Update/Delete class-based views that share one look and feel."""

    class Create(PageMixin, SuccessMessageMixin, CreateView):
        template_name = "core/form.html"
        success_url = reverse_lazy(list_name)
        success_message = f"{label} added."

        def get_context_data(self, **kwargs):
            ctx = super().get_context_data(**kwargs)
            ctx.update(form_title=f"New {label.lower()}", back_url=reverse(list_name), submit_label=f"Save {label.lower()}")
            return ctx

        def get_initial(self):
            initial = super().get_initial()
            initial.update({k: v for k, v in self.request.GET.items() if k in self.form_class.base_fields})
            return initial

    class Update(PageMixin, SuccessMessageMixin, UpdateView):
        template_name = "core/form.html"
        success_url = reverse_lazy(list_name)
        success_message = f"{label} updated."

        def get_context_data(self, **kwargs):
            ctx = super().get_context_data(**kwargs)
            ctx.update(form_title=f"Edit {label.lower()}", back_url=reverse(list_name), submit_label="Save changes")
            return ctx

    class Delete(PageMixin, DeleteView):
        template_name = "core/confirm_delete.html"
        success_url = reverse_lazy(list_name)

        def get_context_data(self, **kwargs):
            ctx = super().get_context_data(**kwargs)
            ctx.update(object_label=label.lower(), back_url=reverse(list_name))
            return ctx

        def form_valid(self, form):
            messages.success(self.request, f"{label} deleted.")
            return super().form_valid(form)

    for cls, title in ((Create, f"New {label.lower()}"), (Update, f"Edit {label.lower()}"), (Delete, f"Delete {label.lower()}")):
        cls.model = model
        if cls is not Delete:
            cls.form_class = form_class
        cls.section = section
        cls.page_title = title
        cls.__name__ = f"{model.__name__}{cls.__name__}"
    return Create.as_view(), Update.as_view(), Delete.as_view()


# --------------------------------------------------------------------------
# Inventory
# --------------------------------------------------------------------------
class MaterialList(FilteredList):
    model = Material
    template_name = "core/material_list.html"
    section = "inventory"
    page_title = "Inventory"
    search_fields = ("name", "sku", "location")
    filter_fields = ("category",)

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.GET.get("stock") == "low":
            qs = qs.filter(quantity__lte=F("reorder_level"))
        return qs

    def filter_defs(self):
        return [
            {"param": "category", "label": "All categories", "choices": Material.CATEGORY_CHOICES},
            {"param": "stock", "label": "Any stock level", "choices": [("low", "Low stock only")]},
        ]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        everything = Material.objects.all()
        ctx["summary"] = {
            "items": everything.count(),
            "low": sum(1 for m in everything if m.is_low),
            "value": sum((m.stock_value for m in everything), Decimal(0)),
        }
        return ctx


class MaterialDetail(PageMixin, DetailView):
    model = Material
    template_name = "core/material_detail.html"
    section = "inventory"
    page_title = "Item details"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["movements"] = self.object.movements.select_related("created_by")[:25]
        return ctx


class MovementCreate(PageMixin, CreateView):
    model = StockMovement
    form_class = forms.StockMovementForm
    template_name = "core/form.html"
    section = "inventory"
    page_title = "Record stock movement"

    def dispatch(self, request, *args, **kwargs):
        self.material = get_object_or_404(Material, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        return {"created_at": timezone.localtime(), "kind": self.request.GET.get("kind", "in")}

    def form_valid(self, form):
        form.instance.material = self.material
        form.instance.created_by = self.request.user
        response = super().form_valid(form)
        messages.success(self.request, f"Stock updated: {self.material.name} now {Material.objects.get(pk=self.material.pk).quantity:g} {self.material.unit}.")
        return response

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if kwargs.get("instance") is None:
            kwargs["instance"] = StockMovement(material=self.material)
        return kwargs

    def get_success_url(self):
        return self.material.get_absolute_url()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(
            form_title=f"Record movement · {self.material.name}",
            form_hint=f"Currently {self.material.quantity:g} {self.material.unit} in stock.",
            back_url=self.material.get_absolute_url(), submit_label="Record movement",
        )
        return ctx


MaterialCreate, MaterialUpdate, MaterialDelete = crud_views(
    Material, forms.MaterialForm, "material_list", "Item", "inventory"
)


# --------------------------------------------------------------------------
# Production orders
# --------------------------------------------------------------------------
class OrderList(FilteredList):
    model = ProductionOrder
    template_name = "core/order_list.html"
    section = "orders"
    page_title = "Production orders"
    search_fields = ("order_no", "product", "customer")
    filter_fields = ("status", "current_stage")

    def filter_defs(self):
        return [
            {"param": "status", "label": "All statuses", "choices": ProductionOrder.STATUS_CHOICES},
            {"param": "current_stage", "label": "All stages", "choices": STAGE_CHOICES},
        ]


class OrderDetail(PageMixin, DetailView):
    model = ProductionOrder
    template_name = "core/order_detail.html"
    section = "orders"
    page_title = "Order details"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        o = self.object
        ctx["stages"] = o.stage_totals()
        ctx["logs"] = o.logs.select_related("machine")[:15]
        ctx["defects"] = o.defects.all()[:8]
        ctx["defect_total"] = o.defects.aggregate(t=Sum("quantity"))["t"] or 0
        ctx["next_stage"] = o.next_stage()
        return ctx


@login_required
@require_POST
def order_advance(request, pk):
    order = get_object_or_404(ProductionOrder, pk=pk)
    nxt = order.next_stage()
    if nxt:
        order.current_stage = nxt
        order.status = "in_progress"
        order.save(update_fields=["current_stage", "status"])
        messages.success(request, f"{order.order_no} moved to {order.get_current_stage_display()}.")
    else:
        order.status = "completed"
        order.save(update_fields=["status"])
        messages.success(request, f"{order.order_no} marked completed.")
    return redirect(order)


OrderCreate, OrderUpdate, OrderDelete = crud_views(
    ProductionOrder, forms.ProductionOrderForm, "order_list", "Order", "orders"
)


# --------------------------------------------------------------------------
# Production log (spinning → weaving → finishing)
# --------------------------------------------------------------------------
class ProductionList(FilteredList):
    model = StageLog
    template_name = "core/production_list.html"
    section = "production"
    page_title = "Production log"
    search_fields = ("order__order_no", "order__product", "operator")
    filter_fields = ("stage", "shift", "machine", "order")

    def get_queryset(self):
        qs = super().get_queryset().select_related("order", "machine")
        if self.request.GET.get("date"):
            qs = qs.filter(date=self.request.GET["date"])
        return qs

    def filter_defs(self):
        return [
            {"param": "stage", "label": "All stages", "choices": STAGE_CHOICES},
            {"param": "shift", "label": "All shifts", "choices": [("A", "Shift A"), ("B", "Shift B"), ("C", "Shift C")]},
            {"param": "machine", "label": "All machines", "choices": machine_choices()},
        ]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["date_filter"] = self.request.GET.get("date", "")
        ctx["has_filters"] = ctx["has_filters"] or bool(ctx["date_filter"])
        return ctx


ProductionCreate, ProductionUpdate, ProductionDelete = crud_views(
    StageLog, forms.StageLogForm, "production_list", "Production entry", "production"
)


# --------------------------------------------------------------------------
# Daily targets
# --------------------------------------------------------------------------
class TargetList(FilteredList):
    model = DailyTarget
    template_name = "core/target_list.html"
    section = "targets"
    page_title = "Daily targets"
    filter_fields = ("stage",)

    def filter_defs(self):
        return [{"param": "stage", "label": "All stages", "choices": STAGE_CHOICES}]


TargetCreate, TargetUpdate, TargetDelete = crud_views(
    DailyTarget, forms.DailyTargetForm, "target_list", "Target", "targets"
)


# --------------------------------------------------------------------------
# Machines & downtime
# --------------------------------------------------------------------------
class MachineList(FilteredList):
    model = Machine
    template_name = "core/machine_list.html"
    section = "machines"
    page_title = "Machines"
    search_fields = ("code", "name", "make")
    filter_fields = ("stage",)
    paginate_by = 20

    def filter_defs(self):
        return [{"param": "stage", "label": "All stages", "choices": STAGE_CHOICES}]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        since = timezone.now() - timedelta(days=30)
        minutes = {}
        for d in DowntimeRecord.objects.filter(started_at__gte=since):
            minutes[d.machine_id] = minutes.get(d.machine_id, 0) + d.duration_minutes
        for m in ctx["object_list"]:
            m.down_hours_30 = round(minutes.get(m.pk, 0) / 60, 1)
        return ctx


MachineCreate, MachineUpdate, MachineDelete = crud_views(
    Machine, forms.MachineForm, "machine_list", "Machine", "machines"
)


class DowntimeList(FilteredList):
    model = DowntimeRecord
    template_name = "core/downtime_list.html"
    section = "downtime"
    page_title = "Machine downtime"
    search_fields = ("machine__code", "machine__name", "description", "reported_by")
    filter_fields = ("category", "machine")

    def get_queryset(self):
        qs = super().get_queryset().select_related("machine")
        if self.request.GET.get("state") == "open":
            qs = qs.filter(ended_at__isnull=True)
        elif self.request.GET.get("state") == "closed":
            qs = qs.filter(ended_at__isnull=False)
        return qs

    def filter_defs(self):
        return [
            {"param": "state", "label": "Open and closed", "choices": [("open", "Still down"), ("closed", "Resolved")]},
            {"param": "category", "label": "All reasons", "choices": DowntimeRecord.CATEGORY_CHOICES},
            {"param": "machine", "label": "All machines", "choices": machine_choices()},
        ]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        since = timezone.now() - timedelta(days=30)
        recent = DowntimeRecord.objects.filter(started_at__gte=since)
        ctx["summary"] = {
            "open": DowntimeRecord.objects.filter(ended_at__isnull=True).count(),
            "events": recent.count(),
            "hours": round(sum(d.duration_minutes for d in recent) / 60, 1),
        }
        return ctx


@login_required
@require_POST
def downtime_resolve(request, pk):
    record = get_object_or_404(DowntimeRecord, pk=pk)
    if record.is_open:
        record.ended_at = timezone.now()
        record.save(update_fields=["ended_at"])
        messages.success(request, f"{record.machine.code} is back in production after {record.duration_display}.")
    return redirect(request.POST.get("next") or "downtime_list")


DowntimeCreate, DowntimeUpdate, DowntimeDelete = crud_views(
    DowntimeRecord, forms.DowntimeForm, "downtime_list", "Downtime record", "downtime"
)


# --------------------------------------------------------------------------
# Defects
# --------------------------------------------------------------------------
class DefectList(FilteredList):
    model = DefectRecord
    template_name = "core/defect_list.html"
    section = "defects"
    page_title = "Defects and rejections"
    search_fields = ("order__order_no", "order__product", "remarks", "inspected_by")
    filter_fields = ("defect_type", "severity", "disposition", "stage")

    def get_queryset(self):
        return super().get_queryset().select_related("order", "machine")

    def filter_defs(self):
        return [
            {"param": "defect_type", "label": "All defect types", "choices": DefectRecord.TYPE_CHOICES},
            {"param": "severity", "label": "All severities", "choices": DefectRecord.SEVERITY_CHOICES},
            {"param": "disposition", "label": "All actions", "choices": DefectRecord.DISPOSITION_CHOICES},
        ]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        since = timezone.localdate() - timedelta(days=29)
        recent = DefectRecord.objects.filter(date__gte=since)
        by_disp = {r["disposition"]: r["t"] for r in recent.values("disposition").annotate(t=Sum("quantity"))}
        ctx["summary"] = {
            "total": recent.aggregate(t=Sum("quantity"))["t"] or 0,
            "scrap": by_disp.get("scrap") or 0,
            "rework": by_disp.get("rework") or 0,
            "downgrade": by_disp.get("downgrade") or 0,
        }
        return ctx


DefectCreate, DefectUpdate, DefectDelete = crud_views(
    DefectRecord, forms.DefectForm, "defect_list", "Defect record", "defects"
)


# --------------------------------------------------------------------------
# Reports
# --------------------------------------------------------------------------
REPORT_TYPES = [
    ("production", "Production summary"),
    ("targets", "Target vs actual"),
    ("downtime", "Machine downtime"),
    ("defects", "Defects and rejections"),
    ("stock", "Inventory valuation"),
]


def _d(value):
    return float(value or 0)


def build_report(kind, start, end):
    """Returns (headers, rows, summary[list of (label, value)])."""
    if kind == "production":
        logs = StageLog.objects.filter(date__range=(start, end))
        rows = []
        for r in logs.values("stage", "order__order_no", "order__product").annotate(q=Sum("quantity"), w=Sum("waste"), n=Count("id")).order_by("stage", "order__order_no"):
            waste_pct = _d(r["w"]) / (_d(r["q"]) + _d(r["w"])) * 100 if (r["q"] or r["w"]) else 0
            rows.append([
                dict(STAGE_CHOICES)[r["stage"]], r["order__order_no"], r["order__product"], r["n"],
                f"{_d(r['q']):,.1f} {STAGE_UNITS[r['stage']]}", f"{_d(r['w']):,.1f} {STAGE_UNITS[r['stage']]}", f"{waste_pct:.1f}%",
            ])
        headers = ["Stage", "Order", "Product", "Entries", "Output", "Waste", "Waste %"]
        totals = {r["stage"]: r["q"] for r in logs.values("stage").annotate(q=Sum("quantity"))}
        summary = [(f"{dict(STAGE_CHOICES)[s]} output", f"{_d(totals.get(s)):,.0f} {STAGE_UNITS[s]}") for s in STAGE_ORDER]
    elif kind == "targets":
        rows, hit, total = [], 0, 0
        for t in DailyTarget.objects.filter(date__range=(start, end)).order_by("date", "stage"):
            actual = t.actual
            total += 1
            hit += 1 if actual >= t.target_qty else 0
            rows.append([
                t.date.strftime("%d %b %Y"), t.get_stage_display(),
                f"{_d(t.target_qty):,.0f} {t.unit}", f"{_d(actual):,.0f} {t.unit}",
                f"{_d(actual) - _d(t.target_qty):+,.0f} {t.unit}", f"{t.pct}%",
            ])
        headers = ["Date", "Stage", "Target", "Actual", "Variance", "Attainment"]
        summary = [("Days × stages tracked", total), ("Targets met", hit), ("Hit rate", f"{hit / total * 100:.0f}%" if total else "–")]
    elif kind == "downtime":
        qs = DowntimeRecord.objects.filter(started_at__date__range=(start, end)).select_related("machine")
        rows, mins = [], 0
        for d in qs.order_by("-started_at"):
            mins += d.duration_minutes
            rows.append([
                d.machine.code, d.machine.name, timezone.localtime(d.started_at).strftime("%d %b %Y %H:%M"),
                timezone.localtime(d.ended_at).strftime("%d %b %Y %H:%M") if d.ended_at else "Still down",
                d.duration_display, d.get_category_display(), d.description,
            ])
        headers = ["Machine", "Name", "Started", "Ended", "Duration", "Reason", "Details"]
        summary = [("Events", len(rows)), ("Total downtime", f"{mins / 60:,.1f} h"), ("Average per event", f"{mins / len(rows):,.0f} min" if rows else "–")]
    elif kind == "defects":
        qs = DefectRecord.objects.filter(date__range=(start, end)).select_related("order", "machine")
        rows, total, scrap = [], Decimal(0), Decimal(0)
        for d in qs.order_by("-date"):
            total += d.quantity
            scrap += d.quantity if d.disposition == "scrap" else 0
            rows.append([
                d.date.strftime("%d %b %Y"), d.order.order_no, d.get_stage_display(),
                d.get_defect_type_display(), d.get_severity_display(), d.get_disposition_display(),
                f"{_d(d.quantity):,.1f} m", d.machine.code if d.machine else "–",
            ])
        weaving = StageLog.objects.filter(stage="weaving", date__range=(start, end)).aggregate(t=Sum("quantity"))["t"]
        headers = ["Date", "Order", "Stage", "Defect", "Severity", "Action", "Fabric", "Machine"]
        summary = [
            ("Defective fabric", f"{_d(total):,.0f} m"), ("Rejected / scrapped", f"{_d(scrap):,.0f} m"),
            ("Rejection rate", f"{_d(scrap) / _d(weaving) * 100:.2f}%" if weaving else "–"),
        ]
    else:  # stock
        items = Material.objects.all()
        rows = [[
            m.sku, m.name, m.get_category_display(), f"{_d(m.quantity):,.1f} {m.unit}",
            f"{_d(m.reorder_level):,.1f} {m.unit}", f"₹{_d(m.cost_per_unit):,.2f}", f"₹{_d(m.stock_value):,.0f}",
            "Reorder" if m.is_low else "OK",
        ] for m in items]
        headers = ["Code", "Item", "Category", "In stock", "Reorder level", "Rate", "Value", "Status"]
        summary = [
            ("Items", items.count()), ("Below reorder level", sum(1 for m in items if m.is_low)),
            ("Stock value", f"₹{_d(sum((m.stock_value for m in items), Decimal(0))):,.0f}"),
        ]
    return headers, rows, summary


@login_required
def reports(request):
    today = timezone.localdate()
    kind = request.GET.get("type", "production")
    if kind not in dict(REPORT_TYPES):
        kind = "production"

    def parse(key, default):
        try:
            return timezone.datetime.strptime(request.GET[key], "%Y-%m-%d").date()
        except (KeyError, ValueError):
            return default

    start = parse("start", today - timedelta(days=29))
    end = parse("end", today)
    if end < start:
        start, end = end, start

    headers, rows, summary = build_report(kind, start, end)

    if request.GET.get("export") == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{kind}_{start}_{end}.csv"'
        response.write("\ufeff")
        writer = csv.writer(response)
        writer.writerow(headers)
        writer.writerows(rows)
        return response

    ctx = {
        "section": "reports", "page_title": "Reports", "kind": kind,
        "kind_label": dict(REPORT_TYPES)[kind], "report_types": REPORT_TYPES,
        "start": start, "end": end, "headers": headers, "rows": rows, "summary": summary,
        "presets": [("Last 7 days", today - timedelta(days=6)), ("Last 30 days", today - timedelta(days=29)), ("This month", today.replace(day=1))],
        "today": today,
    }
    return render(request, "core/reports.html", ctx)
