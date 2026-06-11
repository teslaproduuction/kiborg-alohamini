# Управление SO-101 через веб-интерфейс без leader-руки: обзор проектов и решений

## TL;DR
- **Да, такие решения существуют и работают.** Самый зрелый и активно поддерживаемый вариант — **phosphobot** (phospho-app): веб-дашборд на FastAPI с управлением клавиатурой, геймпадом, через HTTP API и VR — leader-рука прямо названа опциональной. Для чисто браузерного управления сервоприводами без установки Python лучший вариант — **Bambot / feetech.js** (Web Serial API, слайдеры, клавиатура, геймпад, 3D в браузере).
- **Прямой ответ на главный вопрос:** leader-рука НЕ обязательна. И LeRobot, и phosphobot, и Bambot, и ROS2-стеки позволяют управлять follower-рукой SO-101 напрямую — слайдерами, клавишами, геймпадом или программно через API.
- **Лучший выбор по сценарию:** для «поставил и работает» в браузере — phosphobot (localhost-дашборд); для чистого JS/Web Serial без бэкенда — Bambot и LeRobot.js; для 3D-визуализации/цифрового двойника — Bambot, RobotHub (LeRobot-Arena), LeLab; для ROS2+MoveIt+RViz — lerobot-ros, so101-ros-physical-ai, physical_ai_tools.

## Key Findings
1. **Leader-рука официально опциональна.** В документации phospho (docs.phospho.ai, страница `/basic-usage/teleop`, раздел FAQ) прямо сказано: «No, the leader arm is optional. You can control the robot arm with the keyboard, the game controller, the HTTP API, or the Meta Quest app without a leader arm. The leader arm is just an additional way to control the robot arm.»
2. **Самый практичный браузерный путь без Python** — экосистема Bambot (`bambot.org`): `feetech.js` (Web Serial API прямо из Chrome/Edge), панель управления сервоприводами, страница `play.bambot.org` с 3D-сценой и управлением клавиатурой/джойконами, страница сборки/калибровки SO-101.
3. **LeRobot (huggingface) сам по себе** поддерживает teleop без leader: `--teleop.type=keyboard` и `--teleop.type=gamepad` для `so100_follower`/`so101_follower`. Это CLI, не веб, но это база для веб-обёрток.
4. **Веб-дашборды поверх LeRobot:** phosphobot (FastAPI+React), LeLab (FastAPI+React+WebSocket, официальный HF), RobotHub/LeRobot-Arena (SvelteKit+Three.js), LeRobot.js (TypeScript, Web Serial).
5. **ROS2 + Web/MoveIt** реализован в physical_ai_tools (ROBOTIS, web HMI), so101-ros-physical-ai (MoveIt2), lerobot-ros (gamepad/keyboard teleop), so101_ros2.

## Details

### Категория A. Браузерные решения на чистом JS / Web Serial (без leader, без Python)

**1. Bambot (feetech.js + playground)**
- Ссылка: https://github.com/timqian/bambot ; сайты https://bambot.org , https://play.bambot.org , https://bambot.org/feetech.js
- Описание: Открытая платформа для управления недорогими роботами (включая SO-100/SO-101 и Feetech-сервоприводы) прямо из браузера. Включает `feetech.js` — JS-библиотеку для управления сервоприводами SCS/STS (в т.ч. STS3215) через Web Serial API; панель отладки/управления сервоприводами; playground с 3D-сценой и подключением к реальному роботу; пошаговую сборку и калибровку SO-101 в браузере.
- Стек: TypeScript (78.2%), JavaScript (12.3%), HTML (8.8%); Web Serial API, Web USB; 3D-визуализация в браузере; Apache-2.0.
- Способ управления: слайдеры (панель сервоприводов), клавиатура (раскладка по суставам: rotation/pitch/elbow/wrist/jaw), Nintendo Joycon; прямое управление каждым суставом без leader-руки.
- Поддержка: активно; **931 звезда, 90 форков, 146 коммитов** (GitHub timqian/bambot, на момент сбора). Управление сервоприводами и калибровка SO-101 через Web Serial подтверждены документацией DeepWiki.

**2. LeRobot.js (@lerobot/web, @lerobot/node)**
- Ссылка: https://github.com/TimPietrusky/lerobot.js ; demo Space: https://huggingface.co/spaces/NERDDISCO/LeRobot.js ; npm `@lerobot/web`, `@lerobot/node`
- Описание: JS/TypeScript-порт LeRobot. Позволяет найти USB-порт, откалибровать и управлять SO-100 прямо в браузере (Web Serial) или через Node/CLI. Автор — Tim Pietrusky (NERDDISCO).
- Стек: TypeScript, Vite, Apache-2.0; UI-прототип на React + shadcn/ui + Tailwind (v0.dev). Web Serial + Web USB. Требует Chromium-браузер ≥ v89.
- Способ управления: клавиатура и UI («control it with your keyboard or the UI»); API `findPort`/`calibrate`/`teleoperate`. По блогу автора на HF: «LeRobot.js currently ships as @lerobot/web … and supports the SO-100 in Chromium-based browsers»; npm-страница уточняет: «Currently supports SO-100 follower and leader arms with STS3215 motors.»
- Поддержка: небольшой, но живой проект; **35 звёзд, 3 форка** (GitHub); npm `@lerobot/node` v0.3.0, Apache-2.0, опубликован «9 months ago» на момент сбора.

### Категория B. Веб-дашборды поверх Python LeRobot

**3. phosphobot (phospho-app) — рекомендуемый**
- Ссылка: https://github.com/phospho-app/phosphobot ; документация https://docs.phospho.ai
- Описание: Community-driven middleware с чистым веб-дашбордом для управления роботами, записи датасетов, обучения и инференса VLA-моделей. Совместим с SO-100 и SO-101. Запускается локально, дашборд на `localhost:80` (или `:8020`).
- Стек: Python (64.3%) + TypeScript (33.7%); FastAPI-сервер, React/TS-дашборд (npm build), pybullet для симуляции, MIT.
- Способ управления (без leader): **клавиатура** (Keyboard Control — стрелки), **геймпад** (Gamepad Control, через Gamepad API; Xbox/PS), **HTTP API** (`/move/init`, `/move/...`, интерактивные docs на `localhost/docs`), **VR (Meta Quest)**. Leader-рука — отдельная опция, не обязательна.
- Поддержка: очень активный; **356 звёзд, 75 форков, 2057 коммитов**, MIT. **154 релиза**, последний v0.3.134 от 22 октября 2025 (github.com/phospho-app/phosphobot/releases).

**4. LeLab (официальный HuggingFace + оригинал nicolas-rabault)**
- Ссылки: https://github.com/huggingface/leLab ; оригинал https://github.com/nicolas-rabault/leLab ; Space `lerobot/LeLab` ; документация https://huggingface.co/docs/lerobot/main/en/lelab
- Описание: Браузерный веб-GUI поверх LeRobot. Объединяет калибровку, телеоперацию, запись датасетов, обучение (локально и через HF Jobs), инференс, replay и загрузку в Hub в одном веб-интерфейсе. Цель — пройти путь от распаковки SO-101 до policy без CLI.
- Стек: FastAPI-бэкенд (порт 8000) + React/TypeScript-фронтенд (Vite, порт 8080), WebSocket для реального времени, MIT. Команды `lelab`, `lelab-fullstack`.
- Способ управления: гид-флоу калибровки обеих рук без клавиатурных команд; телеоперация и **live 3D-визуализация рук**; live joint streaming. Базовый сценарий телеоперации использует leader→follower, но GUI, калибровка, инференс и 3D-визуализация работают и при ручной настройке.
- Поддержка: активный, поддерживается HuggingFace; Space обновлялся недавно на момент сбора.

**5. RobotHub (бывший LeRobot-Arena) — Julien Blanchon**
- Ссылки: https://github.com/julien-blanchon/RobotHub-Frontend ; https://github.com/julien-blanchon/RobotHub-TransportServer ; https://github.com/julien-blanchon/RobotHub-InferenceServer ; Spaces: https://huggingface.co/spaces/blanchon/RobotHub-Frontend , https://huggingface.co/spaces/blanchon/LeRobot-Arena ; live demo: https://blanchon-robothub-frontend.hf.space
- Описание: Открытый end-to-end стек: real-time коммуникация, 3D-визуализация (цифровой двойник) и AI-политики для управления симулированными и реальными роботами. В браузере спавнится SO-100 6-DoF (URDF). Прямо заявлен сценарий **Web-UI Manual Control: «Browser sliders → Remote producer → Robot (USB). No physical master arm needed – drive joints from any device.»**
- Стек: Frontend — SvelteKit + Svelte 5 + Threlte (Three.js), TypeScript, Tailwind, Bun; Transport Server — FastAPI + WebSocket + WebRTC (видео); Inference Server — FastAPI + PyTorch + опц. Gradio (ACT, Pi0, SmolVLA, Diffusion). USB-слой — feetech.js. MIT.
- Способ управления без leader: **слайдеры суставов** (компонент `ManualControlSheet`) — подтверждено. Цифровой двойник/3D-сцена через Threlte. (Управление перетаскиванием с IK, клавиатурой и геймпадом в README НЕ подтверждено — флаг.)
- Поддержка: фактически solo/hobby-проект; звёзд почти нет (Frontend 0, TransportServer 0, Inference 1), релизов нет, ~42/21/50 коммитов соответственно, активность ~середина-конец 2025; точные даты последних коммитов не подтверждены.

### Категория C. Базовый LeRobot CLI (фундамент для веб-обёрток)

**6. huggingface/lerobot — teleop без leader**
- Ссылка: https://github.com/huggingface/lerobot
- Описание: Основная библиотека. Поддерживает teleop-устройства keyboard и gamepad как замену leader-руке: `lerobot-teleoperate --robot.type=so101_follower --robot.port=... --teleop.type=keyboard` (или `gamepad`). Также есть phone-teleop (WebXR). Есть `SO100FollowerEndEffector` для управления концевым эффектором (IK), обсуждается в issue #1966 (для SO-101 совместимо с оговорками; есть открытый вопрос об отсутствии отдельного `SO101FollowerEndEffector`).
- Стек: Python, PyTorch; CLI + Rerun для визуализации.
- Способ управления: клавиатура, геймпад, телефон (WebXR), программно через `robot.send_action()`.
- Поддержка: очень активный, флагман экосистемы (релиз v0.5.0 — крупнейший на момент сбора).

### Категория D. ROS2 + Web / MoveIt

**7. physical_ai_tools (ROBOTIS)**
- Ссылка: https://github.com/ROBOTIS-GIT/physical_ai_tools
- Описание: Интерфейс для physical AI поверх LeRobot и ROS 2 с веб-компонентом (`physical_ai_manager` — JavaScript). Поддерживает LeRobot, включает lerobot как submodule.
- Стек: JavaScript (52.4%) + Python (44.9%) + C++ (1.3%); ROS 2 (Jazzy), Docker, Apache-2.0.
- Способ управления: веб-менеджер (HMI) + ROS2; запись датасетов, инференс.
- Поддержка: активный; **137 звёзд, 27 форков, 34 релиза, 1160 коммитов**; последний релиз 0.8.3 от 30 апреля 2026.

**8. so101-ros-physical-ai (legalaspro)**
- Ссылка: https://github.com/legalaspro/so101-ros-physical-ai
- Описание: Полный ROS 2-стек для SO-101: драйвер Feetech STS3215 через ros2_control, MoveIt 2 motion planning, мультикамеры, запись эпизодов, конвертация в LeRobot-датасеты, инференс политик (ACT/SmolVLA/Pi0), live-визуализация в Rerun.
- Стек: ROS 2, ros2_control, MoveIt 2, Pixi, Python, Rerun.
- Способ управления: основной демо — leader→follower teleop, но MoveIt 2 даёт планирование/управление без leader (интерактивные маркеры в RViz), а инференс политик — автономно.
- Поддержка: активный, PR/issues welcome.

**9. lerobot-ros (ycheng517)**
- Ссылка: https://github.com/ycheng517/lerobot-ros (+ симуляция https://github.com/Pavankv92/lerobot_ws)
- Описание: Generic ROS 2-интерфейс для LeRobot; обёртка для любой ros2_control/MoveIt-совместимой руки. Включает **gamepad-телеоператор для 6-DoF управления концевым эффектором** и **keyboard-телеоператор для управления положением суставов**.
- Стек: ROS 2 Jazzy, Python 3.12, MoveIt, Gazebo.
- Способ управления: геймпад (end-effector через MoveIt Servo / CARTESIAN_VELOCITY), клавиатура (joint position); leader не нужен. Симулированный SO-101 в Gazebo.
- Поддержка: живой, поддерживает разные режимы (JOINT_POSITION, JOINT_TRAJECTORY, CARTESIAN_VELOCITY).

**10. so101_ros2 (msf4-0)** и **SO-ARM101 MoveIt/IsaacSim (MuammerBay)**
- Ссылки: https://github.com/msf4-0/so101_ros2 ; https://github.com/MuammerBay/SO-ARM101_MoveIt_IsaacSim ; туториал https://lycheeai-hub.com/isaac-sim/ros2/so-arm101-moveit-in-isaac-sim-with-ros2
- Описание: ROS2-интеграция SO-101 (запись/replay движений; публикация JointState), и отдельный MoveIt-конфиг для SO-ARM101 с планированием движений в RViz/Isaac Sim.
- Стек: ROS 2 Humble, MoveIt 2, RViz2, ros2_control, Isaac Sim.
- Способ управления: MoveIt в RViz (перетаскивание интерактивного маркера end-effector, планирование), без leader; запись/replay.
- Поддержка: учебные/демо-проекты.

### Категория E. Прочие инструменты для STS3215 в браузере / на ПК
- **feetech.js** (часть Bambot, https://bambot.org/feetech.js) — конфигурирование и управление сервоприводами Feetech SCS/STS прямо в браузере через Web Serial.
- **Официальное ПО Feetech (FD/FT_SCServo_Debug_Qt)** — десктоп-приложение (Windows/Ubuntu) для отладки и управления сервами по TTL-шине; слайдеры положения, смена ID, режимы. Не веб, но прямое управление без leader.
- **Viam SO-101 module** (https://github.com/viam-devrel/so-101) — Viam-модуль с web-based setup app (Viam App) для конфигурации/калибровки и управления рукой через платформу Viam.

## Recommendations
1. **Нужно «просто работающее» веб-управление с ПК прямо сейчас** → ставьте **phosphobot**, откройте `localhost` в браузере: клавиатура, геймпад, HTTP API из коробки, leader не нужен. Порог входа минимальный, проект очень активен (356⭐, 154 релиза, последний — октябрь 2025).
2. **Нужно чистое браузерное управление сервоприводами без Python/установки** → **Bambot** (`play.bambot.org`, `feetech.js`): Web Serial из Chrome/Edge, слайдеры, клавиатура, джойстик, 3D-сцена. Подходит для быстрой проверки сервоприводов STS3215 и ручного управления суставами.
3. **Нужны 3D-визуализация и красивый UI / цифровой двойник** → начните с **LeLab** (официальный HF, FastAPI+React+3D) или **Bambot**; для экспериментального Svelte+Three.js стека — **RobotHub** (слайдеры без leader подтверждены, но проект hobby-уровня, без релизов — закладывайте время на самостоятельную сборку).
4. **Нужен production-grade IK / планирование траекторий** → **ROS2-путь**: `lerobot-ros` (gamepad/keyboard + MoveIt Servo), `so101-ros-physical-ai` (MoveIt 2), `physical_ai_tools` (web HMI, 137⭐, релизы до апреля 2026). Это самый трудоёмкий путь, но даёт полноценное управление концевым эффектором и планирование без leader.
5. **Если хватает CLI и не нужен браузер** → базовый **lerobot** с `--teleop.type=keyboard` или `--teleop.type=gamepad`. Это эталонная реализация; на неё опираются все веб-обёртки.

**Пороги для смены выбора:** если при slider-управлении из браузера не хватает обратной связи по позиции и обхода ограничений сервоприводов — переходите на ROS2/MoveIt. Если 0 звёзд и отсутствие релизов у RobotHub критичны для надёжности — выбирайте phosphobot или LeLab. Если нужна работа на Windows без WSL — phosphobot и Bambot предпочтительнее ROS2-стеков.

## Caveats
- **Slider/IK/gamepad в RobotHub:** в браузере подтверждено только slider-управление без leader (`ManualControlSheet`); управление перетаскиванием с инверсной кинематикой, клавиатурой и геймпадом в README НЕ задокументировано. Точные даты последних коммитов и число контрибьюторов не подтверждены; звёзд почти нет — это solo/hobby-проект.
- **LeRobot.js / NERDDISCO** официально поддерживает **SO-100** (follower и leader с моторами STS3215); для SO-101 совместимость вероятна (один протокол), но прямо не гарантирована автором на момент сбора.
- **LeLab** в документации описывает телеоперацию как leader→follower; ручное slider-управление follower-рукой без leader не подчёркнуто явно — основная «безлидерная» ценность LeLab в калибровке, инференсе и 3D-визуализации.
- **Калибровка phosphobot vs LeRobot:** калибровки совместимы, но независимы; при использовании LeRobot для обучения нужно перекалибровать руку в LeRobot после phosphobot (иначе min/max лимиты сервоприводов остаются «устаревшими»).
- **Web Serial API** (Bambot, LeRobot.js) работает только в Chromium-браузерах (Chrome/Edge ≥ 89); в Firefox/Safari не поддерживается.
- Часть деталей (звёзды, даты) приведена по состоянию на момент сбора (июнь 2026) и могла измениться.
- Проекты MuammerBay и so101_ros2 — преимущественно учебные/демонстрационные; для боевого применения требуется доработка.