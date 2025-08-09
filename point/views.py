from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from market.models import *
from accounts.models import CustomUser

# Create your views here.
@login_required
def point_home(request):
    user = request.user
    
    # 1. 전체 사용자 포인트 랭킹 계산
    rankings = ActivityLog.objects.values('user') \
        .annotate(total_points=Sum('point_earned')) \
        .order_by('-total_points')

    # 2. 내 포인트
    my_total = 0
    for rank, entry in enumerate(rankings, start=1):
        if entry['user'] == user.id:
            my_total = entry['total_points']
            my_rank = rank
            break
    else:
        my_total = 0
        my_rank = None  # 아직 활동 기록이 없는 경우

    # 3. 주간 포인트
    from datetime import timedelta
    from django.utils import timezone

    now = timezone.now()
    start_of_week = now - timedelta(days=now.weekday())
    weekly_points = ActivityLog.objects.filter(user=user, visited_at__gte=start_of_week) \
        .aggregate(total=Sum('point_earned'))['total'] or 0

    return render(request, 'point/home.html', {
        'total_points': my_total,
        'weekly_points': weekly_points,
        'user_address': user.location or '미등록',
        'my_rank': my_rank,
    })


@login_required
def point_history(request):
    logs = ActivityLog.objects.filter(user=request.user).order_by('-visited_at')
    return render(request, 'point/history.html', {'logs': logs})


@login_required
def point_ranking(request):
    rankings = ActivityLog.objects.values('user__location', 'user__username') \
        .annotate(total_points=Sum('point_earned')) \
        .order_by('-total_points')

    return render(request, 'point/ranking.html', {'rankings': rankings})