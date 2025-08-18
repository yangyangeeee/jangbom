document.addEventListener('DOMContentLoaded', () => {
    const input = document.querySelector('.gptInput');
    const keyboardIcon = document.querySelector('.keyboard-icon');
    const foodBtn = document.querySelector('.foodBtn');
    const selectBtn = document.querySelector('.selectBtn');
    const gptBox = document.getElementById('gptBox');
    
    // 초기 숨김 상태
    keyboardIcon.style.display = 'none';
    foodBtn.style.display = 'none';

    // input에 글자가 들어올 때
    input.addEventListener('input', () => {
        if (input.value.trim() !== "") {
            keyboardIcon.style.display = 'block';
            foodBtn.style.display = 'flex';
            selectBtn.classList.add('hidden');
            gptBox.classList.add('up');
        } else {
            keyboardIcon.style.display = 'none';
            foodBtn.style.display = 'none';
            selectBtn.classList.remove('hidden');
            gptBox.classList.remove('up');
        }
    });

    // document 클릭 이벤트
    document.addEventListener('click', (e) => {
        // 클릭된 요소가 input이 아니라면 원래 상태로 되돌림
        if (!input.contains(e.target)) {
            keyboardIcon.style.display = 'none';
            foodBtn.style.display = 'none';
            selectBtn.classList.remove('hidden');
            gptBox.classList.remove('up');
            input.value = ''; // 필요하면 입력값도 초기화
        }
    });
});
