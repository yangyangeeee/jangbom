from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
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

@login_required
def point_history(request):
    logs = ActivityLog.objects.filter(user=request.user).order_by('-visited_at')
    return render(request, 'point/history.html', {'logs': logs})

@login_required
def point_ranking(request):
    # 전체 랭킹은 누적 테이블(UserPoint) 기준
    rankings = (
        UserPoint.objects.select_related('user')
        .order_by('-total_point', 'user_id')
    )
    # 템플릿에서 entry.user.username / entry.user.location / entry.total_point 사용
    return render(request, 'point/ranking.html', {'rankings': rankings})