from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count, F
from market.models import *
from .models import *
from accounts.models import CustomUser
from datetime import timedelta, datetime, time
from django.utils import timezone
from django.contrib import messages
from django.db import transaction, IntegrityError
from django.utils.crypto import get_random_string
from food.views import get_user_total_point, cart_items_count

# Create your views here.
def _my_district(user) -> str | None:
    """대표 주소의 addr_level2 우선, 없으면 미러 필드 사용."""
    addr = getattr(user, "active_address", None)
    if addr and addr.addr_level2:
        return addr.addr_level2
    return getattr(user, "addr_level2", None)

@login_required
def point_home(request):
    user = request.user

    up, _ = UserPoint.objects.get_or_create(user=user)
    my_total = up.total_point

    # 이번 주 (월~일) 경계 계산 — zoneinfo 방식
    now_local = timezone.localtime()  # tz-aware
    week_start_date = now_local.date() - timedelta(days=now_local.weekday())

    start_of_week_naive = datetime.combine(week_start_date, time.min)   # naive
    end_of_week_naive   = start_of_week_naive + timedelta(days=7)

    tz = timezone.get_current_timezone()
    start_of_week = timezone.make_aware(start_of_week_naive, tz)
    end_of_week   = timezone.make_aware(end_of_week_naive, tz)

    # 내 구(district)
    district = _my_district(user)
    local_users = (
        CustomUser.objects.filter(addr_level2=district) if district
        else CustomUser.objects.all()
    )

    base_qs = ActivityLog.objects.filter(
        user__in=local_users,
        visited_at__gte=start_of_week,
        visited_at__lt=end_of_week,
    )

    weekly_points = base_qs.filter(user=user).aggregate(
        s=Sum("point_earned")
    )["s"] or 0

    if weekly_points > 0:
        higher_cnt = (
            base_qs.values("user_id")
                .annotate(points=Sum("point_earned"))
                .filter(points__gt=weekly_points)
                .count()
        )
        my_rank = higher_cnt + 1
    else:
        my_rank = None

    items_count = cart_items_count(user)
    total_point = get_user_total_point(user)

    return render(request, "point/home.html", {
        "district": district,
        "total_points": my_total,
        "weekly_points": weekly_points,
        "my_rank": my_rank,
        "cart_items_count": items_count,
        "total_point": total_point,
    })

PERIODS = {
    '1m': 30, '3m': 90, '6m': 180, '1y': 365, 'all': None,
}

@login_required
def point_history(request):
    user = request.user

    period = request.GET.get('period', '1m')   # 1m,3m,6m,1y,all
    sort = request.GET.get('sort', 'latest')   # latest, points

    qs = ActivityLog.objects.filter(user=request.user)

    if period in PERIODS and PERIODS[period] is not None:
        cutoff = timezone.now() - timedelta(days=PERIODS[period])
        qs = qs.filter(visited_at__gte=cutoff)

    sort_field = 'visited_at' if sort == 'latest' else 'point_earned'
    qs = qs.order_by(f'-{sort_field}')

    summary = qs.aggregate(total_points=Sum('point_earned'), count=Count('id'))

    items_count = cart_items_count(user)
    total_point = get_user_total_point(user)

    return render(request, 'point/history.html', {
        'logs': qs,
        'summary': summary,
        'selected': {'period': period, 'sort': sort},
        'PERIODS': PERIODS,
        "cart_items_count": items_count,
        "total_point": total_point,
    })

@login_required
def point_ranking(request):
    user = request.user
    
    district = _my_district(request.user)
    local_users = (
        CustomUser.objects.filter(addr_level2=district) if district
        else CustomUser.objects.all()
    )

    now_local = timezone.localtime()
    start_of_week = now_local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now_local.weekday())
    next_week = start_of_week + timedelta(days=7)

    # 이번 주, 같은 구의 전체 로그
    base_qs = ActivityLog.objects.filter(
        user__in=local_users,
        visited_at__gte=start_of_week,
        visited_at__lt=next_week,
    )

    # 이번 주
    weekly_stats = {
        "shopper_count": base_qs.values("user_id").distinct().count(),
        "total_points": base_qs.aggregate(s=Sum("point_earned"))["s"] or 0,
    }

    # 전체
    all_qs = ActivityLog.objects.filter(user__in=local_users)
    total_stats = {
        "shopper_count": all_qs.values("user_id").distinct().count(),
        "total_points": all_qs.aggregate(s=Sum("point_earned"))["s"] or 0,
    }

    # 주간 TOP 30
    weekly_top30 = (
        base_qs.values("user_id", "user__nickname", "user__addr_level3")
        .annotate(points=Sum("point_earned"))
        .order_by("-points", "user_id")[:30]
    )

    items_count = cart_items_count(user)
    total_point = get_user_total_point(user)

    return render(request, "point/ranking.html", {
        "district": district,
        "weekly_top30": weekly_top30,
        "weekly_stats": weekly_stats,
        "total_stats": total_stats,
        "cart_items_count": items_count,
        "total_point": total_point,
    })

# 바코드
@login_required
def barcode_view(request):
    user_point, _ = UserPoint.objects.get_or_create(user=request.user)

    if request.method == "POST":
        # 1) PIN 확인 (4자리 숫자)
        code = (request.POST.get("code") or "").strip()
        if not (code.isdigit() and len(code) == 4):
            messages.error(request, "인증번호는 4자리 숫자여야 합니다.")
            return redirect('point:barcode')

        active_pin = StaffPin.objects.filter(is_active=True).first()
        if not active_pin or not active_pin.verify(code):
            messages.error(request, "인증번호가 올바르지 않습니다.")
            return redirect('point:barcode')

        # 2) 사용할 포인트 파싱/검증
        try:
            use_point = int(request.POST.get("use_point", 0))
        except ValueError:
            messages.error(request, "포인트 입력이 올바르지 않습니다.")
            return redirect('point:barcode')

        if use_point < 0 or use_point % 100 != 0:
            messages.error(request, "포인트는 100P 단위의 0 이상의 값만 사용 가능합니다.")
            return redirect('point:barcode')

        # 3) 중복 방지 키
        request_id = (request.POST.get("request_id") or "").strip() or get_random_string(24)
        if PointUsage.objects.filter(request_id=request_id).exists():
            messages.info(request, "이미 처리된 요청입니다.")
            return redirect('point:barcode')

        # 4) 원자적 차감 + 사용 이력 기록
        try:
            with transaction.atomic():
                updated = UserPoint.objects.filter(
                    user=request.user,
                    total_point__gte=use_point
                ).update(total_point=F('total_point') - use_point)

                if updated == 0:
                    messages.error(request, "포인트가 부족합니다.")
                    return redirect('point:barcode')

                user_point.refresh_from_db(fields=['total_point'])

                PointUsage.objects.create(
                    user=request.user,
                    amount=use_point,
                    request_id=request_id,
                    memo="바코드 차감"
                )

        except IntegrityError:
            messages.info(request, "이미 처리된 요청입니다.")
            return redirect('point:barcode')
        except Exception:
            messages.error(request, "처리 중 오류가 발생했습니다.")
            return redirect('point:barcode')

        # 5) 성공 모달에 쓸 정보 저장
        request.session['point_processed'] = {
            'used': use_point,
            'remaining': int(user_point.total_point),
        }
        return redirect('point:barcode')

    # GET: 성공 정보 있으면 모달로 표시
    success_info = request.session.pop('point_processed', None)
    return render(request, 'point/barcode.html', {
        'total_point': user_point.total_point,
        'success_info': success_info,
        'request_id': get_random_string(24),  # 중복 방지용
    })