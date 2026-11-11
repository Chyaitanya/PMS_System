from .models import DowntimeRecord, Material


def sidebar_counts(request):
    if not request.user.is_authenticated:
        return {}
    from django.db.models import F
    return {
        "nav_down_count": DowntimeRecord.objects.filter(ended_at__isnull=True).count(),
        "nav_low_stock": Material.objects.filter(quantity__lte=F("reorder_level")).count(),
    }
