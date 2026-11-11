from django import forms

from . import models

DATE = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
DATETIME = forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")
DT_FORMATS = ["%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"]


class StyledForm(forms.ModelForm):
    """Adds Bootstrap classes to every widget."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            # Friendlier placeholder than Django's "---------"
            if isinstance(field, forms.ModelChoiceField):
                if field.empty_label is not None:
                    field.empty_label = f"Select {str(field.label).lower()}"
            elif isinstance(field, forms.ChoiceField) and field.choices and field.choices[0][0] == "":
                field.choices = [("", f"Select {str(field.label).lower()}")] + list(field.choices)[1:]
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = "form-check-input"
            elif isinstance(widget, forms.Select):
                widget.attrs["class"] = "form-select"
            else:
                widget.attrs["class"] = "form-control"
            if isinstance(widget, forms.Textarea):
                widget.attrs.setdefault("rows", 3)

    def full_clean(self):
        super().full_clean()
        for name in self.errors:
            if name in self.fields:
                widget = self.fields[name].widget
                widget.attrs["class"] = widget.attrs.get("class", "") + " is-invalid"


class MaterialForm(StyledForm):
    class Meta:
        model = models.Material
        fields = ["sku", "name", "category", "unit", "quantity", "reorder_level", "cost_per_unit", "location"]


class StockMovementForm(StyledForm):
    created_at = forms.DateTimeField(label="Date and time", widget=DATETIME, input_formats=DT_FORMATS)

    class Meta:
        model = models.StockMovement
        fields = ["kind", "quantity", "reference", "note", "created_at"]


class MachineForm(StyledForm):
    class Meta:
        model = models.Machine
        fields = ["code", "name", "stage", "make", "is_active"]


class ProductionOrderForm(StyledForm):
    class Meta:
        model = models.ProductionOrder
        fields = [
            "order_no", "product", "customer", "yarn", "yarn_required_kg", "planned_qty",
            "start_date", "due_date", "current_stage", "status", "notes",
        ]
        widgets = {"start_date": DATE, "due_date": DATE}


class StageLogForm(StyledForm):
    class Meta:
        model = models.StageLog
        fields = ["order", "stage", "machine", "date", "shift", "quantity", "waste", "operator", "remarks"]
        widgets = {"date": DATE}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["order"].queryset = models.ProductionOrder.objects.filter(
            status__in=["planned", "in_progress"]
        ) | models.ProductionOrder.objects.filter(pk=self.instance.order_id or 0)
        self.fields["machine"].queryset = models.Machine.objects.filter(is_active=True)
        self.fields["machine"].required = False
        self.fields["quantity"].label = "Output (kg for spinning, m for weaving/finishing)"


class DailyTargetForm(StyledForm):
    class Meta:
        model = models.DailyTarget
        fields = ["date", "stage", "target_qty", "note"]
        widgets = {"date": DATE}
        labels = {"target_qty": "Target (kg for spinning, m for weaving/finishing)"}


class DowntimeForm(StyledForm):
    started_at = forms.DateTimeField(widget=DATETIME, input_formats=DT_FORMATS)
    ended_at = forms.DateTimeField(
        widget=DATETIME, input_formats=DT_FORMATS, required=False,
        help_text="Leave empty while the machine is still down",
    )

    class Meta:
        model = models.DowntimeRecord
        fields = ["machine", "started_at", "ended_at", "category", "description", "reported_by"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["machine"].queryset = models.Machine.objects.filter(is_active=True)


class DefectForm(StyledForm):
    class Meta:
        model = models.DefectRecord
        fields = [
            "order", "stage", "machine", "date", "defect_type", "severity",
            "disposition", "quantity", "inspected_by", "remarks",
        ]
        widgets = {"date": DATE}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["machine"].required = False
        self.fields["machine"].queryset = models.Machine.objects.filter(is_active=True)
