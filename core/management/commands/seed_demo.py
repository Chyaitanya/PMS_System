"""Fill the database with realistic demo data:  python manage.py seed_demo [--reset]"""
import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import (
    DailyTarget, DefectRecord, DowntimeRecord, Machine, Material, ProductionOrder,
    StageLog, StockMovement,
)

OPERATORS = ["R. Patil", "S. Deshmukh", "A. Shaikh", "M. Kulkarni", "V. Jadhav", "P. More", "K. Gaikwad", "N. Pawar"]
INSPECTORS = ["D. Joshi", "S. Bhosale", "T. Kamble"]

MATERIALS = [
    # sku, name, category, unit, qty, reorder, cost, location
    ("CY-30C", "Cotton combed yarn 30s", "yarn", "kg", 4200, 1500, 245, "Yarn store A1"),
    ("CY-20K", "Cotton carded yarn 20s", "yarn", "kg", 2800, 1200, 220, "Yarn store A2"),
    ("PY-150", "Polyester yarn 150D", "yarn", "kg", 1100, 1500, 118, "Yarn store B1"),
    ("VY-40S", "Viscose yarn 40s", "yarn", "kg", 3400, 1000, 280, "Yarn store B2"),
    ("PC-40S", "Polyester/cotton blend yarn 40s", "yarn", "kg", 2600, 1000, 210, "Yarn store A3"),
    ("RM-COT", "Raw cotton bales", "raw", "kg", 18000, 6000, 112, "Godown 1"),
    ("RM-PSF", "Polyester staple fibre", "raw", "kg", 900, 2000, 96, "Godown 1"),
    ("RM-STR", "Sizing starch", "raw", "kg", 650, 300, 54, "Chemical store"),
    ("RM-DYE", "Reactive indigo dye", "raw", "kg", 85, 60, 1450, "Chemical store"),
    ("RM-NAOH", "Caustic soda flakes", "raw", "kg", 420, 250, 42, "Chemical store"),
    ("RM-SOF", "Fabric softener", "raw", "l", 180, 100, 165, "Chemical store"),
    ("RM-OIL", "Loom lubricating oil", "raw", "l", 40, 50, 310, "Maintenance store"),
    ("GF-POP", "Greige poplin", "fabric", "m", 24000, 8000, 78, "Fabric godown"),
    ("FF-TWL", "Finished cotton twill", "fabric", "m", 9600, 5000, 132, "Dispatch bay"),
]

MACHINES = [
    ("RF-01", "Ring frame 1", "spinning", "Lakshmi LR 6/S"), ("RF-02", "Ring frame 2", "spinning", "Lakshmi LR 6/S"),
    ("RF-03", "Ring frame 3", "spinning", "Rieter G 38"), ("RF-04", "Ring frame 4", "spinning", "Rieter G 38"),
    ("LM-01", "Air-jet loom 1", "weaving", "Picanol OMNIplus 800"), ("LM-02", "Air-jet loom 2", "weaving", "Picanol OMNIplus 800"),
    ("LM-03", "Air-jet loom 3", "weaving", "Tsudakoma ZAX 9100"), ("LM-04", "Air-jet loom 4", "weaving", "Tsudakoma ZAX 9100"),
    ("LM-05", "Rapier loom 5", "weaving", "Itema R9500"), ("LM-06", "Rapier loom 6", "weaving", "Itema R9500"),
    ("ST-01", "Stenter", "finishing", "Monforts Montex"), ("CL-01", "Calender", "finishing", "Calico Textile Machinery"),
    ("SF-01", "Sanforizing range", "finishing", "Tubular Textile Machinery"),
]

TARGETS = {"spinning": 900, "weaving": 3600, "finishing": 2400}
WASTE_PCT = {"spinning": (0.015, 0.03), "weaving": (0.008, 0.015), "finishing": (0.005, 0.01)}

DOWNTIME_NOTES = {
    "mechanical": ["Warp beam alignment fault", "Picking motion belt worn", "Spindle bearing noise", "Stenter chain jam"],
    "electrical": ["Drive panel tripped", "Sensor fault on weft feeler", "Contactor replaced"],
    "power": ["Grid supply interruption", "DG changeover delay"],
    "maintenance": ["Scheduled lubrication and cleaning", "Monthly preventive maintenance"],
    "material": ["Waiting for warp beams from sizing", "Yarn lot not issued"],
    "changeover": ["Style change to twill", "Reed and heald change"],
    "other": ["Operator shortage"],
}


class Command(BaseCommand):
    help = "Create demo data (admin / admin123) for the textile production system."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete existing production data first")

    def handle(self, *args, **opts):
        random.seed(42)
        if opts["reset"]:
            for model in (DefectRecord, DowntimeRecord, StageLog, DailyTarget, ProductionOrder, StockMovement, Material, Machine):
                model.objects.all().delete()
        elif Machine.objects.exists():
            self.stdout.write(self.style.WARNING("Data already exists. Run with --reset to rebuild the demo data."))
            return

        User = get_user_model()
        admin, created = User.objects.get_or_create(username="admin", defaults={"is_staff": True, "is_superuser": True, "first_name": "Plant", "last_name": "Manager"})
        if created:
            admin.set_password("admin123")
            admin.save()

        now = timezone.now()
        today = timezone.localdate()

        # Machines
        machines = {s: [] for s in TARGETS}
        for code, name, stage, make in MACHINES:
            machines[stage].append(Machine.objects.create(code=code, name=name, stage=stage, make=make))

        # Materials with stock movements that end at the intended balance
        for sku, name, cat, unit, qty, reorder, cost, loc in MATERIALS:
            m = Material.objects.create(sku=sku, name=name, category=cat, unit=unit, quantity=0, reorder_level=reorder, cost_per_unit=cost, location=loc)
            final = Decimal(qty)
            outs = [(final * Decimal(str(random.uniform(0.04, 0.1)))).quantize(Decimal("1")) for _ in range(3)]
            mid_in = (final * Decimal("0.12")).quantize(Decimal("1"))
            first_in = final + sum(outs) - mid_in
            plan = [("in", first_in, 28, "GRN"), ("out", outs[0], 20, "ISS"), ("in", mid_in, 12, "GRN"), ("out", outs[1], 8, "ISS"), ("out", outs[2], 3, "ISS")]
            for kind, q, days_ago, prefix in plan:
                StockMovement.objects.create(
                    material=m, kind=kind, quantity=q, reference=f"{prefix}-{random.randint(1000, 9999)}",
                    note="Received from supplier" if kind == "in" else "Issued to production",
                    created_at=now - timedelta(days=days_ago, hours=random.randint(0, 6)), created_by=admin,
                )

        # Orders
        yarn = {m.sku: m for m in Material.objects.filter(category="yarn")}
        # (order_no, product, customer, yarn sku, yarn kg, fabric m, start, due, current stage, status, share of the
        #  current stage already done)
        orders_spec = [
            ("ORD-2609", "Cotton shirting 40s × 40s", "Kalyani Apparels", "CY-30C", 2800, 14000, -21, -4, "finishing", "completed", 1.0),
            ("ORD-2613", "PC blend shirting 40s", "Nanded Uniforms Co.", "PC-40S", 3600, 18000, -20, -1, "finishing", "in_progress", 0.9),
            ("ORD-2611", "Cotton poplin 40s × 40s", "Shree Ganesh Garments", "CY-30C", 5000, 25000, -18, 9, "finishing", "in_progress", 0.8),
            ("ORD-2612", "Cotton twill 20s × 20s", "Kalyani Apparels", "CY-20K", 5400, 27000, -15, 6, "weaving", "in_progress", 0.6),
            ("ORD-2614", "Viscose crepe", "Sai Home Textiles", "VY-40S", 3200, 16000, -8, 14, "spinning", "in_progress", 0.35),
            ("ORD-2615", "Cotton drill, uniform grade", "Marathwada Hosiery", "CY-20K", 6000, 30000, 3, 25, "spinning", "planned", 0),
            ("ORD-2616", "Cotton poplin 60s × 60s", "Shree Ganesh Garments", "CY-30C", 4400, 22000, 6, 30, "spinning", "planned", 0),
        ]
        stage_idx = {"spinning": 0, "weaving": 1, "finishing": 2}
        orders, need, planned_for = [], {}, {}
        for no, product, cust, y, ykg, qty, start, due, stage, status, done in orders_spec:
            o = ProductionOrder.objects.create(
                order_no=no, product=product, customer=cust, yarn=yarn[y], yarn_required_kg=ykg, planned_qty=qty,
                start_date=today + timedelta(days=start), due_date=today + timedelta(days=due), current_stage=stage, status=status,
            )
            orders.append(o)
            for st, idx in stage_idx.items():
                total = Decimal(ykg if st == "spinning" else qty)
                planned_for[(o.pk, st)] = total
                if status == "planned" or idx > stage_idx[stage]:
                    need[(o.pk, st)] = Decimal(0)
                elif idx < stage_idx[stage] or status == "completed":
                    need[(o.pk, st)] = total
                else:
                    need[(o.pk, st)] = total * Decimal(str(done))
        done_so_far = {k: Decimal(0) for k in need}
        runnable = [o for o in orders if o.status != "planned"]
        prev_stage = {"weaving": "spinning", "finishing": "weaving"}

        # Daily targets and production logs for the last 21 days. Each day's output is handed to the oldest order
        # that still needs it, and a stage only starts once the stage before it is 15% done.
        for back in range(20, -1, -1):
            day = today - timedelta(days=back)
            for stage, target in TARGETS.items():
                shifts = ["A", "B", "C"]
                if back == 0:  # today is still in progress
                    shifts = ["A", "B"] if stage != "finishing" else ["A"]
                share = 0.62 if back == 0 else random.uniform(0.86, 1.06)
                day_total = Decimal(target * share)
                produced_any = False
                for shift in shifts:
                    shift_qty = day_total / len(shifts) * Decimal(str(random.uniform(0.92, 1.08)))
                    while shift_qty > Decimal("0.5"):
                        pick = None
                        for o in runnable:
                            if o.start_date > day or need[(o.pk, stage)] - done_so_far[(o.pk, stage)] <= 0:
                                continue
                            if stage in prev_stage:
                                before = done_so_far[(o.pk, prev_stage[stage])]
                                if before < planned_for[(o.pk, prev_stage[stage])] * Decimal("0.15"):
                                    continue
                            pick = o
                            break
                        if pick is None:
                            break
                        take = min(shift_qty, need[(pick.pk, stage)] - done_so_far[(pick.pk, stage)]).quantize(Decimal("0.1"))
                        if take <= 0:
                            break
                        lo, hi = WASTE_PCT[stage]
                        StageLog.objects.create(
                            order=pick, stage=stage, machine=random.choice(machines[stage]), date=day, shift=shift,
                            quantity=take, waste=(take * Decimal(str(random.uniform(lo, hi)))).quantize(Decimal("0.1")),
                            operator=random.choice(OPERATORS),
                        )
                        done_so_far[(pick.pk, stage)] += take
                        shift_qty -= take
                        produced_any = True
                if produced_any or back == 0:
                    DailyTarget.objects.create(date=day, stage=stage, target_qty=target)

        # Downtime
        all_machines = [m for lst in machines.values() for m in lst]
        cats = ["mechanical", "mechanical", "electrical", "power", "maintenance", "material", "changeover", "other"]
        for _ in range(17):
            cat = random.choice(cats)
            start = now - timedelta(days=random.randint(1, 29), hours=random.randint(0, 20))
            DowntimeRecord.objects.create(
                machine=random.choice(all_machines), started_at=start, ended_at=start + timedelta(minutes=random.randint(20, 280)),
                category=cat, description=random.choice(DOWNTIME_NOTES[cat]), reported_by=random.choice(OPERATORS),
            )
        lm04 = next(m for m in all_machines if m.code == "LM-04")
        rf02 = next(m for m in all_machines if m.code == "RF-02")
        DowntimeRecord.objects.create(machine=lm04, started_at=now - timedelta(minutes=95), category="mechanical", description="Warp beam alignment fault", reported_by="R. Patil")
        DowntimeRecord.objects.create(machine=rf02, started_at=now - timedelta(minutes=40), category="electrical", description="Drive panel tripped", reported_by="S. Deshmukh")

        # Defects: only on orders that actually ran through that stage on that day
        types = ["slub", "hole", "broken_end", "weft_bar", "oil_stain", "uneven_dye", "shade", "selvedge", "other"]
        weights = [18, 12, 22, 14, 7, 10, 9, 6, 2]
        made = 0
        while made < 30:
            dtype = random.choices(types, weights)[0]
            stage = "finishing" if dtype in ("uneven_dye", "shade") else "weaving"
            day = today - timedelta(days=random.randint(0, 27))
            logs = list(StageLog.objects.filter(date=day, stage=stage).select_related("order"))
            if not logs:
                continue
            severity = random.choices(["minor", "major", "critical"], [48, 34, 18])[0]
            disposition = {"minor": "rework", "major": random.choice(["rework", "downgrade", "downgrade"]), "critical": "scrap"}[severity]
            log = random.choice(logs)
            DefectRecord.objects.create(
                order=log.order, stage=stage, machine=log.machine, date=day,
                defect_type=dtype, severity=severity, disposition=disposition,
                quantity=Decimal(str(round(random.uniform(20, 220), 1))), inspected_by=random.choice(INSPECTORS),
            )
            made += 1

        self.stdout.write(self.style.SUCCESS("Demo data created. Sign in with  admin / admin123"))
