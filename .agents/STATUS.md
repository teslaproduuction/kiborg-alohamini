# AlohaMini — статус проекта
_Обновлено: 2026-06-13 (ночь)_

---

## ✅ СДЕЛАНО / РАБОТАЕТ

### Железо
- [x] Сборка шасси (3 омни-колеса, лифт)
- [x] Две руки SO-101 (левая ID 1-6, правая ID 1-6)
- [x] 3 Waveshare контроллера: base=/dev/ttyACM0, right=/dev/ttyACM1, left=/dev/ttyACM2
- [x] udev симлинки: ttyWS_base, ttyWS_left, ttyWS_right
- [x] 5 USB-камер: video0/2/4/6/8 (не хаб-в-хаб)

### Малина / Pi-side (lekiwi_host)
- [x] lekiwi_host стартует, calibration грузится, lift homed
- [x] `__disarm_robot` → disable_torque() (без аргументов, все моторы)
- [x] `__arm_robot` → enable_torque()
- [x] `__arm_left` / `__arm_right` / `__arm_base` отдельный арм
- [x] Защита от краша: get_observation() в try/except
- [x] Защита от краша: кодировка камер в try/except (KeyError: 'front')
- [x] Защита от краша: stop_base() в disconnect() в try/except
- [x] BGR→RGB исправлен (cv2.imencode перед отправкой)
- [x] Флаг --no_right (правая рука не подключена)
- [x] Overcurrent защита (5000 mA лимит, 20 подряд = стоп)
- [x] Watchdog: нет команд 1.5с → стоп базы

### ПК / controller_v3.py
- [x] ZMQ PUSH/PULL cmd:5555 obs:5556
- [x] Старт в DISARMED состоянии (robot_disarmed=True)
- [x] SA switch (RadioMaster btn 6) — ARM/DISARM уровнем, с фиксацией
- [x] ExpressLRS Bluetooth ("express lrs" в названии устройства)
- [x] PS4 DualShock — управление руками (дельты на стики)
- [x] Оба триггера RadioMaster → full ARM; один → рука; без PS4 → только база
- [x] arm_hold_until (0.6с после ARM — нет позиционных команд)
- [x] arm_sync_until (0.5с — obs пишет реальные позиции в state)
- [x] smooth_move к "ready" пресету после ARM (shoulder_lift=25, elbow=-45)
- [x] DISARM из веба и SA работает (лог: WHOLE ROBOT DISARMED)
- [x] ARM из SA работает (лог: WHOLE ROBOT ARMED)
- [x] Пресеты: home / ready / gripper_open / gripper_close
- [x] Навбар в вебе: статус ARM/DISARM, клик = переключение
- [x] Настройки RadioMaster: live highlight кнопок/осей, rebind по нажатию
- [x] Настройки DS4: live highlight, rebind, arm_speed ползунок
- [x] Лифт: deadzone 0.30, ездит только при явной команде (нет концевиков)
- [x] Обратная связь камер: 5 камер в веб-гриде
- [x] 3D симулятор: shoulder_lift/elbow_flex/wrist_flex → rotation.x

---

## 🔴 НЕ РАБОТАЕТ / ПРОБЛЕМЫ

### Питание (КРИТИЧНО)
- [ ] **Просадка 5В при включении моторов** → USB отваливается → serial I/O error
  - Симптом: экран гаснет при ARM, lekiwi_host получает `termios.error`
  - Решение: заменить кабель питания до USB-хаба, добавить конденсатор 470-1000мкФ на 5В шину
  - Статус: _пользователь меняет кабель_

### ~~ARM по кнопкам в вебе~~
- [x] ИСПРАВЛЕНО: start_all.sh в /tmp стирался при ребуте → lekiwi_host не запускался. Постоянная копия теперь `/home/pi/start_robot.sh`

### Shoulder Pan (motor ID 1, левая рука)
- [x] Физически OK — motor 1 отвечает. Раньше был в fault state из-за конкурентного доступа к порту
- [x] ready пресет больше не трогает shoulder_pan (оба плеча = разные физические 0)
- [ ] Левая рука разворачивается немного не туда (shoulder_pan ≠ правильное "прямо") — нужна ручная подстройка

### .bash_profile
- [ ] Синтаксическая ошибка строка 4 (`fi` без `if`)
  - Некритично, только раздражает при SSH
  - Фикс: `nano ~/.bash_profile`, убрать строку с `fi`

---

## 🔵 ТЕСТИРУЕТСЯ

- [ ] ARM после замены питающего кабеля — не упадёт ли от просадки
- [ ] smooth_move к "ready" при ARM — руки должны идти плавно в mid-range
- [ ] DISARM → руки лимп (torque off), база тоже
- [ ] lekiwi_host выживает после serial error (новые try/except)
- [ ] Shoulder pan синхронизируется из obs при arm_sync_until окне

---

## ⏳ ПРЕДСТОИТ

### Сделано (этот сеанс)
- [x] PS4 deadzone: per-axis slider + Auto DZ кнопка (3с измерение шума), default 0.25→0.10
- [x] arm_speed default 0.6→2.5
- [x] Навбар redesign: Barlow Condensed + JetBrains Mono, янтарный ARMED, status pills
- [x] Light/dark тема на всех 3 страницах, localStorage
- [x] ⏻ Pi кнопка в навбаре (kill python → sudo shutdown)
- [x] systemd сервисы alohamini-host + alohamini-cam (автостарт при ребуте, installed)
- [x] .bash_profile починен (убран пустой if/fi блок)
- [x] Бекап малины: `pi-backup/pi_backup_2026-06-13.tar.gz` (135MB)
- [x] Recording tab: timer, progress bar, Next Episode кнопка, обновлённый список
- [x] Map/Waypoints: minor/major grid (20cm/1m), scale bar, расстояния между точками, right-click = clear, тема

### Средний приоритет
- [ ] Shoulder pan левой руки — физически развёрнута не туда, нужна ручная подстройка
- [ ] Камера front (/dev/video0) в lekiwi_host config — убедиться что закомментирована (crash если нет)
- [ ] robot_display.py — проверить глаза после всех изменений

### Низкий приоритет
- [ ] Запись датасетов → конвертация в LeRobot формат (convert_recording.py нужно написать)
- [ ] Обучение (lerobot train / ACT policy)
- [ ] Инференс (lerobot eval)
- [ ] Полноценный waypoint router с огибанием препятствий

---

## 📁 Ключевые файлы

| Файл | Назначение |
|------|-----------|
| `lerobot_alohamini/examples/alohamini/controller_v3.py` | Главный контроллер на ПК |
| `lerobot_alohamini/examples/alohamini/ui_main.html` | Веб-интерфейс |
| `lerobot_alohamini/examples/alohamini/ui_settings.html` | Настройки RadioMaster |
| `lerobot_alohamini/examples/alohamini/ui_arm_settings.html` | Настройки PS4 |
| `pi-config/robot_src/lekiwi_host.py` | Хост на малине |
| `pi-config/robot_src/lekiwi.py` | Робот-класс, send_action, get_observation |
| `lerobot_alohamini/examples/alohamini/gamepad_bindings.json` | Бинды RadioMaster |
| `/home/pi/start_robot.sh` | Постоянный скрипт запуска (не стирается) |
| `pi-config/systemd/` | systemd сервисы (установлены, автостарт) |
| `pi-backup/pi_backup_2026-06-13.tar.gz` | Бекап малины 135MB |

---

## 🔌 Топология железа

```
12V аккум → Waveshare base (ttyWS_base / ACM0)  — колёса ID8-10, лифт ID11
          → Waveshare left  (ttyWS_left  / ACM2)  — левая рука ID1-6
          → Waveshare right (ttyWS_right / ACM1)  — правая рука ID1-6
          → 12V→5V конвертер → RPi5
                               → USB hub → 5 камер (video0/2/4/6/8)
```

## 📡 Сеть

- Pi IP: set via `ROBOT_IP` env var (default in controller_v3.py)
- ZMQ cmd: `tcp://<ROBOT_IP>:5555`
- ZMQ obs: `tcp://<ROBOT_IP>:5556`
- Веб контроллер: http://localhost:8080
- Камера сервер: `http://<ROBOT_IP>:8091`
