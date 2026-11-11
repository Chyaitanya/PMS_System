from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone

STAGE_CHOICES = [
    ("spinning", "Spinning"),
    ("weaving", "Weaving"),
    ("finishing", "Finishing"),
]
FABRIC_STAGE_CHOICES = [("weaving", "Weaving"), ("finishing", "Finishing")]
STAGE_ORDER = ["spinning", "weaving", "finishing"]
# Spinning output is yarn (kg); weaving and finishing output is fabric (metres).
STAGE_UNITS = {"spinning": "kg", "weaving": "m", "finishing": "m"}
SHIFT_CHOICES = [("A", "Shift A (06:00–14:00)"), ("B", "Shift B (14:00–22:00)"), ("C", "Shift C (22:00–06:00)")]


class Material(models.Model):
    CATEGORY_CHOICES = [("yarn", "Yarn"), ("fabric", "Fabric"), ("raw", "Raw material")]
    UNIT_CHOICES = [("kg", "kg"), ("m", "m"), ("pcs", "pcs"), ("l", "litre")]

    sku = models.CharField("Item code", max_length=30, unique=True)
    name = models.CharField(max_length=120)
    category = models.CharField(max_length=10, choices=CATEGORY_CHOICES)
    unit = models.CharField(max_length=5, choices=UNIT_CHOICES, default="kg")
    quantity = models.DecimalField("In stock", max_digits=12, decimal_places=2, default=0)
    reorder_level = models.DecimalField("Reorder level", max_digits=12, decimal_places=2, default=0)
    cost_per_unit = models.DecimalField("Cost per unit (₹)", max_digits=10, decimal_places=2, default=0)
    location = models.CharField("Storage location", max_length=60, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category", "name"]

    def __str__(self):
        return f"{self.sku} · {self.name}"

    @property
    def is_low(self):
        return self.quantity <= self.reorder_level

    @property
    def stock_value(self):
        return self.quantity * self.cost_per_unit

    @property
    def stock_pct(self):
        """Fill level against twice the reorder level, for the stock bar."""
        cap = (self.reorder_level or Decimal(1)) * 2
        return int(max(0, min(100, self.quantity / cap * 100)))

    def get_absolute_url(self):
        return reverse("material_detail", args=[self.pk])


class StockMovement(models.Model):
    KIND_CHOICES = [("in", "Stock in"), ("out", "Stock out")]

    material = models.ForeignKey(Material, on_delete=models.CASCADE, related_name="movements")
    kind = models.CharField(max_length=3, choices=KIND_CHOICES)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    reference = models.CharField("Reference", max_length=60, blank=True, help_text="Challan, GRN or order number")
    note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["-created_at", "-id"]

    def clean(self):
        if self.quantity is not None and self.quantity <= 0:
            raise ValidationError({"quantity": "Quantity must be greater than zero."})
        if self.kind == "out" and self.material_id and self.quantity and not self.pk:
            if self.quantity > self.material.quantity:
                raise ValidationError(
                    {"quantity": f"Only {self.material.quantity:g} {self.material.unit} in stock."}
                )

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        with transaction.atomic():
            super().save(*args, **kwargs)
            if is_new:
                delta = self.quantity if self.kind == "in" else -self.quantity
                material = Material.objects.select_for_update().get(pk=self.material_id)
                material.quantity += delta
                material.save(update_fields=["quantity", "updated_at"])


class Machine(models.Model):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    stage = models.CharField(max_length=10, choices=STAGE_CHOICES)
    make = models.CharField("Make / model", max_length=100, blank=True)
    is_active = models.BooleanField("In service", default=True)

    class Meta:
        ordering = ["stage", "code"]

    def __str__(self):
        return f"{self.code} · {self.name}"

    @property
    def open_downtime(self):
        return self.downtimes.filter(ended_at__isnull=True).first()

    @property
    def status(self):
        if not self.is_active:
            return "Out of service"
        return "Down" if self.open_downtime else "Running"


class ProductionOrder(models.Model):
    STATUS_CHOICES = [
        ("planned", "Planned"),
        ("in_progress", "In progress"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    ]

    order_no = models.CharField("Order no.", max_length=30, unique=True)
    product = models.CharField("Fabric / product", max_length=120)
    customer = models.CharField(max_length=120, blank=True)
    yarn = models.ForeignKey(
        Material, null=True, blank=True, on_delete=models.SET_NULL,
        limit_choices_to={"category": "yarn"}, related_name="orders", verbose_name="Yarn used",
    )
    yarn_required_kg = models.DecimalField("Yarn required (kg)", max_digits=12, decimal_places=2, default=0)
    planned_qty = models.DecimalField("Fabric to produce (m)", max_digits=12, decimal_places=2)
    start_date = models.DateField()
    due_date = models.DateField()
    current_stage = models.CharField(max_length=10, choices=STAGE_CHOICES, default="spinning")
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default="planned")
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-start_date", "-id"]

    def __str__(self):
        return f"{self.order_no} · {self.product}"

    def get_absolute_url(self):
        return reverse("order_detail", args=[self.pk])

    def clean(self):
        if self.start_date and self.due_date and self.due_date < self.start_date:
            raise ValidationError({"due_date": "Due date cannot be before the start date."})

    def stage_planned(self, stage):
        return self.yarn_required_kg if stage == "spinning" else self.planned_qty

    def stage_totals(self):
        sums = {
            row["stage"]: row["total"]
            for row in self.logs.values("stage").annotate(total=Sum("quantity"))
        }
        data = []
        for stage in STAGE_ORDER:
            produced = sums.get(stage) or Decimal(0)
            planned = self.stage_planned(stage)
            pct = int(min(100, produced / planned * 100)) if planned else 0
            data.append({
                "stage": stage, "label": dict(STAGE_CHOICES)[stage], "unit": STAGE_UNITS[stage],
                "produced": produced, "planned": planned, "pct": pct,
            })
        return data

    @property
    def overall_pct(self):
        if self.status == "completed":
            return 100
        totals = self.stage_totals()
        return int(sum(t["pct"] for t in totals) / len(totals))

    @property
    def is_overdue(self):
        return self.status in ("planned", "in_progress") and self.due_date < timezone.localdate()

    def next_stage(self):
        idx = STAGE_ORDER.index(self.current_stage)
        return STAGE_ORDER[idx + 1] if idx + 1 < len(STAGE_ORDER) else None


class StageLog(models.Model):
    order = models.ForeignKey(ProductionOrder, on_delete=models.CASCADE, related_name="logs")
    stage = models.CharField(max_length=10, choices=STAGE_CHOICES)
    machine = models.ForeignKey(Machine, null=True, blank=True, on_delete=models.SET_NULL, related_name="logs")
    date = models.DateField(default=timezone.localdate)
    shift = models.CharField(max_length=1, choices=SHIFT_CHOICES)
    quantity = models.DecimalField("Output", max_digits=12, decimal_places=2)
    waste = models.DecimalField("Waste", max_digits=10, decimal_places=2, default=0)
    operator = models.CharField(max_length=80, blank=True)
    remarks = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.order.order_no} {self.stage} {self.date}"

    @property
    def unit(self):
        return STAGE_UNITS[self.stage]

    def clean(self):
        if self.machine_id and self.stage and self.machine.stage != self.stage:
            raise ValidationError({"machine": f"{self.machine.code} belongs to {self.machine.get_stage_display()}, not {self.get_stage_display()}."})
        if self.quantity is not None and self.quantity <= 0:
            raise ValidationError({"quantity": "Output must be greater than zero."})


class DailyTarget(models.Model):
    date = models.DateField(default=timezone.localdate)
    stage = models.CharField(max_length=10, choices=STAGE_CHOICES)
    target_qty = models.DecimalField("Target", max_digits=12, decimal_places=2)
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-date", "stage"]
        constraints = [models.UniqueConstraint(fields=["date", "stage"], name="one_target_per_stage_per_day")]

    def __str__(self):
        return f"{self.date} {self.stage}"

    @property
    def unit(self):
        return STAGE_UNITS[self.stage]

    @property
    def actual(self):
        total = StageLog.objects.filter(date=self.date, stage=self.stage).aggregate(t=Sum("quantity"))["t"]
        return total or Decimal(0)

    @property
    def pct(self):
        return int(self.actual / self.target_qty * 100) if self.target_qty else 0


class DowntimeRecord(models.Model):
    CATEGORY_CHOICES = [
        ("mechanical", "Mechanical failure"),
        ("electrical", "Electrical fault"),
        ("power", "Power cut"),
        ("maintenance", "Planned maintenance"),
        ("material", "Waiting for material"),
        ("changeover", "Style changeover"),
        ("other", "Other"),
    ]

    machine = models.ForeignKey(Machine, on_delete=models.CASCADE, related_name="downtimes")
    started_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True, help_text="Leave empty while the machine is still down")
    category = models.CharField("Reason", max_length=12, choices=CATEGORY_CHOICES)
    description = models.CharField(max_length=250, blank=True)
    reported_by = models.CharField(max_length=80, blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.machine.code} {self.started_at:%d %b %H:%M}"

    @property
    def is_open(self):
        return self.ended_at is None

    @property
    def duration_minutes(self):
        end = self.ended_at or timezone.now()
        return max(0, int((end - self.started_at).total_seconds() // 60))

    @property
    def duration_display(self):
        m = self.duration_minutes
        h, mins = divmod(m, 60)
        return f"{h}h {mins:02d}m" if h else f"{mins}m"

    def clean(self):
        if self.ended_at and self.started_at and self.ended_at < self.started_at:
            raise ValidationError({"ended_at": "End time cannot be before the start time."})


class DefectRecord(models.Model):
    TYPE_CHOICES = [
        ("slub", "Slubs / thick places"),
        ("hole", "Holes / cuts"),
        ("broken_end", "Broken ends"),
        ("weft_bar", "Weft bar"),
        ("oil_stain", "Oil stains"),
        ("uneven_dye", "Uneven dyeing"),
        ("shade", "Shade variation"),
        ("selvedge", "Selvedge defect"),
        ("other", "Other"),
    ]
    SEVERITY_CHOICES = [("minor", "Minor"), ("major", "Major"), ("critical", "Critical")]
    DISPOSITION_CHOICES = [("rework", "Rework"), ("downgrade", "Downgrade (B-grade)"), ("scrap", "Reject / scrap")]

    order = models.ForeignKey(ProductionOrder, on_delete=models.CASCADE, related_name="defects")
    stage = models.CharField(max_length=10, choices=FABRIC_STAGE_CHOICES, default="weaving")
    machine = models.ForeignKey(Machine, null=True, blank=True, on_delete=models.SET_NULL, related_name="defects")
    date = models.DateField(default=timezone.localdate)
    defect_type = models.CharField(max_length=12, choices=TYPE_CHOICES)
    severity = models.CharField(max_length=8, choices=SEVERITY_CHOICES, default="minor")
    disposition = models.CharField("Action taken", max_length=10, choices=DISPOSITION_CHOICES, default="rework")
    quantity = models.DecimalField("Affected fabric (m)", max_digits=10, decimal_places=2)
    inspected_by = models.CharField(max_length=80, blank=True)
    remarks = models.CharField(max_length=250, blank=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.order.order_no} {self.get_defect_type_display()}"

    def clean(self):
        if self.quantity is not None and self.quantity <= 0:
            raise ValidationError({"quantity": "Quantity must be greater than zero."})
