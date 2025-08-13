from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count
from market.models import *
from .models import *
from accounts.models import CustomUser
from datetime import timedelta
from django.utils import timezone

# Create your views here.
@login_required
def point_home(request):
    user = request.user

    # 내 총 포인트 (누적 테이블 사용)
    up, _ = UserPoint.objects.get_or_create(user=user)
    my_total = up.total_point

    # 내 랭킹: 나보다 점수 큰 사람 수 + 1
    my_rank = UserPoint.objects.filter(total_point__gt=my_total).count() + 1 if my_total > 0 else None

    # 이번 주 월요일 날짜 구하기
    today = timezone.localdate()  # 현지 날짜
    week_start_date = today - timedelta(days=today.weekday())

    # 날짜 기준으로 필터
    weekly_points = (
        ActivityLog.objects
        .filter(user=user, visited_at__date__gte=week_start_date)
        .aggregate(total=Sum('point_earned'))['total'] or 0
    )

    return render(request, 'point/home.html', {
        'total_points': my_total,
        'weekly_points': weekly_points,
        'user_address': getattr(user, 'location', None) or '미등록',
        'my_rank': my_rank,
    })

PERIODS = {
    '1m': 30, '3m': 90, '6m': 180, '1y': 365, 'all': None,
}

@login_required
def point_history(request):
    period = request.GET.get('period', '1m')   # 1m,3m,6m,1y,all
    sort = request.GET.get('sort', 'latest')   # latest, points

    qs = ActivityLog.objects.filter(user=request.user)

    if period in PERIODS and PERIODS[period] is not None:
        cutoff = timezone.now() - timedelta(days=PERIODS[period])
        qs = qs.filter(visited_at__gte=cutoff)

    sort_field = 'visited_at' if sort == 'latest' else 'point_earned'
    qs = qs.order_by(f'-{sort_field}')

    summary = qs.aggregate(total_points=Sum('point_earned'), count=Count('id'))

    return render(request, 'point/history.html', {
        'logs': qs,
        'summary': summary,
        'selected': {'period': period, 'sort': sort},
        'PERIODS': PERIODS,
    })

def _my_district(user) -> str | None:
    """대표 주소의 addr_level2 우선, 없으면 미러 필드 사용."""
    addr = getattr(user, "active_address", None)
    if addr and addr.addr_level2:
        return addr.addr_level2
    return getattr(user, "addr_level2", None)

@login_required
def point_ranking(request):
    district = _my_district(request.user)
    local_users = (
        CustomUser.objects.filter(addr_level2=district) if district
        else CustomUser.objects.all()
    )

    now = timezone.now()
    start_of_week = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    next_week = start_of_week + timedelta(days=7)

    # 이번 주, 같은 구의 전체 로그
    base_qs = ActivityLog.objects.filter(
        user__in=local_users,
        visited_at__gte=start_of_week,
        visited_at__lt=next_week,
    )

    # 헤더 카드(이번 주 전체 기준)
    header_stats = {
        "shopper_count": base_qs.values("user_id").distinct().count(),
        "total_points": base_qs.aggregate(s=Sum("point_earned"))["s"] or 0,
    }

    # 주간 TOP 30
    weekly_top30 = (
        base_qs.values("user_id", "user__nickname", "user__addr_level3")
        .annotate(points=Sum("point_earned"))
        .order_by("-points", "user_id")[:30]
    )

    return render(request, "point/ranking.html", {
        "district": district,
        "weekly_top30": weekly_top30,
        "header_stats": header_stats,
    })