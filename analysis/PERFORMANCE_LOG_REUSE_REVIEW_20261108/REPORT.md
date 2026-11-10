# 이전 실행 성능 로그 재사용 검토

검토 ID: `EXPLR-PERFORMANCE-LOG-REUSE-20261108`. 기존 JSON/JSONL/특징 CSV만 읽었다. 새 촬영·원본 영상 열람·모델 로드/학습·실시간 시험·새 벤치마크는 하지 않았다. 현재 FS3 T0의 분류 조건, 공식8조합/B6, IRB HOLD 및 Patch8 실행 보류는 유지한다.

**결론: 이전 지연·FPS·CPU·RAM은 당시 geometry probe의 참고 관측으로 재사용할 수 있다. 현재 7특징 SVM의 전체 파이프라인 성능으로 대체할 수는 없다.** 최근120구간의 저장 속도·특징 유효율과 촬영 후 모델 추론 비용도 서로 다른 측정이다.

## 자료 선택과 제외

- `analysis/ENGINEERING_ONLY_*/**/host_timing.json` 29개를 조사했다. SHA-256 기준 서로 다른 내용은19개이며 복사본10개를 독립 반복으로 세지 않았다. 이 검색 범위 밖의 모든 과거 자료를 전수 검토했다는 뜻은 아니다.
- 실제 장치 실행 로그16건의 event journal hash·내장 events·timing 일치, 원시 stage 이벤트의 percentile·resource percentile·FPS 산술을 확인했다. 초기 B의 짧은/중단 실행4건은 대표 성능에서 제외했다.
- 합성 예제1건과 0.3초 가상시계 검증 fixture2건은 실제 하드웨어 성능에서 제외했다. 이들의 복사본도 제외했다.
- 대표 반복 관측은 `ENGINEERING_ONLY_C_FINAL_20261105_152742`의 UI3회/HEADLESS3회, 각90초다. B_RETRY의90초3회는 이전 설정의 보조 기록이며 대표 반복과 합쳐 평균내지 않았다.
- 짧지만 정밀한 관측은 `ENGINEERING_ONLY_C6_LIVE_20261105_170905`의 UI/HEADLESS 각25초다. QPC 진단 원시값과 frame journal hash를 확인했다. 예열 제외0프레임이며 각각 한 번의 실행이므로 안정 상태·반복 개선 효과를 주장하지 않는다.
- 실제 실행16건 모두 `h9_enabled=false`, 성공한 H9 분류 추론0회다. CSV/callback도 비활성인 probe 실행으로 최근120구간 수집이나 FS3 SVM 배포 실행과 다르다. 특징 유효 여부도 이 로그만으로 확정할 수 없다.

원본에는 장치 일련번호·로컬 경로가 있으므로 복사하지 않았다. 경로/hash·집계 검증 결과는 `local_private/review.json`에만 저장했다.

## 재사용 가능한 90초 반복 관측

입력 설정은 D455 RGB1280×720/Depth848×480, 각각15FPS다. Python3.12.10, MediaPipe1.0.1, pyrealsense2 2.58.4.10922, Windows11, 논리CPU28개인 당시 PC의 관측이다. 다른 저사양 장치의 성능을 입증하지 않는다.

|실행|처리 FPS|수신→처리 완료 p95 ms|수신→화면 제출 p95 ms|CPU p95 %¹|RSS 관측 최고 MiB|
|---|---:|---:|---:|---:|---:|
|UI01|14.856|63|47|31.25|304.01|
|UI02|14.878|63|47|28.53|300.13|
|UI03|14.856|63|47|31.25|302.37|
|HEADLESS01|14.842|47|N/A|31.25|280.11|
|HEADLESS02|14.864|47|N/A|30.77|281.95|
|HEADLESS03|14.853|46|N/A|29.22|280.67|

¹CPU는 프로세스 기준 코어 하나=100%다. 전체 논리CPU 용량 기준으로 나누면 UI p95는1.02~1.12%, HEADLESS는1.04~1.12%다. 시스템 전체 CPU 사용률이 아니며 GPU/외부 프로세스 비용도 포함하지 않는다.

FPS는 예열을 포함한 전체 stream의 완료 frameset 수/실제 시간이다. 지연의 frame.processing은 앞150개 처리 프레임을 제외한 값이다. 둘의 측정 구간이 같지 않음을 유지한다. 처리 지연은 수신 직후부터 align·변환·Pose/Face·Depth geometry·UI/키 처리 등을 거쳐 loop 완료까지이며 수신 전 대기/촬영/모델 집계·SVM 추론/물리 화면 표시는 포함하지 않는다. UI 제출 지연은 key wait보다 앞에서 끝나므로 처리 완료 지연과 다르다.

이 로그의 monotonic clock은 별도 QPC 기록에서 `GetTickCount64`, 해상도15.625ms로 확인됐다. 0/15/16ms가 반복되므로 짧은 단계 연산의 정밀 비교에는 사용하지 않는다. 전체 p95도 이 시간 양자화를 가진 역사적 관측이다. 단계 p95를 합해 전체 지연을 만들지 않는다.

RSS 최고는 약1초 간격 stream 샘플 중 최고다. OS 누적 peak working set도 별도 보존돼 있으며 UI304.22~305.90MiB, HEADLESS282.52~284.10MiB다. Private Bytes 관측 최고는 UI999.20~1003.14MiB, HEADLESS983.01~984.52MiB로, RSS와 다른 메모리량이며 실제 상주 RAM으로 합산하지 않는다. 장시간 메모리 안정성은90초 기록으로 판단하지 않는다.

## QPC 고해상도 보조 관측

`time.perf_counter_ns` / QueryPerformanceCounter, 기록된 해상도100ns다. 각25초, 완료365프레임, 예열 제외 없음. 아래 지연은 원시 duration에서 percentile을 다시 계산해 일치 확인했다.

|항목|UI|HEADLESS|
|---|---:|---:|
|전체 stream 처리 frameset/s|14.600|14.591|
|수신→처리 완료 p50 ms|43.3953|25.6221|
|수신→처리 완료 p95 ms|52.1899|26.6113|
|수신→UI 제출 p95 ms|37.6287|N/A|
|Pose p95 ms|18.7922|19.4723|
|Face p95 ms|1.6995|1.7335|
|Depth geometry p95 ms|0.4864|0.4588|
|align p95 ms|4.1969|4.1829|
|UI build+submit p95 ms|11.5713|N/A|
|key wait p95 ms|17.5399|N/A|

이 두 실행에서는 Pose와 화면 구성·키 대기가 다음 병목 점검 후보가 된다. 다만 검출 성공률이나 유효한 인체 특징의 support를 보여주는 로그는 아니므로 Depth geometry의 짧은 시간을 모든 자세·검출 조건에 일반화하지 않는다. UI/HEADLESS는 서로 다른 시각의 단발 실행이고 관측기 자체의 비용도 포함하므로 두 실행의 차이를 최적화 효과량으로 취급하지 않는다.

UI의 RSS 샘플 최고는292.08MiB, CPU p95는34.49%(1core=100%)다. HEADLESS는274.73MiB, 29.99%다. QPC raw/event를 메모리에 유지하는 진단 실행이므로 진단 없는 배포판 RAM 기준으로 대체하지 않는다.

## 지표별 재사용 판단

|요청 지표|판단|기존 자료로 확인 가능한 범위와 부족한 부분|
|---|---|---|
|전체 파이프라인 지연 p95|부분 재사용|probe의 수신 후 처리·UI 제출까지. 현재 FS3의10초 집계·SVM 판정까지의 전체값과 sensor-to-screen은 미측정|
|실제 처리 FPS|부분 재사용|위 frameset loop 완료율. 고유한 새 RGB 처리 FPS·유효 특징 FPS와 다름|
|유효 처리율|저장된120구간에서 재사용|선정120구간의18000개 저장 프레임 중17945개에서 FS3의7열이 finite, 99.6944%. 수신 전 누락·준비/전환·제외7구간은 분모에 없음|
|CPU 사용률|부분 재사용|당시 probe 프로세스 값. 현재 SVM 전체 경로·시스템 전체·다른 장치는 미측정|
|RAM·최고치|부분 재사용|당시 프로세스 RSS/Private/OS peak. 모델 전용 RAM이나 장시간 안정성이 아님|
|프레임 누락률|NOT_MEASURED 유지|composite 번호 gap을 RGB/Depth 누락률로 바꾸지 않음. 중복·clock/profile 경계와 센서별 identity 확인 필요|
|GPU 사용률|NOT_MEASURED|사용률 로그 없음. GPU 미사용의 확증이나0%라는 결과로 바꾸지 않음|

프레임 번호 주의: C_FINAL의 HEADLESS3회에는 composite 번호 중복60/71/88건이 있다. 25초 C6의 raw 메타데이터에서도 UI는 RGB 중복0/Depth 중복1건, HEADLESS는 RGB 중복25/Depth 중복23건이다(종료 경계의1회 수신 포함). SDK 동기화·child 재사용과 실제 입력 누락을 분리하지 못한 채 누락률을 만들지 않는다. 기존 frame summary도 sensor_missing_rate=NOT_MEASURED다. EXP-006의 동일 stream 연속 번호·중복/리셋/출처 불명 시 NOT_MEASURED 조건을 변경하지 않는다.

최근120구간의 각10초에150개 저장 행이 있으므로 저장 속도는15행/초다. 이것만으로 카메라가 생성한 전체 프레임의 무누락이나 현재 SVM의 실시간 처리 성공을 증명하지 않는다. 모든 구간이 분석 적격인 것과 모든 저장 프레임의 특징이 유효한 것도 구분한다.

촬영 후 별도로 측정한7특징 SVM 비용은 [기존 REPORT](../PILOT120_SEVEN_CANDIDATE_REVIEW_20261108/REPORT.md)를 재사용한다. 표준화+predict p95=0.1290ms이며 학습60구간 모델의720회 추론을 pool한 값이다. 위 probe p95에 더해 미측정 전체 p95를 만들지 않는다. 기존 저장 결과의`--verify`만 재실행했으며 재학습·재벤치마크는 하지 않았다.

## 다음에 필요한 범위와 검증

재촬영 전에 기존 계측을 FS3의 실제 특징 생성→고정 집계→scaler/SVM까지 연결할 수 있는지 코드를 확인한다. 이후 필요한 실행 계측만 별도로 다룬다. 고해상도 동일 host clock, 센서별 identity, 특징 성공/실패 사유와 동일 측정 구간의 FPS/CPU/RAM을 갖춘다. 창 길이·유효 조건·모델 출력을 변경해 빨라진 것으로 취급하지 않는다. 정식 Patch8 실행이나 IRB 대상 촬영을 이 검토에서 시작하지 않는다.

검증은 실제 로그16건의 journal SHA/내장 event 일치·stage/resource percentile·FPS 재계산, QPC2건의 raw percentile·journal SHA, 120구간의 source hash/18000행/17945개 유효 행, 기존7특징 비교의 저장 결과 verify를 수행했다. 코드 변경이 없어 신규 unit test·전체 회귀는 실행하지 않았다. 생성물은 이 REPORT와 로컬 전용`local_private/review.json`뿐이다. 기존 파일 덮어쓰기·Stage·Commit·Push는 하지 않았다.
