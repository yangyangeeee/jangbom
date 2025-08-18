document.addEventListener('DOMContentLoaded', () => {
  // 하단 탭 활성화
  const tabs = document.querySelectorAll('#bottomTab a');
  const currentPath = window.location.pathname;

  tabs.forEach(tab => {
    const href = tab.getAttribute('href');
    if (href === currentPath) {
      tab.classList.add('active');
    } else {
      tab.classList.remove('active');
    }

    // 클릭 시 active 변경 (SPA 아니면 없어도 됨)
    tab.addEventListener('click', () => {
      tabs.forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
    });
  });

  // 배너 선택 영역
const divs = document.querySelectorAll('.clickable');
const bannerImg = document.getElementById('banner-img');

divs.forEach(div => {
    div.addEventListener('click', () => {
      // 이미지 변경
    if (div.id === 'mart') {
        bannerImg.src = '/jangbom/static/img/banner1.png';
    } else if (div.id === 'cafe') {
        bannerImg.src = '/jangbom/static/img/banner2.png';
    } else if (div.id === 'localMart') {
        bannerImg.src = '/jangbom/static/img/banner1.png';
    }

      // active 클래스 토글
    divs.forEach(d => d.classList.remove('active'));
      div.classList.add('active');
    });
  });
});
