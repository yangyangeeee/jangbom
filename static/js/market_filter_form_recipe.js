function makeExclusive(name, defaultIndex = 0) {
    const boxes = Array.from(document.querySelectorAll(`input[type=checkbox][name="${name}"]`));

    // 기본 체크박스 선택
    boxes.forEach((b,i) => b.checked = (i === defaultIndex));

    boxes.forEach(b => {
        b.addEventListener('change', function() {
            if (this.checked) {
                boxes.forEach(x => { if (x !== this) x.checked = false; });
            } else {
                // 최소 하나 선택 유지
                this.checked = true;
            }
        });
    });
}

// 거리: 두 번째 체크박스 선택 (index 1)
makeExclusive('distance_preference', 1);

// 상점 종류: 세 번째 체크박스 선택 (index 2)
makeExclusive('type_preference', 2);