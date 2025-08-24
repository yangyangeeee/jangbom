"use strict";

// 유틸
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

// 상세 모달
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
  const lis = panel.querySelectorAll("ul > li");
  if (lis.length) lis[lis.length - 1].style.borderBottom = "0";
  return panel;
}

// 하단 버튼 모달
let fridgeCta = null;
function ensureCTA() {
  if (fridgeCta) return fridgeCta;
  const parent = document.querySelector(".box") || document.body;

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
    console.log("[CTA] 기존 식재료로 요리법 찾기");
  });

  fridgeCta.append(msg, btn);

  const bottomNav = document.querySelector(".bottom-nav");
  if (bottomNav && bottomNav.parentElement === parent) {
    parent.insertBefore(fridgeCta, bottomNav);
  } else {
    parent.appendChild(fridgeCta);
  }
  return fridgeCta;
}
function showCTA() {
  ensureCTA().style.display = "block";
}
function hideCTA() {
  if (fridgeCta) fridgeCta.style.display = "none";
}
function updateCTAVisibility() {
  document.querySelector(".recipes_list.open") ? showCTA() : hideCTA();
}

// 데이터 로딩
async function loadRowDataOnce(row) {
  if (row._detailData) return row._detailData;

  const id = row.dataset.id;
  const ajaxPattern = window.ajaxPattern;
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

// 아코디언 열기/닫기
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
    row.querySelectorAll(".activity-detail-inline").forEach((n) => n.remove());

    if (!baseH.has(row)) baseH.set(row, row.offsetHeight);
    const start = baseH.get(row) ?? row.offsetHeight;

    row.style.height = `${start}px`;
    row.style.overflow = "hidden";
    row.style.flexWrap = "wrap";
    row.style.transition = `height ${DURATION}ms ease`;

    const name = row.querySelector(".menu_name")?.textContent.trim() || "";
    const dateText = row.querySelector(".menu_date")?.textContent.trim() || "";
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

// 초기 설정
document.addEventListener("DOMContentLoaded", () => {
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

  const parseDate = (str) => {
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
    let ts = el.dataset.ts ? Number(el.dataset.ts) : NaN;
    if (Number.isNaN(ts)) {
      ts = parseDate(el.querySelector(".menu_date")?.textContent);
      el.dataset.ts = String(ts);
    }
    return ts;
  };

  items.forEach((el, i) => (el._idx = i));

// 범위 드롭다운
  const onDocClick = (e) => {
    if (e.target.closest(".range-dropdown")) return;
    closeMenu();
  };
  const onEscClose = (e) => {
    if (e.key === "Escape") closeMenu();
  };
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
  rangeBtn.addEventListener("click", toggleMenu);

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
        return 0;
      default:
        return 0;
    }
    return since.getTime();
  };

  const applyRangeFilter = (value) => {
    const sinceTs = calcSince(value);
    items.forEach((el) => {
      const ts = getTime(el);
      const visible = value === "all" ? true : ts >= sinceTs;
      el.style.display = visible ? "" : "none";
    });
  };

  const selectRange = (li) => {
    rangeItems.forEach((el) => {
      const on = el === li;
      el.classList.toggle("is-selected", on);
      el.setAttribute("aria-selected", on ? "true" : "false");
    });
    rangeBtn.childNodes[0].nodeValue = (li.textContent || "").trim() + " ";
    rangeBtn.dataset.value = li.dataset.value || "";
    applyRangeFilter(li.dataset.value || "all");
    closeMenu();
  };

  rangeItems.forEach((li) =>
    li.addEventListener("click", () => selectRange(li))
  );

  const initialRange =
    rangeItems.find((el) => el.classList.contains("is-selected")) ||
    rangeItems[0];
  if (initialRange) selectRange(initialRange);

// 최신순/가나다순 정렬
  const setActiveTab = (btn) => {
    [latestTab, alphaTab].forEach((el) => {
      const on = el === btn;
      el.classList.toggle("is-active", on);
      el.classList.toggle("on", on);              // ✅ 동그라미/강조용 클래스도 동기화
      el.setAttribute("aria-selected", on ? "true" : "false");
    });
  };

  const sortList = (mode) => {
    const visible = items.filter((el) => el.style.display !== "none");
    const hidden = items.filter((el) => el.style.display === "none");

    const sorted = visible.slice().sort((a, b) => {
      if (mode === "alpha") {
        return getTitle(a).localeCompare(getTitle(b), "ko", {
          sensitivity: "base",
          numeric: true,
        });
      }
      return getTime(b) - getTime(a); // 최신순
    });

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

  setActiveTab(latestTab);
  sortList("latest");

// 리스트 토글(열기/닫기) 바인딩
  const listSet = listWrap;
  if (listSet) {
    listSet.addEventListener("click", (e) => {
      const row = e.target.closest(".recipes_list");
      if (!row) return;
      row.classList.contains("open") ? closeRow(row) : openRowWithDetail(row);
    });

    listSet.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      const row = e.target.closest(".recipes_list");
      if (!row) return;
      e.preventDefault();
      row.classList.contains("open") ? closeRow(row) : openRowWithDetail(row);
    });
  }

  document.querySelector(".top-back")?.addEventListener("click", () => {
    document
      .querySelectorAll(".recipes_list.open")
      .forEach((row) => closeRow(row));
  });

  if (typeof initRangeDropdown === "function") {
    initRangeDropdown();
  }
});
