# AIoT 프로젝트 부품 리스트

## 기준
본 부품 목록은 `Research Protocol v1.0` 기준으로 **Gate 0~4 Preliminary Experiment를 수행하는 데 필요한 최소·권장 구성**을 정리한 것이다.

핵심 원칙은 다음과 같다.

- 불필요한 기능을 추가하지 않는다.
- AIoT Monitoring Node의 전력과 Motion Testbed의 전력을 분리한다.
- 반복 가능하고 통제 가능한 Physical Event를 만들 수 있어야 한다.
- Gate 0의 측정 유효성 검증이 가능해야 한다.
- 아직 구매 전인 부품은 Candidate Hardware로 관리한다.

---

# 1. 1차 구매 — 필수 부품

| 부품 | 수량 | 권장 후보 | 역할 | 우선순위 |
|---|---:|---|---|---|
| **ESP32-S3 개발보드** | **2** | ESP32-S3-DevKitC-1-N8R8 | AIoT Node / TinyML / Wi-Fi / MQTT | **필수** |
| **6축 IMU 모듈** | 1~2 | ICM-42688-P Breakout | 진동·Motion 데이터 취득 | **필수** |
| **전력 측정 모듈** | 1~2 | INA226 Breakout | ESP32+Sensor Node Energy 측정 | **필수** |
| **Stepper Motor** | 1 | NEMA17-class | 반복 Motion Workload | **필수** |
| **Stepper Driver** | 2 | TMC2209 Carrier | NEMA17 구동 / 예비 포함 | **필수** |
| **반복 이동 구조** | 1 set | GT2 Belt 또는 소형 Linear Stage | 반복 가능한 Physical Event 생성 | **필수** |
| **12V Motor 전원** | 1 | 충분한 전류 용량의 DC PSU | Stepper 전원 | **필수** |
| **별도 5V Node 전원** | 1 | 안정화 5V PSU/DC-DC | ESP32 측정용 전원 | **필수** |
| **Wi-Fi AP/Router** | 1 | 기존 공유기 사용 가능 | MQTT Network | **필수** |
| **Raspberry Pi / Linux 장치** | 1 | 기존 장비 사용 가능 | Mosquitto + Logger | **필수** |
| **PC/Mac** | 1 | 기존 장비 | AI Training / 분석 | **필수** |

---

# 2. ESP32-S3

## 권장 후보

**ESP32-S3-DevKitC-1-N8R8**

권장 이유:

- ESP32-S3
- 8 MB Flash
- 8 MB PSRAM
- Wi-Fi
- TinyML/TFLite Micro 실험에 적합
- 센서 취득 + AI inference + MQTT를 하나의 Node에서 처리 가능

## 권장 수량

**2개**

용도:

```text
Board 1
→ Actual Experiment Node

Board 2
→ Development / Debug / Spare
```

멀티노드 실험을 위한 수량이 아니라 개발 안정성을 위한 예비 보드다.

---

# 3. IMU

## 권장 후보

**ICM-42688-P Breakout**

주요 역할:

- 3축 Accelerometer
- 3축 Gyroscope
- Vibration / Motion Signal 측정

## 구매 형태

Bare IC가 아니라:

> **Breakout Board / Module 형태**

를 권장한다.

## 수량

- 최소: **1개**
- 권장: **2개**

두 번째 IMU는 예비 또는 Reference Sensor가 필요할 때 사용할 수 있다.

---

# 4. INA226 Power Monitor

본 연구의 핵심 Metric 중 하나는 Monitoring Node Energy다.

Energy는 다음과 같이 계산한다.

\[
E = \int V(t)I(t)dt
\]

따라서 전력 측정 모듈이 필요하다.

## 권장 후보

**INA226 Breakout**

## 측정 대상

```text
5V Node Supply
      ↓
    INA226
      ↓
ESP32-S3
+
ICM-42688
+
Local Node Electronics
```

## 측정 대상에서 제외

```text
NEMA17
Stepper Driver
Fault Actuator
Raspberry Pi
Wi-Fi AP
```

Motor/Testbed 전력을 Node Energy와 섞으면 안 된다.

---

# 5. 전원 구성

전원은 반드시 두 계통으로 분리한다.

## Motion Testbed Power

```text
12V PSU
   ↓
TMC2209
   ↓
NEMA17
```

## AIoT Monitoring Node Power

```text
5V Regulated Supply
       ↓
     INA226
       ↓
ESP32-S3 + IMU
```

## 이유

Motor Power가 AIoT Node보다 훨씬 클 가능성이 높기 때문이다.

예:

```text
Sampling 변화
→ Node에서 작은 Energy 차이 발생

Motor Power Variation
→ 훨씬 큰 전력 변화
```

두 전력을 섞으면 Sampling/Communication Adaptation의 Energy 효과를 정확히 측정하기 어렵다.

---

# 6. Motion Testbed 구성

연구에 고가의 Precision Stage는 필요하지 않다.

중요한 조건은:

> **같은 Motion과 같은 Disturbance를 반복해서 생성할 수 있는가**

이다.

## 권장 기본 구조

```text
NEMA17
   ↓
GT2 Pulley
   ↓
GT2 Belt
   ↓
Carriage
   ↓
Linear Rail
```

## 필요한 부품 예

| 부품 | 수량 |
|---|---:|
| NEMA17 | 1 |
| TMC2209 | 1 |
| GT2 Pulley | 1~2 |
| GT2 Belt | 1 |
| Idler Pulley | 1 |
| Linear Rail | 1 |
| Carriage Mounting Plate | 1 |
| Motor Bracket | 1 |
| Idler Bracket | 1 |
| 볼트/너트/와셔 | Set |

저렴한 소형 Linear Stage Kit가 있다면 완제품 Kit를 사용하는 것도 가능하다.

---

# 7. Stepper Driver

## 권장 후보

**TMC2209 Carrier**

초기에는 복잡한 기능을 사용할 필요가 없다.

기본 구성:

```text
ESP32 GPIO
   ↓
STEP
DIR
ENABLE
   ↓
TMC2209
   ↓
NEMA17
```

## 수량

**2개 권장**

- 실제 사용: 1
- 예비: 1

Stepper Driver는 배선 및 전류설정 실수로 손상될 가능성이 있어 예비품이 유용하다.

---

# 8. Fault / Severity 생성 부품

연구에서는 다음처럼 여러 강도의 Physical Event를 반복해서 만들 수 있어야 한다.

```text
Normal
Low
Medium
High
Critical
```

손으로 모터나 Belt를 직접 잡는 방식은 재현성이 낮으므로 권장하지 않는다.

## 가능한 방법

- 조절 가능한 마찰 구조
- Spring Load
- Weight
- Belt Tension 변화

## 자동화 권장안

작은 Servo를 사용해 일정한 저항을 가하는 구조.

예:

```text
Servo
 ↓
Friction Pad
 ↓
Belt / Carriage
```

## 권장 부품

- SG90 또는 MG90S급 Servo ×1

Servo 전력은 Monitoring Node Energy 측정에 포함하지 않는다.

---

# 9. Event Ground Truth용 부품

Gate 0에서는:

> **실제 Physical Event가 정확히 언제 시작되었는가**

를 확인해야 한다.

## 저비용 후보

- Limit Switch
- Photo Interrupter
- Hall Sensor

## 추가 후보

- Rotary Encoder
- Linear Encoder
- Current Reference Sensor

## 초기 권장 구성

- Limit Switch ×2~4
- Photo Interrupter ×1~2

Encoder는 Pilot 결과에서 필요성이 확인될 경우 추가 구매한다.

---

# 10. Network Experiment 구성

## 필수

- Wi-Fi Router/AP
- Raspberry Pi 또는 Linux Computer
- Ethernet Cable

## Software

별도 네트워크 장애 발생 하드웨어 없이 다음을 사용할 수 있다.

```text
tc
netem
iperf3
Mosquitto
tcpdump / Wireshark
```

## 권장 구조

```text
ESP32
 ↓ Wi-Fi
AP
 ↓
Linux Network Emulator
 ↓
MQTT Broker
```

초기에는 기존 Raspberry Pi와 Router로 시작한다.

추가 Raspberry Pi나 USB Ethernet Adapter는 실제 필요가 확인된 경우에만 구매한다.

---

# 11. 배선·제작용 잡부품

## 필수 권장

- Breadboard ×2
- Dupont Male-Male
- Dupont Male-Female
- Dupont Female-Female
- JST Connector Set
- Terminal Block
- Pin Header
- Heat-shrink Tube
- Wire
- USB Data Cable
- Ethernet Cable
- Cable Tie
- 나사
- 너트
- 와셔
- Spacer / Standoff

## 있으면 편리함

- Perfboard
- Screw Terminal PCB
- Lever Connector
- Ferrule

---

# 12. 측정장비

## 사실상 필수

- Digital Multimeter

## 매우 권장

- USB Logic Analyzer

용도:

- I²C/SPI 확인
- STEP/DIR 확인
- GPIO Event Trigger 확인
- Timing Validation

## 있으면 좋음

- Oscilloscope
- Bench Power Supply

하지만 논문을 위해 새 Oscilloscope를 반드시 구매할 필요는 없다.

---

# 13. 구매 우선순위

## A급 — 바로 구매

| 부품 | 수량 |
|---|---:|
| ESP32-S3-DevKitC-1-N8R8 | 2 |
| ICM-42688-P Breakout | 1 |
| INA226 Breakout | 1~2 |
| NEMA17 | 1 |
| TMC2209 Carrier | 2 |
| GT2 / Linear Stage 부품 | 1 Set |
| 12V PSU | 1 |
| 안정화 5V Node Supply | 1 |
| Breadboard | 2 |
| Jumper Wire / Connector Set | 1 Set |
| USB Data Cable | 2 |
| Bracket / Spacer / Fastener | 필요한 만큼 |

---

## B급 — 같이 구매 권장

| 부품 | 수량 | 용도 |
|---|---:|---|
| SG90/MG90S Servo | 1 | 반복 Fault Injection |
| Limit Switch | 2~4 | Position / Event Reference |
| Photo Interrupter | 1~2 | Physical Event Ground Truth |
| USB Logic Analyzer | 1 | Gate 0 Timing 검증 |
| Perfboard | 2~3 | 배선 안정화 |
| 추가 INA226 | 1 | Reference / Spare |

---

## C급 — Pilot 후 판단

| 부품 | 구매 판단 |
|---|---|
| Encoder | Position 정보 필요성이 확인되면 |
| 두 번째 IMU | Reference Sensor 필요 시 |
| 두 번째 Raspberry Pi | Network Bridge 필요 시 |
| Oscilloscope | 기존 장비로 Timing 검증 불가 시 |
| 추가 ESP32 Node | Multi-node 연구가 필요해질 경우 |

---

# 14. 현재 사지 않을 부품

현재 Research Question과 직접 관계가 없는 항목은 구매하지 않는다.

- Camera
- LiDAR
- PLC
- Industrial Servo
- EtherCAT Equipment
- Precision XY Stage
- 다수 ESP32 Node
- GPU 장비
- 별도 Cloud Server
- LCD
- Touchscreen
- Display
- Mobile-App 전용 Hardware

---

# 15. 최소 실험 시스템

최소 구성은 다음과 같다.

```text
              [Physical Testbed]

12V PSU
   ↓
TMC2209
   ↓
NEMA17
   ↓
Linear / Belt Motion
   ↓
Controlled Disturbance
   │
   └────→ ICM-42688
               ↓
          ESP32-S3
               │
5V PSU → INA226┘
               │
        Wi-Fi / MQTT
               ↓
        Router / AP
               ↓
       Raspberry Pi
   Mosquitto + Logger
               ↓
          CSV / Logs
               ↓
         Python Analysis
```

---

# 16. 핵심 구매 품목 6종

가장 중요한 핵심 부품은 다음 여섯 종류다.

1. **ESP32-S3**
2. **ICM-42688-P**
3. **INA226**
4. **NEMA17**
5. **TMC2209**
6. **반복 Motion Mechanism**

여기에:

- 12V Motor Power
- 5V Monitoring Node Power

를 분리하면 Gate 0 Measurement Validation을 시작할 수 있다.

---

# 17. 최종 권장

현재 단계에서는 부품을 과도하게 확장하지 않는다.

구매 우선순위는:

```text
AIoT Node
↓
Sensor
↓
Node Power Measurement
↓
Repeatable Motion Testbed
↓
Physical Event Ground Truth
↓
Network Experiment
```

순서로 본다.

특히 중요하게 확인할 사항:

- ESP32-S3는 PSRAM 포함 모델 우선
- IMU는 Breakout Module 형태 우선
- INA226 모듈은 Shunt 사양 확인
- Node Power와 Motor Power 완전 분리
- Motion Testbed는 정밀도보다 반복성 우선
- Fault Injection은 손으로 만들지 않고 반복 가능한 구조 우선

본 BOM은 `Research Protocol v1.0`의 Gate 0~4 Preliminary Experiment를 시작하기 위한 기준 목록으로 사용한다.
