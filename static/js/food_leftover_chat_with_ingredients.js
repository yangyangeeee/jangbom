document.addEventListener('DOMContentLoaded', () => {
    const input = document.querySelector('.gptInput');
    const keyboardIcon = document.querySelector('.keyboard-icon');
    const foodBtn = document.querySelector('.foodBtn');
    const gptBox = document.getElementById('gptBox');

    // 초기 숨김 상태
    keyboardIcon.style.display = 'none';

    input.addEventListener('input', () => {
        if (input.value.trim() !== "") {
            keyboardIcon.style.display = 'block';
            foodBtn.classList.add('up'); // 보여주기
            gptBox.classList.add('up');
        } else {
            keyboardIcon.style.display = 'none';
            foodBtn.classList.add('up');// 숨기기
            gptBox.classList.remove('up');
        }
    });

    // input 외부 클릭 시 원래 상태로 돌아오기
    document.addEventListener('click', (e) => {
        if (!input.contains(e.target)) { // 클릭한 곳이 input이 아니면
            keyboardIcon.style.display = 'none';
            foodBtn.classList.remove('up');
            gptBox.classList.remove('up');
        }
    });
});




// 모달창
document.addEventListener("DOMContentLoaded", function() {
    const modal = document.getElementById("customModal");
    const openModalBtn = document.getElementById("openModalBtn");
    const confirmBtn = document.getElementById("confirmBtn");
    const backBtn = document.getElementById("backBtn");
    const form = document.querySelector(".ingredientsGet");

    // 버튼 클릭 시 모달 열기 (폼 제출 막기)
    openModalBtn.addEventListener("click", function(e) {
        e.preventDefault();
        modal.style.display = "block";
    });

    // 확인 → 폼 전송
    confirmBtn.addEventListener("click", function() {
        form.submit();
    });

    // 취소 → 모달 닫기
    backBtn.addEventListener("click", function() {
        modal.style.display = "none";
    });

    // 배경 클릭 시 모달 닫기
    window.addEventListener("click", function(e) {
        if (e.target === modal) {
            modal.style.display = "none";
        }
    });
});
