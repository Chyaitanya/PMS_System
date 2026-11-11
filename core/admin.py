from django.contrib import admin

from . import models

for model in (
    models.Material, models.StockMovement, models.Machine, models.ProductionOrder,
    models.StageLog, models.DailyTarget, models.DowntimeRecord, models.DefectRecord,
):
    admin.site.register(model)
