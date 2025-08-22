// getPoint.js
document.addEventListener("DOMContentLoaded", () => {
  const scroller = document.querySelector(".app-body");

  // 상단 sticky 2줄(상태바+앱탑바) 높이만큼 여유
  const rs = getComputedStyle(document.documentElement);
  const statusH = parseInt(rs.getPropertyValue("--status-h")) || 44;
  const topH = parseInt(rs.getPropertyValue("--apptop-h")) || 44;
  const offset = statusH + topH + 10;

  const alignUnderSticky = (el) => {
    if (!scroller || !el) return;
    const top =
      el.getBoundingClientRect().top - scroller.getBoundingClientRect().top;
    scroller.scrollBy({ top: top - offset, behavior: "smooth" });
  };

  // ========== 1) 입구 사진 확인하기 ==========
  document.querySelectorAll(".section-title .center-arrow").forEach((arrow) => {
    const section = arrow.closest(".section-title");
    const titleEl = section?.querySelector(".section-title2") || section;
    if (!section) return;

    const toggle = () => {
      section.classList.toggle("open");
      const open = section.classList.contains("open");
      // 아이콘 회전/검정 (CSS 트랜지션 있으면 자연스럽게 돌아감)
      arrow.style.transform = open ? "rotate(180deg)" : "rotate(0deg)";
      arrow.style.filter = open ? "brightness(0) saturate(100%)" : "";
      if (open) alignUnderSticky(titleEl);
    };

    arrow.setAttribute("role", "button");
    arrow.setAttribute("tabindex", "0");
    arrow.addEventListener("click", toggle);
    arrow.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        toggle();
      }
    });
  });

  // ========== 2) 장바구니 체크리스트 ==========
  document
    .querySelectorAll("h4.section-title2 .center-arrow")
    .forEach((arrow) => {
      const heading = arrow.closest("h4.section-title2");
      if (!heading) return;

      // 바로 다음 형제의 .checklist-card를 우선 찾고, 없으면 근처에서 보조 탐색
      let panel = heading.nextElementSibling;
      if (!panel || !panel.classList.contains("checklist-card")) {
        panel = heading.parentElement?.querySelector(".checklist-card");
      }

      const toggle = () => {
        const open = heading.classList.toggle("open");
        if (panel) panel.classList.toggle("open", open);
        arrow.style.transform = open ? "rotate(180deg)" : "rotate(0deg)";
        arrow.style.filter = open ? "brightness(0) saturate(100%)" : "";
        if (open) alignUnderSticky(heading);
      };

      arrow.setAttribute("role", "button");
      arrow.setAttribute("tabindex", "0");
      arrow.addEventListener("click", toggle);
      arrow.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          toggle();
        }
      });
    });
});

// getPoint.js (모달 열기/닫기)

document.addEventListener("DOMContentLoaded", () => {
  const scroller = document.querySelector(".app-body"); // 내부 스크롤 컨테이너
  const trigger = document.querySelector(".not-this-mart"); // "사진과 도착지가 다르다면?"
  const modal = document.querySelector(".re-start-modal"); // 오버레이
  const content = modal?.querySelector(".modal-content"); // 모달 카드
  const closeBtn = modal?.querySelector(".closeBtn");
  const callBtn = modal?.querySelector(".callBtn");
  const reNavBtn = modal?.querySelector(".renavigationBtn");

  if (!trigger || !modal || !content) return;

  let lastFocus = null;

  const openModal = () => {
    lastFocus = document.activeElement;
    modal.classList.remove("hidden");
    modal.setAttribute("aria-hidden", "false");

    // 스크롤 잠금
    scroller?.classList.add("no-scroll");
    document.body.classList.add("modal-open");

    // 포커스 이동(접근성)
    (closeBtn || content).focus?.({ preventScroll: true });
  };

  const closeModal = () => {
    modal.classList.add("hidden");
    modal.setAttribute("aria-hidden", "true");

    // 스크롤 잠금 해제
    scroller?.classList.remove("no-scroll");
    document.body.classList.remove("modal-open");

    // 포커스 복귀
    lastFocus?.focus?.({ preventScroll: true });
  };

  // 열기
  trigger.addEventListener("click", openModal);

  // 닫기(X)
  closeBtn?.addEventListener("click", closeModal);

  // 바깥 클릭 닫기 (오버레이 부분만)
  modal.addEventListener("click", (e) => {
    if (e.target === modal) closeModal();
  });

  // ESC 닫기 + 탭 포커스 트랩
  document.addEventListener("keydown", (e) => {
    if (modal.classList.contains("hidden")) return;

    if (e.key === "Escape") {
      e.preventDefault();
      closeModal();
      return;
    }

    if (e.key === "Tab") {
      const focusables = modal.querySelectorAll(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
      );
      if (!focusables.length) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];

      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  });

  // 버튼 동작(원하면 여기서 실제 액션 연결)
  callBtn?.addEventListener("click", () => {
    // 예: window.location.href = 'tel:010-0000-0000';
    closeModal();
  });
  reNavBtn?.addEventListener("click", () => {
    // 예: 재네비게이션 트리거
    closeModal();
  });
});
