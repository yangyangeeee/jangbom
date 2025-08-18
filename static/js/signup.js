// 단계 이동 함수
function goStep(stepNumber) {
    // 모든 step 숨기기
    document.querySelectorAll('.step').forEach(step => {
        step.classList.remove('active');
    });

    // 선택한 step 보이기
    document.getElementById(`step${stepNumber}`).classList.add('active');
}

// 뒤로가기 버튼 (아이디 입력 → 로그인 페이지, 나머지는 이전 단계)
document.querySelectorAll('.backIcon').forEach(btn => {
    btn.addEventListener('click', (e) => {
        e.preventDefault(); // 기본 a 태그 이동 막기
        const activeStep = document.querySelector('.step.active');
        if (activeStep.id === 'step1') {
            // 첫 단계면 로그인 페이지로 이동
            window.location.href = '/jangbom/static/html/login.html';
        } else if (activeStep.id === 'step2') {
            goStep(1);
        } else if (activeStep.id === 'step3') {
            goStep(2);
        }
    });
});


document.querySelector('.completeBtn').addEventListener('click', () => {
    window.location.href = '/jangbom/static/html/splash.html';
});

