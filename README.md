# Kiborg — AlohaMini Robot

Бэкап и рабочее окружение проекта **AlohaMini** — двурукий мобильный робот с лифтом на базе LeRobot.

## Структура

```
Kiborg/
├── AlohaMini/            ← железо: CAD/STL, BOM, docs, симуляция (URDF/meshes)
├── lerobot_alohamini/    ← форк LeRobot под AlohaMini (ОСНОВНОЙ софт)
│   └── examples/alohamini/
│       ├── controller_v3.py   ← веб-пульт: камеры, 3D-руки, карта/маршруты, AI
│       ├── ui_main.html       ← веб-интерфейс (вкладки Drive/Cameras/Arms/Map/AI)
│       ├── controller_v2.py   ← Steam-style биндинг геймпада (RadioMaster Pocket SVG)
│       ├── gamepad_bindings.json ← сохранённые привязки осей/кнопок
│       └── teleop_keyboard_simple.py / web_teleop.py ← простые пульты
├── lerobot/              ← upstream HuggingFace LeRobot (справочник)
└── .claude/             ← CLAUDE.md + AGENTS.md (контекст для AI-агентов)
```

> `lerobot/`, базовый `lerobot_alohamini/` и `AlohaMini/` — публичные репозитории.
> Ценность бэкапа = **мои правки** (см. ниже) + конфиг Pi.

## Железо

| Компонент | Кол-во | Заметки |
|-----------|--------|---------|
| Raspberry Pi 5 (8GB) | 1 | Хост (lekiwi_host) |
| Feetech STS3215 12V | 4 | База: колёса 8,9,10 + лифт 11 |
| Feetech STS3215 (руки) | 12 | 2 руки × 6 (ID 1–6) |
| Waveshare Bus Servo Controller | 3 | левая рука / правая рука / база |
| 12V Li-ion | 1 | База + лифт |
| USB камеры | до 5 | top/front/rear + 2× wrist |

### Порты на Pi (по факту сборки)
| Порт | Устройство | Моторы |
|------|-----------|--------|
| `/dev/ttyACM2` | Левая рука | 1–6 |
| `/dev/ttyACM0` | Правая рука | 1–6 |
| `/dev/ttyACM1` | База | 8,9,10,11 |

> Порядок `ttyACM*` может меняться при переподключении/ребуте — проверять через скан моторов.

### Питание
- База/лифт: 12V (STS3215-C018).
- Руки follower: **7.4V** (SO-101 моторы). Нужен отдельный 7.4V источник — на 5V моторы перегреваются (ток >2000mA на elbow_flex).

## Сеть / SSH

- Pi: `pi` / `raspberry`, статически ловится сканом `nmap -sn <subnet>`.
- WiFi (netplan `50-cloud-init.yaml`): Rostelecom-55, ASUS, Ёжик, CTT_wifi.
- Вентилятор: пороги в `/boot/firmware/config.txt` (`dtparam=fan_temp0=40000…`).

## Мои правки в lerobot_alohamini (ключевое для бэкапа)

Файлы `src/lerobot/robots/alohamini/`:
- **config_lekiwi.py** — добавлены `base_port`, `no_base`, `no_right`; порты под факт сборки.
- **lekiwi.py** — раздельная шина базы (`base_bus`), guard'ы на пустые base_motors, поднят лимит тока до 5000mA, защита чтения left_bus, частичная калибровка (правая рука отдельно).
- **lift_axis.py** — `descent_floor_mm=0`, приоритет `height_mm` над `vel` (фикс залипания лифта).

## Запуск

### Pi (хост):
```bash
conda activate lerobot
cd ~/lerobot_alohamini
python -m lerobot.robots.alohamini.lekiwi_host --robot_model alohamini1
```

### ПК (веб-пульт):
```powershell
D:\Проекты\Kiborg\lerobot_alohamini\.venv312\Scripts\python.exe `
  D:\Проекты\Kiborg\lerobot_alohamini\examples\alohamini\controller_v3.py
```
- Пульт: http://localhost:8080
- Биндинг геймпада: http://localhost:8080/settings

### Вкладки веб-интерфейса
- **Drive** — dpad базы, лифт, превью камеры
- **Cameras** — все MJPEG-потоки с робота (ZMQ obs → base64 JPEG)
- **Arms 3D** — Three.js визуализация суставов + ползунки
- **Map / Routes** — 2D карта, клик = waypoint, одометрия (dead reckoning), автопроезд
- **AI Control** — запуск обученной политики (lerobot_rollout) по сети

## Протокол связи ПК↔Pi (ZMQ)
- cmd  PC→Pi : `tcp://<pi>:5555` (PUSH/PULL, JSON action, CONFLATE)
- obs  Pi→PC : `tcp://<pi>:5556` (PUSH/PULL, JSON + base64 JPEG камер)

## Пайплайн обучения
1. `record_bi.py` — запись датасета (лидер-руки teleop).
2. `lerobot-train --policy.type=act …` — обучение на ПК с GPU.
3. AI Control / `lerobot_rollout` — инференс на ПК, действия → Pi.

> Лидер-рук в этой сборке нет — управление с геймпада/веба/клавиатуры.
