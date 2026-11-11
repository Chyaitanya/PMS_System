from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    DailyTarget, DefectRecord, DowntimeRecord, Machine, Material, ProductionOrder, StageLog, StockMovement,
)


class SmokeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("tester", password="pw12345!")
        today = timezone.localdate()
        cls.yarn = Material.objects.create(sku="Y1", name="Cotton 30s", category="yarn", unit="kg", quantity=100, reorder_level=50, cost_per_unit=200)
        cls.loom = Machine.objects.create(code="LM-1", name="Loom 1", stage="weaving")
        cls.order = ProductionOrder.objects.create(
            order_no="O-1", product="Poplin", yarn=cls.yarn, yarn_required_kg=100, planned_qty=1000,
            start_date=today, due_date=today + timedelta(days=5), status="in_progress", current_stage="weaving",
        )
        DailyTarget.objects.create(date=today, stage="weaving", target_qty=500)
        StageLog.objects.create(order=cls.order, stage="weaving", machine=cls.loom, date=today, shift="A", quantity=250, waste=3)
        cls.down = DowntimeRecord.objects.create(machine=cls.loom, category="mechanical")
        DefectRecord.objects.create(order=cls.order, stage="weaving", date=today, defect_type="hole", disposition="scrap", quantity=12)

    def setUp(self):
        self.client.force_login(self.user)

    def test_login_required(self):
        self.client.logout()
        resp = self.client.get(reverse("dashboard"))
        self.assertRedirects(resp, "/login/?next=/")

    def test_all_pages_render(self):
        names = ["dashboard", "material_list", "order_list", "production_list", "target_list",
                 "machine_list", "downtime_list", "defect_list", "reports",
                 "material_create", "order_create", "production_create", "target_create",
                 "machine_create", "downtime_create", "defect_create"]
        for name in names:
            with self.subTest(name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)
        for name, pk in [("material_detail", self.yarn.pk), ("material_update", self.yarn.pk), ("movement_create", self.yarn.pk),
                         ("order_detail", self.order.pk), ("order_update", self.order.pk),
                         ("machine_update", self.loom.pk), ("downtime_update", self.down.pk),
                         ("material_delete", self.yarn.pk), ("order_delete", self.order.pk)]:
            with self.subTest(name):
                self.assertEqual(self.client.get(reverse(name, args=[pk])).status_code, 200)

    def test_reports_and_csv(self):
        for kind in ("production", "targets", "downtime", "defects", "stock"):
            with self.subTest(kind):
                self.assertEqual(self.client.get(reverse("reports"), {"type": kind}).status_code, 200)
                resp = self.client.get(reverse("reports"), {"type": kind, "export": "csv"})
                self.assertEqual(resp["Content-Type"], "text/csv; charset=utf-8")

    def test_stock_movements_update_balance(self):
        url = reverse("movement_create", args=[self.yarn.pk])
        now = timezone.localtime().strftime("%Y-%m-%dT%H:%M")
        self.client.post(url, {"kind": "in", "quantity": "40", "created_at": now})
        self.yarn.refresh_from_db()
        self.assertEqual(self.yarn.quantity, Decimal("140"))
        self.client.post(url, {"kind": "out", "quantity": "90", "created_at": now})
        self.yarn.refresh_from_db()
        self.assertEqual(self.yarn.quantity, Decimal("50"))
        resp = self.client.post(url, {"kind": "out", "quantity": "500", "created_at": now})
        self.assertContains(resp, "in stock")  # validation error, balance unchanged
        self.yarn.refresh_from_db()
        self.assertEqual(self.yarn.quantity, Decimal("50"))
        self.assertEqual(StockMovement.objects.filter(material=self.yarn).count(), 2)

    def test_downtime_resolve_and_order_advance(self):
        self.client.post(reverse("downtime_resolve", args=[self.down.pk]))
        self.down.refresh_from_db()
        self.assertFalse(self.down.is_open)
        self.client.post(reverse("order_advance", args=[self.order.pk]))
        self.order.refresh_from_db()
        self.assertEqual(self.order.current_stage, "finishing")
        self.client.post(reverse("order_advance", args=[self.order.pk]))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "completed")

    def test_create_production_entry_and_target_attainment(self):
        resp = self.client.post(reverse("production_create"), {
            "order": self.order.pk, "stage": "weaving", "machine": self.loom.pk,
            "date": timezone.localdate().isoformat(), "shift": "B", "quantity": "250", "waste": "2",
        })
        self.assertEqual(resp.status_code, 302)
        target = DailyTarget.objects.get()
        self.assertEqual(target.actual, Decimal("500"))
        self.assertEqual(target.pct, 100)

    def test_machine_stage_mismatch_rejected(self):
        resp = self.client.post(reverse("production_create"), {
            "order": self.order.pk, "stage": "spinning", "machine": self.loom.pk,
            "date": timezone.localdate().isoformat(), "shift": "A", "quantity": "10", "waste": "0",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "belongs to Weaving")

    def test_duplicate_target_rejected(self):
        resp = self.client.post(reverse("target_create"), {"date": timezone.localdate().isoformat(), "stage": "weaving", "target_qty": "100"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(DailyTarget.objects.count(), 1)

    def test_delete_flow(self):
        resp = self.client.post(reverse("defect_delete", args=[DefectRecord.objects.get().pk]))
        self.assertRedirects(resp, reverse("defect_list"))
        self.assertEqual(DefectRecord.objects.count(), 0)


    def test_pagination_on_first_middle_and_last_page(self):
        for i in range(40):
            Material.objects.create(sku=f"M{i:03d}", name=f"Item {i}", category="raw", unit="kg", quantity=10, reorder_level=1)
        for page in (1, 2, 4):
            with self.subTest(page=page):
                resp = self.client.get(reverse("material_list"), {"page": page})
                self.assertEqual(resp.status_code, 200)
                self.assertContains(resp, "pager")
