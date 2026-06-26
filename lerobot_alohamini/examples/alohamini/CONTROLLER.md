# AlohaMini Web Pendant

Веб-пульт управления роботом AlohaMini. Камеры, 3D-визуализация рук, карта
маршрутов, запись демонстраций, запуск нейросети, биндинг геймпада
RadioMaster Pocket. Лёгкий — без torch/lerobot.

## Файлы

| Файл | Назначение |
|------|-----------|
| `controller_v3.py` | Бэкенд: Flask + ZMQ к Pi + pygame-геймпад + запись + инференс |
| `ui_main.html` | Веб-интерфейс (вкладки Drive/Cameras/Arms3D/Map/Record/AI) |
| `controller_v2.py` | Страница `/settings` — SVG RadioMaster Pocket, биндинг осей/кнопок |
| `convert_recording.py` | Запись `recordings/` → LeRobot-датасет для обучения |
| `gamepad_bindings.json` | Сохранённые привязки геймпада |
| `Dockerfile.controller` / `docker-compose.yml` | Контейнеризация пульта |
| `requirements-controller.txt` | Зависимости пульта |

## Запуск (нативно)

```powershell
# Windows venv с зависимостями пульта
D:\Проекты\Kiborg\lerobot_alohamini\.venv312\Scripts\python.exe controller_v3.py
```
Открыть http://localhost:8080 · биндинг геймпада http://localhost:8080/settings

### Env-переменные
| Var | Default | Что |
|-----|---------|-----|
| `ROBOT_IP` | 172.24.93.157 | IP малины (хост lekiwi) |
| `CMD_PORT` | 5555 | ZMQ команды PC→Pi |
| `OBS_PORT` | 5556 | ZMQ наблюдения Pi→PC |
| `WEB_PORT` | 8080 | порт веб-сервера |
| `DEMO_CAMERAS` | — | `1` = синтетическое видео камер (тест без робота) |

## Запуск (Docker)

```bash
# Реальный робот (geймпад через /dev/input, Linux-хост)
docker compose up --build

# Демо без робота — синтетические камеры
DEMO_CAMERAS=1 docker compose up --build

# Или вручную
docker build -f Dockerfile.controller -t alohamini-pendant .
docker run --rm -p 8080:8080 -e ROBOT_IP=172.24.93.157 --device /dev/input \
  -v "$PWD/recordings:/app/recordings" alohamini-pendant
```

> Геймпад в Docker работает только на Linux-хосте (проброс `/dev/input`).
> На Windows/Mac запускай пульт нативно для поддержки геймпада.

## Вкладки

- **Drive** — омни-база (W/S вперёд-назад, A/D поворот, Z/X стрейф), лифт (U/J),
  скорость (R/F). Кнопки на экране + клавиатура.
- **Cameras** — все MJPEG-потоки с робота (`/camera/<name>`). Источник —
  ZMQ-наблюдения с Pi (base64 JPEG). `DEMO_CAMERAS=1` для теста без робота.
- **Arms 3D** — Three.js-модель обеих рук, суставы по live-данным, ползунки ±.
- **Map / Routes** — 2D-карта, клик = waypoint, одометрия (dead reckoning по
  командам), кнопка ▶ проезжает маршрут автоматически.
- **Record** — запись демонстраций: имя датасета → Start → управляешь роботом →
  Stop. Пишет `recordings/<ds>/episode_NNN/` (data.jsonl + кадры камер).
- **AI Control** — выбор обученной модели (скан `outputs/train`) → Start
  запускает `lerobot_rollout`, нейросеть управляет роботом. Пульт паузит
  отправку команд, чтобы не конфликтовать.

## Биндинг геймпада (`/settings`)

SVG RadioMaster Pocket: гимблы двигаются по живым осям, переключатели/кнопки
подсвечиваются. Клик на элемент → панель справа: action, scale, dead zone
(с превью кривой), invert. Сохранение в `gamepad_bindings.json`.
Геймпад подключается на лету (hot-plug, без перезапуска).

## Пайплайн обучения нейросети

```
1. Record (веб)        → recordings/<ds>/episode_*/
2. convert_recording.py → LeRobot-датасет (нужен torch+lerobot env)
     python convert_recording.py <ds> --repo_id user/task --fps 30
3. lerobot-train       → outputs/train/.../checkpoints/
4. AI Control (веб)    → lerobot_rollout, инференс на ПК, действия → Pi
```

## Протокол ZMQ (PC ↔ Pi)

- `tcp://<ROBOT_IP>:5555` — команды (PUSH→PULL, JSON action, CONFLATE)
- `tcp://<ROBOT_IP>:5556` — наблюдения (PUSH→PULL, JSON + base64 JPEG камер)

Pi-сторона: `python -m lerobot.robots.alohamini.lekiwi_host --robot_model alohamini1`
