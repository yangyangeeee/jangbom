document.addEventListener("DOMContentLoaded", () => {
  /* ===== 공통 엘리먼트 ===== */
  const rangeBtn = document.getElementById("rangeBtn");
  const rangeMenu = document.getElementById("rangeMenu");
  const rangeItems = Array.from(
    rangeMenu?.querySelectorAll(".range-item") || []
  );
  const listWrap = document.querySelector(".list-set");
  const items = Array.from(listWrap?.querySelectorAll(".recipes_list") || []);
  const latestTab = document.querySelector(".search-filter .lately");
  const alphaTab = document.querySelector(".search-filter .abc");

  if (!rangeBtn || !rangeMenu || !items.length || !latestTab || !alphaTab)
    return;

  /* ===== 유틸: 날짜/제목 파싱 ===== */
  const parseDate = (str) => {
    // 예: "2025.08.13 15:00"
    const m = String(str || "")
      .trim()
      .match(/(\d{4})[.\-\/](\d{2})[.\-\/](\d{2})\s+(\d{2}):(\d{2})/);
    if (!m) return 0;
    const [, y, M, d, h, min] = m;
    return new Date(`${y}-${M}-${d}T${h}:${min}:00`).getTime();
  };
  const getTitle = (el) =>
    el.querySelector(".menu_name")?.textContent.trim() || "";
  const getTime = (el) => {
    // 캐시(없으면 menu_date에서 읽어와 data-ts로 저장)
    let ts = el.dataset.ts ? Number(el.dataset.ts) : NaN;
    if (Number.isNaN(ts)) {
      ts = parseDate(el.querySelector(".menu_date")?.textContent);
      el.dataset.ts = String(ts);
    }
    return ts;
  };

  // 초기 DOM 순서 기억(안전한 재배치용)
  items.forEach((el, i) => (el._idx = i));

  /* ===== 1) 범위 드롭다운 ===== */

  // 메뉴 열고/닫기
  const openMenu = () => {
    rangeMenu.hidden = false;
    rangeBtn.setAttribute("aria-expanded", "true");
    document.addEventListener("click", onDocClick);
    document.addEventListener("keydown", onEscClose);
  };
  const closeMenu = () => {
    rangeMenu.hidden = true;
    rangeBtn.setAttribute("aria-expanded", "false");
    document.removeEventListener("click", onDocClick);
    document.removeEventListener("keydown", onEscClose);
  };
  const toggleMenu = () => (rangeMenu.hidden ? openMenu() : closeMenu());

  // 바깥 클릭 시 닫기
  const onDocClick = (e) => {
    if (e.target.closest(".range-dropdown")) return;
    closeMenu();
  };
  const onEscClose = (e) => {
    if (e.key === "Escape") closeMenu();
  };

  rangeBtn.addEventListener("click", toggleMenu);

  // 범위 → 기준 시각 계산
  const calcSince = (value) => {
    const now = new Date();
    const since = new Date(now);
    switch (value) {
      case "1m":
        since.setMonth(now.getMonth() - 1);
        break;
      case "3m":
        since.setMonth(now.getMonth() - 3);
        break;
      case "6m":
        since.setMonth(now.getMonth() - 6);
        break;
      case "1y":
        since.setFullYear(now.getFullYear() - 1);
        break;
      case "all":
        return 0; // 전체
      default:
        return 0;
    }
    return since.getTime();
  };

  // 메뉴 항목 선택
  const selectRange = (li) => {
    rangeItems.forEach((el) => {
      const on = el === li;
      el.classList.toggle("is-selected", on);
      el.setAttribute("aria-selected", on ? "true" : "false");
    });
    // 버튼 라벨 업데이트
    rangeBtn.childNodes[0].nodeValue = (li.textContent || "").trim() + " ";
    rangeBtn.dataset.value = li.dataset.value || "";

    // 필터 적용
    applyRangeFilter(li.dataset.value || "all");
    closeMenu();
  };

  // 실제 필터링
  const applyRangeFilter = (value) => {
    const sinceTs = calcSince(value);
    items.forEach((el) => {
      const ts = getTime(el);
      const visible = value === "all" ? true : ts >= sinceTs;
      el.style.display = visible ? "" : "none";
    });
  };

  // 메뉴 항목 클릭 바인딩
  rangeItems.forEach((li) =>
    li.addEventListener("click", () => selectRange(li))
  );

  // 초기 상태(현재 is-selected된 값으로)
  const initialRange =
    rangeItems.find((el) => el.classList.contains("is-selected")) ||
    rangeItems[0];
  if (initialRange) selectRange(initialRange);

  /* ===== 2) 최신순 / 가나다순 정렬 ===== */

  const setActiveTab = (btn) => {
    [latestTab, alphaTab].forEach((el) =>
      el.classList.toggle("is-active", el === btn)
    );
  };

  const sortList = (mode) => {
    // 현재 display:none인 항목은 그대로 두고, 보이는 항목만 정렬
    const visible = items.filter((el) => el.style.display !== "none");
    const hidden = items.filter((el) => el.style.display === "none");

    const sorted = visible.slice().sort((a, b) => {
      if (mode === "alpha") {
        return getTitle(a).localeCompare(getTitle(b), "ko", {
          sensitivity: "base",
          numeric: true,
        });
      }
      // 최신순(내림차순)
      return getTime(b) - getTime(a);
    });

    // DOM 재배치: 보이는 것들 먼저 순서대로, 그 뒤에 감춰진 것들 원래 순서대로
    sorted.forEach((el) => listWrap.appendChild(el));
    hidden
      .sort((a, b) => a._idx - b._idx)
      .forEach((el) => listWrap.appendChild(el));
  };

  latestTab.addEventListener("click", () => {
    setActiveTab(latestTab);
    sortList("latest");
  });
  alphaTab.addEventListener("click", () => {
    setActiveTab(alphaTab);
    sortList("alpha");
  });

  // 초기: 최신순
  setActiveTab(latestTab);
  sortList("latest");
});

// ../js/activity_history.js
("use strict");

/* =========================
   공통 전환/잠금 유틸
   ========================= */
const DURATION = 280;
const baseH = new WeakMap();
const busyRows = new WeakSet();
const lockRow = (row, on) => (row.style.pointerEvents = on ? "none" : "");

const onTransitionEnd = (el, prop) =>
  new Promise((resolve) => {
    const h = (e) => {
      if (!prop || e.propertyName === prop) {
        el.removeEventListener("transitionend", h);
        resolve();
      }
    };
    el.addEventListener("transitionend", h);
  });

/* =========================
   상세 패널 생성
   ========================= */
function makeActivityPanel(name, dateText, data) {
  const d = data || {};
  const items = Array.isArray(d.ingredients) ? d.ingredients : [];

  const nf = new Intl.NumberFormat("ko-KR");
  const minutes = d.travel_minutes ?? "-";
  const steps = d.steps != null ? nf.format(d.steps) : "-";
  const kcal =
    d.calories_kcal != null
      ? (Math.round(Number(d.calories_kcal) * 10) / 10).toString()
      : "-";
  const point =
    d.point_earned != null ? `+ ${nf.format(d.point_earned)} P` : "+ 0 P";

  const panel = document.createElement("div");
  panel.className = "activity-detail-inline";
  Object.assign(panel.style, {
    flexBasis: "100%",
    width: "100%",
    marginTop: "10px",
    paddingTop: "10px",
    borderTop: "1px solid #e9e9e9",
    fontSize: "14px",
    lineHeight: "1.55",
    opacity: "0",
    transition: `opacity ${DURATION}ms ease`,
  });

  panel.innerHTML = `
    <div class="detail-body">

      <div style="display:flex; align-items:center; gap:8px; margin:0 0 10px;">
        <span style="font-size:16px">📝</span>
        <h4 style="margin:0; font-size:15px;">걷기 기록</h4>
      </div>

      <div style="display:grid; grid-template-columns:1fr auto; row-gap:8px; column-gap:12px; margin-bottom:12px;">
        <div style="color:#4b5563;">이동 시간</div>
        <div style="justify-self:end; color:#111827;">${minutes} 분</div>

        <div style="color:#4b5563;">걸음 수</div>
        <div style="justify-self:end; color:#111827;">${steps} 걸음</div>

        <div style="color:#4b5563;">소모 칼로리</div>
        <div style="justify-self:end; color:#111827;">${kcal} kcal</div>

        <div style="color:#4b5563;">획득 포인트</div>
        <div style="justify-self:end; color:#5b8f00; font-weight:700;">${point}</div>
      </div>

      ${
        items.length
          ? `
            <div style="display:flex; align-items:center; gap:8px; margin:14px 0 8px;">
              <span style="font-size:16px">🍽️</span>
              <h4 style="margin:0; font-size:15px;">구매한 식재료</h4>
            </div>
            <ul style="list-style:none; padding:0; margin:0; border:1px solid #eee; border-radius:10px; overflow:hidden;">
              ${items
                .map(
                  (x) =>
                    `<li style="padding:10px 12px; border-bottom:1px solid #eee;">${x}</li>`
                )
                .join("")}
            </ul>
          `
          : ""
      }
    </div>
  `;

  // 마지막 아이템 보더 제거
  const lis = panel.querySelectorAll("ul > li");
  if (lis.length) lis[lis.length - 1].style.borderBottom = "0";

  return panel;
}

/* =========================
   하단 CTA (열린 카드가 1개 이상이면 표시)
   ========================= */
let fridgeCta = null;
function ensureCTA() {
  if (fridgeCta) return fridgeCta;
  const box = document.querySelector(".box") || document.body;

  fridgeCta = document.createElement("div");
  fridgeCta.id = "fridgeCta";
  Object.assign(fridgeCta.style, {
    position: "sticky",
    bottom: "65px",
    width: "393px",
    height: "122px",
    zIndex: "45",
    margin: "0 16px",
    padding: "14px",
    background: "#fff",
    boxShadow: "0 6px 22px rgba(0,0,0,.08)",
    display: "none",
  });

  const msg = document.createElement("p");
  msg.textContent = "아직 냉장고에 식재료가 남아있나요?";
  Object.assign(msg.style, {
    margin: "0 0 10px",
    textAlign: "center",
    color: "#545454",
    fontSize: "16px",
    fontWeight: "600",
  });

  const btn = document.createElement("button");
  btn.type = "button";
  btn.textContent = "기존 식재료로 요리법 찾기";
  btn.className = "fridge-cta-btn";
  Object.assign(btn.style, {
    width: "271px",
    padding: "14px 16px",
    display: "block",
    margin: "0 auto",
    borderRadius: "12px",
    border: "0",
    background: "#cce7a3",
    fontWeight: "600",
    fontSize: "20px",
    color: "#fff",
    cursor: "pointer",
  });
  btn.addEventListener("click", () => {
    // TODO: 라우팅/모달 연결
    console.log("[CTA] 기존 식재료로 요리법 찾기");
  });

  fridgeCta.append(msg, btn);
  const bottomNav = document.querySelector(".bottom-nav");
  const parent = document.querySelector(".box") || document.body;
  if (bottomNav && bottomNav.parentElement === parent) {
    parent.insertBefore(fridgeCta, bottomNav);
  } else {
    parent.appendChild(fridgeCta);
  }
  return fridgeCta;
}
function showCTA() {
  const el = ensureCTA();
  el.style.display = "block";
}
function hideCTA() {
  if (fridgeCta) fridgeCta.style.display = "none";
}
function updateCTAVisibility() {
  const anyOpen = document.querySelector(".recipes_list.open");
  if (anyOpen) showCTA();
  else hideCTA();
}

/* =========================
   데이터 로딩 (처음 열 때만 fetch)
   - row.dataset.id 와 window.ajaxPattern 사용
   - 실패/부재 시 graceful fallback
   ========================= */
async function loadRowDataOnce(row) {
  if (row._detailData) return row._detailData; // 이미 로드된 경우

  const id = row.dataset.id; // <div class="recipes_list" data-id="...">
  const ajaxPattern = window.ajaxPattern; // 예: "/api/activity/__ID__"
  if (id && typeof ajaxPattern === "string" && ajaxPattern.includes("__ID__")) {
    const url = ajaxPattern.replace("__ID__", id);
    try {
      const res = await fetch(url, { headers: { Accept: "application/json" } });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      row._detailData = data;
      return data;
    } catch (e) {
      console.error("[activity_history] fetch 실패:", e);
      // 실패 시 최소 구조 반환
      row._detailData = {
        point_earned: 0,
        travel_minutes: "-",
        steps: "-",
        calories_kcal: "-",
        ingredients: [],
      };
      return row._detailData;
    }
  } else {
    // demo 용: 페이지에 하드코딩된 텍스트에서 키 추출하거나 빈 데이터
    const name = row.querySelector(".menu_name")?.textContent.trim();
    row._detailData = {
      point_earned: 0,
      travel_minutes: "-",
      steps: "-",
      calories_kcal: "-",
      ingredients: [],
    };
    console.warn(
      "[activity_history] ajaxPattern/id 없음. 빈 데이터로 표시:",
      name
    );
    return row._detailData;
  }
}

/* =========================
   아코디언 열기/닫기
   ========================= */
async function closeRow(row) {
  if (busyRows.has(row)) return;
  busyRows.add(row);
  lockRow(row, true);

  try {
    const arrow = row.querySelector(".see-detail");
    const panel = row.querySelector(".activity-detail-inline");
    row.style.overflow = "hidden";

    if (panel) {
      panel.style.transition = `opacity ${DURATION}ms ease`;
      panel.style.opacity = "0";
    }

    const base = baseH.get(row) ?? row.offsetHeight;
    row.style.transition = `height ${DURATION}ms ease`;
    row.style.height = `${base}px`;

    if (arrow) {
      arrow.style.transition =
        "transform .2s ease, filter .2s ease, opacity .2s ease";
      arrow.style.transform = "none";
      arrow.style.filter = "";
      arrow.style.opacity = "0.45";
    }

    await Promise.all([
      onTransitionEnd(row, "height"),
      panel ? onTransitionEnd(panel, "opacity") : Promise.resolve(),
    ]);

    panel?.remove();
    row.style.flexWrap = "";
    row.style.overflow = "";
    row.classList.remove("open");
  } finally {
    busyRows.delete(row);
    lockRow(row, false);
    updateCTAVisibility();
  }
}

async function openRowWithDetail(row) {
  if (busyRows.has(row)) return;
  busyRows.add(row);
  lockRow(row, true);

  try {
    // 중복 제거
    row.querySelectorAll(".activity-detail-inline").forEach((n) => n.remove());

    if (!baseH.has(row)) baseH.set(row, row.offsetHeight);
    const start = baseH.get(row) ?? row.offsetHeight;

    row.style.height = `${start}px`;
    row.style.overflow = "hidden";
    row.style.flexWrap = "wrap";
    row.style.transition = `height ${DURATION}ms ease`;

    const name = row.querySelector(".menu_name")?.textContent.trim() || "";
    const dateText = row.querySelector(".menu_date")?.textContent.trim() || "";

    // ⚡ 처음 열 때만 fetch
    const data = await loadRowDataOnce(row);

    const panel = makeActivityPanel(name, dateText, data);
    row.appendChild(panel);

    const arrow = row.querySelector(".see-detail");
    if (arrow) {
      arrow.style.transition =
        "transform .2s ease, filter .2s ease, opacity .2s ease";
      arrow.style.transform = "rotate(90deg)";
      arrow.style.filter = "brightness(0)";
      arrow.style.opacity = "1";
    }

    requestAnimationFrame(() => {
      const extra = panel.scrollHeight + 10;
      row.style.height = `${start + extra}px`;
      panel.style.opacity = "1";
    });

    row.classList.add("open");

    setTimeout(() => {
      panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
      setTimeout(() => {
        if (row.classList.contains("open")) row.style.overflow = "";
      });
    }, 0);
  } finally {
    busyRows.delete(row);
    lockRow(row, false);
    updateCTAVisibility();
  }
}

/* =========================
   초기 바인딩
   ========================= */
document.addEventListener("DOMContentLoaded", () => {
  const listSet = document.querySelector(".list-set");
  if (listSet) {
    listSet.addEventListener("click", (e) => {
      const row = e.target.closest(".recipes_list");
      if (!row) return;

      if (row.classList.contains("open")) {
        closeRow(row);
      } else {
        openRowWithDetail(row);
      }
    });

    listSet.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      const row = e.target.closest(".recipes_list");
      if (!row) return;
      e.preventDefault();
      if (row.classList.contains("open")) closeRow(row);
      else openRowWithDetail(row);
    });
  }

  document.querySelector(".top-back")?.addEventListener("click", () => {
    document
      .querySelectorAll(".recipes_list.open")
      .forEach((row) => closeRow(row));
  });

  initRangeDropdown();
});
