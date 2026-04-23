
# 🎥 MissAV 다운로더 웹 UI

**MissAV 웹 기반 다운로더**로, TrueNAS 및 Docker 환경에서 완벽하게 작동합니다.  
`curl_cffi`와 `yt-dlp`를 사용하여 ISP 차단(SNI) 및 Cloudflare의 강력한 봇 보호를 우회합니다.

## ✨ 기능

### 핵심 기능
- **웹 UI:** 브라우저에 URL만 입력하면 백그라운드에서 다운로드가 원활하게 실행됩니다.
- **실시간 진행률 표시:** 직관적인 게이지 바(%)로 다운로드 진행 상황을 모니터링합니다 — 터미널을 확인할 필요가 없습니다.
- **스마트 우회 로직:**
  - `curl_cffi`를 사용하여 최신 Chrome 브라우저를 모방, Cloudflare 봇 보호 및 CAPTCHA 우회
  - MissAV 미러 도메인을 자동으로 순회하며 접근 가능한 주소 찾기
- **완전한 VPN 호환성:** Gluetun과 같은 VPN 컨테이너 네트워크에 연결된 경우에도 완벽하게 작동, IP 제한을 올바르게 우회
- **향상된 안정성:** 긴 일본어/한국어 제목으로 인한 파일 시스템 저장 오류(`[Errno 36] File name too long`)를 방지하기 위해 파일명 자동 최적화
- **작업 취소 기능:** 목록에서 `삭제` 버튼을 클릭하여 백그라운드 다운로드 프로세스를 즉시 강제 종료(취소)

### 새로운 기능
- **🌍 다국어 지원:** 영어, 한국어, 일본어, 중국어(간체) 지원. 드롭다운 메뉴로 쉽게 언어 전환 가능
- **⚙️ 설정 관리:** 웹 UI에서 다운로드 디렉토리, 순차 모드, 다운로드 간격, 기본 화질, 미러 도메인 설정 가능
- **🔍 JAV 코드 변환:** JAV 코드(예: ABP-123)만 입력하면 자동으로 올바른 MissAV URL로 변환
- **📦 일괄 다운로드:** 여러 URL 또는 JAV 코드를 한 번에 추가하여 대량 다운로드
- **📁 파일 관리자:** 웹 인터페이스에서 직접 다운로드한 파일 탐색, 검색, 미리보기 및 삭제
- **📝 다운로드 로그:** 각 다운로드 작업별 로그 파일로 문제 해결 용이
- **⚡ 순차/병렬 모드:** 한 번에 하나씩 또는 여러 개를 동시에 다운로드하도록 선택 가능

## 🛠️ 설치 및 사용법

> ⚠️ **권장 사항:** 안전을 위해 VPN(예: Gluetun)과 함께 실행하세요.

### 1. `docker-compose.yml` 생성

VPN 네트워크에 다운로더 컨테이너를 연결합니다. (GitHub Container Registry 사용)

```yaml
version: '3'
services:
  missav-dlp-web:
    image: ghcr.io/nerdnam/missav-dlp-web:latest
    network_mode: "container:gluetun-vpn" # 선택 사항: VPN 컨테이너 사용 시
    # ports:
    #   - "5000:5000" # VPN을 사용하지 않는 경우에만 활성화
    volumes:
      - /path/to/your/downloads:/downloads
      - ./locales:/app/locales # 선택 사항: 사용자 정의 번역용
    restart: unless-stopped
```

### 2. Gluetun `docker-compose.yml`에 포트 추가

다운로더가 VPN 컨테이너에 연결되므로 **Gluetun 컨테이너 구성**에 외부 액세스 포트를 **반드시** 추가해야 합니다:

```yaml
services:
  gluetun-vpn:
    # ... (기존 Gluetun 설정) ...
    ports:
      - "58000:5000/tcp"  # 호스트 포트 58000을 컨테이너 포트 5000에 매핑
```

### 3. 웹 UI 접속

컨테이너를 시작한 후 브라우저를 열고 다음 주소로 이동하세요:

```
http://[YOUR_NAS_OR_SERVER_IP]:58000
```

## 📁 프로젝트 구조

```
missav-dlp-web/
├── app.py                    # 메인 Flask 애플리케이션
├── .settings.json            # 사용자 설정 (자동 생성)
├── downloads/                # 다운로드된 비디오
├── logs/                     # 다운로드 작업 로그
├── locales/                  # 언어 파일
│   ├── en.json              # 영어
│   ├── ko.json              # 한국어
│   ├── ja.json              # 일본어
│   └── zh.json              # 중국어 (간체)
├── templates/                # 웹 인터페이스
│   ├── index.html           # 메인 페이지
│   ├── script.js            # 프론트엔드 로직
│   └── style.css            # 스타일
├── app_files/               # 백엔드 모듈
│   ├── config_manager.py    # 설정 관리
│   ├── download_manager.py  # 다운로드 큐 및 yt-dlp
│   ├── extractor.py         # 커스텀 MissAV 추출기
│   ├── language.py          # 다국어 지원
│   ├── paths.py             # 경로 관리
│   └── utils.py             # 헬퍼 함수
└── ffmpeg/                  # FFmpeg 바이너리 (선택 사항)
    └── bin/
        └── ffmpeg.exe
```

## 🌍 언어 지원

애플리케이션은 여러 언어를 지원하며 언제든지 전환할 수 있습니다:

| 언어 | 코드 | 상태 |
|------|------|--------|
| English | en | ✅ 완료 |
| 한국어 | ko | ✅ 완료 |
| 日本語 (Japanese) | ja | ✅ 완료 |
| 中文 (Chinese Simplified) | zh | ✅ 완료 |

새 언어를 추가하려면:
1. `locales/` 폴더에 새 JSON 파일 생성 (예: `fr.json`)
2. `en.json`의 구조를 복사하여 값 번역
3. `templates/index.html`의 드롭다운에 언어 코드 추가

## ⚙️ 설정

설정은 `.settings.json`에 저장되며 웹 UI를 통해 수정할 수 있습니다:

| 설정 | 설명 | 기본값 |
|------|------|--------|
| 다운로드 디렉토리 | 비디오 저장 위치 | `./downloads` |
| 순차 모드 | 한 번에 하나의 비디오 다운로드 | `true` |
| 다운로드 간격 | 다운로드 사이 대기 시간(초) | `3` |
| 기본 화질 | 다운로드할 최대 해상도 | `best` |
| 미러 도메인 | 대체용 MissAV 미러 도메인 | `missav.ai`, `missav.net` 등 |

### 고급 설정

`.settings.json`을 직접 편집할 수도 있습니다:

```json
{
  "max_concurrent": 1,
  "filename_template": "[%(id)s] %(title).60s.%(ext)s",
  "spoofdpi_enabled": true,
  "video_quality": "best",
  "mirrors": ["missav.ai", "missav.net", "missav123.com", "missav.com", "missav.ws"],
  "download_dir": "./downloads",
  "delay_between_downloads": 3,
  "max_retries": 3,
  "sequential_mode": true
}
```

## 🚀 사용 예시

### 단일 다운로드
1. MissAV URL 또는 JAV 코드 입력 (예: `ABP-123`)
2. "정보 가져오기" 클릭하여 비디오 세부 정보 확인
3. 화질 선택
4. "지금 다운로드" 또는 "큐에 추가" 클릭

### 일괄 다운로드
1. "일괄 추가" 클릭
2. 여러 URL 또는 JAV 코드 입력 (한 줄에 하나)
3. "모두 큐에 추가" 클릭

### 다운로드 관리
- 큐에서 실시간 진행 상황 확인
- ✕ 버튼으로 개별 다운로드 취소
- 완료된 작업 정리 또는 대기 중인 큐 지우기
- 다운로드 섹션에서 다운로드된 파일 탐색 및 관리

## 🔧 문제 해결

| 문제 | 해결책 |
|------|--------|
| 웹 UI에 접근할 수 없음 | Gluetun 컨테이너에서 포트가 올바르게 노출되었는지 확인 |
| 다운로드가 멈춤 | VPN 연결 및 네트워크 모드 구성 확인 |
| 파일 이름 오류 | 도구가 자동으로 파일명을 단축함 — 다운로드 경로가 쓰기 가능한지 확인 |
| 설정이 저장되지 않음 | 루트 디렉토리의 `.settings.json` 쓰기 권한 확인 |
| 언어가 변경되지 않음 | 브라우저 캐시 지우기 또는 `locales/` 폴더가 올바르게 마운트되었는지 확인 |
| JAV 코드가 작동하지 않음 | 형식이 올바른지 확인 (예: `ABP-123`, `SSIS-456`) |

## 🐳 Docker 빌드

로컬에서 Docker 이미지를 빌드하려면:

```bash
docker build -t missav-dlp-web .
docker run -p 5000:5000 -v $(pwd)/downloads:/downloads missav-dlp-web
```

## 📦 요구 사항

- Docker 및 Docker Compose
- (선택 사항) Gluetun 또는 OpenVPN/WireGuard 컨테이너
- Python 3.8+ (로컬 개발용)
- FFmpeg (비디오 병합용)

### 로컬 개발

```bash
# 의존성 설치
pip install -r requirements.txt

# 애플리케이션 실행
python app.py

# http://localhost:5000 에서 접속
```

## 🔄 API 엔드포인트

애플리케이션은 REST API 엔드포인트를 제공합니다:

| 엔드포인트 | 메서드 | 설명 |
|----------|--------|------|
| `/api/info` | POST | 비디오 정보 가져오기 |
| `/api/download` | POST | 단일 다운로드 추가 |
| `/api/batch` | POST | 여러 다운로드 추가 |
| `/api/tasks` | GET | 모든 작업 목록 |
| `/api/tasks/<id>` | DELETE | 작업 취소 |
| `/api/queue/stats` | GET | 큐 통계 |
| `/api/settings` | GET/PUT | 설정 가져오기/업데이트 |
| `/api/files` | GET | 다운로드된 파일 목록 |
| `/api/language` | GET/POST | 언어 가져오기/설정 |

## ⚠️ 면책 조항

이 도구는 **개인용**으로만 사용됩니다. 사용자는 저작권 준수 및 다운로드한 콘텐츠로 인해 발생하는 모든 결과에 대해 전적인 책임을 집니다.

## 📄 라이선스

MIT 라이선스 - [LICENSE](LICENSE) 파일 참조

## 🙏 감사의 말

이 프로젝트는 **[nerdnam](https://github.com/nerdnam)** 및 원본 **[missav-dlp-web](https://github.com/nerdnam/missav-dlp-web)** 저장소의 훌륭한 작업을 기반으로 합니다.

### 원본 저장소
- **작성자:** nerdnam
- **저장소:** [github.com/nerdnam/missav-dlp-web](https://github.com/nerdnam/missav-dlp-web)
- **라이선스:** 라이선스 조건은 원본 저장소를 확인하세요

### 사용/적용된 주요 기능
- Cloudflare 우회를 위한 `curl_cffi` + `yt-dlp` 통합
- 미러 도메인 순회 로직
- VPN 호환성 (Gluetun)
- 실시간 진행률을 갖춘 웹 기반 다운로드 UI

### 추가 개선 사항
- 다국어 지원 (4개 언어)
- 설정 관리 UI
- JAV 코드 변환기
- 일괄 다운로드 기능
- 검색 및 미리보기가 있는 파일 관리자
- 작업별 로깅
- 순차/병렬 다운로드 모드

### 감사합니다
- 원본 프로젝트의 모든 기여자
- `yt-dlp` 및 `curl_cffi`의 오픈 소스 커뮤니티
- 현지화에 도움을 주신 번역자들

---

## 📝 변경 로그

### 버전 3.0
- 다국어 지원 추가 (EN, KO, JA, ZH)
- 설정 관리 UI 추가
- JAV 코드 변환 추가
- 일괄 다운로드 기능 추가
- 검색 기능이 있는 파일 관리자 추가
- 작업별 로깅 추가
- 코드를 `app_files/` 모듈로 재구성
- 폴더 구조 수정 (downloads/logs가 루트에 위치)

### 버전 2.0
- nerdnam의 작업을 기반으로 한 최초 릴리스
- 기본 다운로드 기능
- 실시간 진행률 표시
- curl_cffi를 사용한 Cloudflare 우회
