# 🚌 Incheon Bus Notifier

인천광역시 버스 Open API로 특정 정류장의 실시간 도착 정보를 조회하고,
조건 충족 시 카카오톡 "나에게 보내기"로 알림을 보내는 개인용 서비스.

> 개인 학습 및 자동화 목적. 상업적 용도로 사용하지 않습니다.

## 기능

- 특정 정류장의 실시간 버스 도착 정보 조회 (기본 60초 주기)
- 특정 노선만 필터링
- 도착 n분 이하 / 남은 정류장 n개 이하 조건 알림
- 동일 차량 중복 알림 방지 (SQLite + TTL)
- 런타임 설정 변경 (`POST /config`)

## 구조

```
app/
├── api/            # FastAPI 라우트 (/health, /arrival, /notify/test, /config)
├── services/       # bus / kakao / notify / scheduler
├── repositories/   # 중복 방지 저장소 (SQLite)
├── models/         # 도메인 모델
├── config/         # pydantic-settings 설정
├── utils/          # loguru 로깅
├── container.py    # DI 컨테이너
└── main.py         # FastAPI 진입점
```

## 설치

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt   # 실행만 하려면 requirements.txt
```

## 설정

```bash
cp config.example.yaml config.yaml
```

`config.yaml`을 채우세요. 비밀 값(서비스 키, 카카오 토큰)은 환경변수로 주입할 수 있고, 이 값이 파일보다 우선합니다.

```bash
export BUS_API__SERVICE_KEY="발급받은_서비스키"
export KAKAO__ACCESS_TOKEN="카카오_액세스_토큰"
```

- `bus_api.use_mock: true` — 실제 API 없이 샘플 데이터로 동작 확인
- `kakao.access_token`이 비어 있으면 실제 발송 대신 로그로만 출력(dry-run)

## 실행

```bash
python -m app                      # config.yaml 의 host/port(기본 8010) 사용
# 또는 개발 중 자동 리로드:
uvicorn app.main:app --reload --port 8010
```

- 노선 검색 + 노선도 화면: **http://localhost:8010/**
- Swagger UI: **http://localhost:8010/docs**
- `GET  /health`      상태 확인
- `GET  /api/routes?no=1300`            노선번호 검색(→ ROUTEID/기점·종점)
- `GET  /api/routes/{routeId}/stops`    경유 정류소(노선도, 방향별)
- `GET  /stops`       감시 정류소 목록
- `GET  /arrival`     정류소별 도착 예정 버스
- `POST /notify/test` 테스트 알림 발송
- `POST /config`      런타임 설정 변경

```bash
curl localhost:8010/health
curl localhost:8010/stops
curl localhost:8010/arrival
curl -X POST localhost:8010/notify/test
curl -X POST localhost:8010/config -H 'Content-Type: application/json' \
  -d '{"notify_minutes": 5, "check_interval": 30}'
```

## 테스트

```bash
pytest
```

## Docker

```bash
docker build -t bus-notifier .
docker run --rm -p 8010:8010 \
  -e INCHEON_API__SERVICE_KEY="..." \
  -e SEOUL_API__SERVICE_KEY="..." \
  -e KAKAO__ACCESS_TOKEN="..." \
  bus-notifier
```

## 인천 버스 도착정보 API 준비

실제 도착정보를 받으려면 data.go.kr에서 **버스도착정보 서비스 활용신청**이 필요합니다.

- 서비스: `busArrivalService` / 오퍼레이션: `getAllRouteBusArrivalList`
- 요청 URL: `https://apis.data.go.kr/6280000/busArrivalService/getAllRouteBusArrivalList`
- 정류소 파라미터명: `bstopId` (= `station_id`)
- 응답: XML (`ARRIVALESTIMATETIME`(초), `REST_STOP_COUNT`, `BUSID`, `ROUTEID`, `CONGESTION` 등)

> ⚠️ **주의 1** — 노선번호(`busRouteService`)와 도착정보(`busArrivalService`)는 **별도 서비스**입니다.
> 노선정보 키만 승인된 상태에서 도착정보를 호출하면 `Forbidden`이 반환됩니다.
> 각 서비스를 개별적으로 활용신청하세요.
>
> ⚠️ **주의 2** — 도착정보 응답은 노선을 사람이 읽는 번호("17")가 아니라 **`ROUTEID`(내부 고유번호)**
> 로 반환합니다. 특정 노선만 필터링하려면 `config.yaml`의 `routes`에 ROUTEID를 넣으세요.
> (ROUTEID는 `busRouteService`로 노선번호→ROUTEID 매핑해 확인 — 향후 자동화 과제)

승인 및 정류소 ID 확인 후 `config.yaml`에서 `bus_api.use_mock: false`로 변경하면 실 데이터로 동작합니다.

## 카카오 "나에게 보내기" 토큰

1. [Kakao Developers](https://developers.kakao.com)에서 앱 생성
2. 카카오 로그인 활성화 + `talk_message` 동의항목 설정
3. 사용자 액세스 토큰 발급 (scope: `talk_message`)
4. `KAKAO__ACCESS_TOKEN`으로 주입

> 액세스 토큰은 만료되므로 장기 운영 시 refresh token 갱신 로직이 필요합니다(향후 과제).

## 향후 기능

- 여러 정류장/노선, 출퇴근 스케줄
- Slack / Discord / Telegram 알림
- 카카오 토큰 자동 갱신
- 웹 관리 화면, Grafana 모니터링
