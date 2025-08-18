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
