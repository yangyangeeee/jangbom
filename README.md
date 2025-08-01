# jangbom


### 🔥Commit Message Convention

- **커밋 유형**
  - Init: 프로젝트 세팅
  - Feat: 새로운 기능 추가
  - Fix: 버그 수정
  - Design: UI&CSS 수정
  - Typing Error: 오타 수정
  - Docs: 문서 수정
  - Mod: 폴더 구조 이동 & 파일 이름 수정
  - Add: 파일 추가
  - Del: 파일 삭제
  - Refactor: 코드 리펙토링
  - Chore: 배포, 빌드 기타 작업
  - Merge: 브랜치 병합
    
- **형식**:  `커밋유형: 상세설명 (#이슈번호)`
- **예시**:
    - Init: 프로젝트 초기 세팅 (#1)
    - Feat: 로그인 페이지 개발 (#2)<br><br><br>


### 🌳Branch Convention
  - **브랜치 종류**

    - `init`: 프로젝트 세팅
    - `feat`: 새로운 기능 추가
    - `fix` : 버그 수정
    - `refactor` : 코드 리펙토링
      
- **형식**: 브랜치종류/#이슈번호/상세기능

- **예시**:

  - init/#1/프로젝트 세팅
  - fix/#2/로그인 화면 수정
  - feat/#3/메인 화면<br><br><br>
 
### 📜 Issue Convention
#### Issue Title 규칙

  - **태그 목록**:

    - Init: 프로젝트 세팅
    - Feat: 새로운 기능 추가
    - Fix : 버그 수정
    - Refactor : 코드 리펙토링
  - **형식**: [태그] 작업 요약

- 예시:

  - [Init] 프로젝트 초기 세팅
  - [Feat] Login 구현<br><br>

#### Issue Template
```
## 📄 About

해당 이슈에서 작업할 내용을 작성해주세요.

---

## ✅ To Do

해당 이슈와 관련된 할 일을 작성해주세요.  
할 일을 완료했다면 체크 표시로 기록해주세요.

- [ ] todo  
- [ ] todo  

---

## 🎨 Preview

작업하고자 하는 내용의 뷰를 첨부해주세요.
```

### 🔄 Pull Request Convention
#### PR Title 규칙

  - **태그 목록**:

    - Init: 프로젝트 세팅
    - Feat: 새로운 기능 추가
    - Fix : 버그 수정
    - Refactor : 코드 리펙토링
  - **형식**: [태그] 제목

- **예시**:

  - [Feat] login/logout 기능 구현
  - [Fix] login/logout 기능 수정<br><br>

 #### PR Template
```
### 📑 이슈 번호

- close #

### ✨️ 작업 내용

작업 내용을 간략히 설명해주세요.

### 💭 코멘트

코드 리뷰가 필요한 부분이나 궁금한 점을 자유롭게 남겨주세요!

### 📸 구현 결과

구현한 기능이 모두 결과물에 포함되도록 자유롭게 첨부해주세요.
```
