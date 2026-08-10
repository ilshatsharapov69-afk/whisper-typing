# Whisper Typer — полный технический контекст для аудита

Дата снимка состояния: 2026-08-10  
Операционная система: Windows  
Основной язык пользователя: русский, с частыми английскими терминами  
Назначение этого файла: дать другой нейросети или разработчику готовый фактический контекст проекта без необходимости сначала разбираться, где лежат файлы и как связаны компоненты.

## 1. Главное

Рабочий проект находится здесь:

```text
D:\whisper-typing
```

Основной исходный код:

```text
D:\whisper-typing\src\whisper_typing
```

Тесты:

```text
D:\whisper-typing\tests
```

Git-состояние на момент составления отчёта:

```text
branch: main
working tree: clean
latest commit: 6378fe6 perf: reduce overlay rendering overhead
origin: https://github.com/ilshatsharapov69-afk/whisper-typing.git
upstream: https://github.com/rpfilomeno/whisper-typing.git
```

В проекте 17 исходных файлов, около 4216 строк Python и 100 тестовых функций.

Приложение в целом выполняет локальное распознавание речи по глобальной горячей клавише: записывает микрофон, сохраняет резервный WAV, распознаёт речь через `faster-whisper`, сохраняет результат в историю, возвращает фокус в исходное окно и вставляет текст через clipboard + Ctrl+V.

Главная известная проблемная подсистема — автоматическая пауза видео и другого медиа в Windows/Chrome/Picture-in-Picture. Она работает нестабильно: YouTube может сначала остановиться, а затем снова запуститься.

## 2. Структура проекта

### Корневые файлы и папки

| Путь | Назначение |
|---|---|
| `D:\whisper-typing\config.json` | Фактическая пользовательская конфигурация |
| `D:\whisper-typing\.env` | Секреты, в частности Gemini API key; содержимое нельзя публиковать |
| `D:\whisper-typing\.venv` | Рабочее Python-окружение |
| `D:\whisper-typing\models` | Локальный кэш моделей Whisper |
| `D:\whisper-typing\tests` | Unit-тесты |
| `D:\whisper-typing\_app.log` | Текущий журнал приложения |
| `D:\whisper-typing\_app.log.1`, `.2` | Ротированные старые журналы |
| `D:\whisper-typing\history.json` | Основная персистентная история распознаваний |
| `D:\whisper-typing\_history.html` | Генерируемый HTML-отчёт истории |
| `D:\whisper-typing\_audio_backup` | Последние резервные WAV-записи |
| `D:\whisper-typing\whisper-typing-silent.vbs` | Скрытый запуск без консольного окна |
| `D:\whisper-typing\keepalive.ps1` | Проверка живости и перезапуск приложения |
| `D:\whisper-typing\keepalive.vbs` | Скрытый запуск keepalive PowerShell-скрипта |
| `D:\whisper-typing\start.bat` | Ручной запуск из консоли |
| `D:\whisper-typing\build_dist.ps1` | Сборка standalone EXE |
| `D:\whisper-typing\pyproject.toml` | Python-зависимости, Ruff, pytest и coverage-настройки |
| `D:\whisper-typing\uv.lock` | Зафиксированные зависимости `uv` |
| `D:\whisper-typing\README.md` | Документация; частично устарела относительно реальной конфигурации |
| `D:\whisper-typing\project-status.json` | Старый статус проекта; последний раз обновлялся 2026-07-10 и не отражает текущий баг паузы |

### Исходный код

| Файл | Назначение |
|---|---|
| `src\whisper_typing\__main__.py` | Точка входа, single-instance mutex, запуск TUI/controller |
| `src\whisper_typing\app_controller.py` | Главный оркестратор: конфигурация, hotkey, запись, пауза медиа, транскрибация, история, вставка |
| `src\whisper_typing\audio_capture.py` | Захват микрофона через `sounddevice.InputStream` |
| `src\whisper_typing\transcriber.py` | `faster-whisper`, CUDA/CPU fallback, финальная и быстрая транскрибация, фильтрация галлюцинаций |
| `src\whisper_typing\overlay.py` | Эквалайзер при записи и индикатор обработки |
| `src\whisper_typing\browser_media_bridge.py` | Python-клиент постоянного PowerShell helper-а для Chrome/PiP |
| `src\whisper_typing\browser_media_bridge.ps1` | UI Automation и фоновые Windows-сообщения для клика по Play/Pause в Chromium |
| `src\whisper_typing\diagnostics.py` | Ротируемый лог, WAV-бэкапы, `history.json`, HTML-история |
| `src\whisper_typing\window_manager.py` | Сохранение и восстановление активного окна |
| `src\whisper_typing\tray_icon.py` | Иконка и меню в system tray |
| `src\whisper_typing\ai_improver.py` | Опциональное улучшение текста через Gemini |
| `src\whisper_typing\typer.py` | Старый модуль посимвольной печати; в текущем основном auto-paste потоке не импортируется |
| `src\whisper_typing\tui\app.py` | Textual TUI, связь controller с tray и экраном |
| `src\whisper_typing\tui\screens.py` | Экраны конфигурации и истории TUI |

## 3. Как приложение запускается

Основной скрытый запуск выполняется файлом:

```text
D:\whisper-typing\whisper-typing-silent.vbs
```

Он устанавливает рабочую директорию `D:\whisper-typing` и скрыто выполняет:

```text
.venv\Scripts\python.exe -m whisper_typing
```

`src\whisper_typing\__main__.py`:

1. Создаёт Windows named mutex `WhisperTyping_SingleInstance`.
2. Если mutex уже занят, пишет `Another whisper-typing instance is already running — exiting.` и завершает второй экземпляр.
3. Загружает `.env`.
4. Создаёт `WhisperAppController`.
5. Загружает конфигурацию.
6. Запускает Textual TUI. При запуске через VBS интерфейс скрыт, но tray icon продолжает работать.

`keepalive.ps1` отдельно проверяет существование mutex. Если приложение не запущено, он вызывает `whisper-typing-silent.vbs`. Наличие файлов keepalive подтверждено; конкретная задача Windows Task Scheduler этим отчётом не подтверждена.

## 4. Фактическая текущая конфигурация

Источник истины:

```text
D:\whisper-typing\config.json
```

Ключевые значения:

```text
hotkey: numpad_enter
extra_hotkeys: []
improve_hotkey: <f10>
record_mode: toggle
model: openai/whisper-large-v3-turbo
language: null (automatic detection)
microphone_name: HyperX SoloCast
device: cuda
compute_type: int8_float16
model_cache_dir: ./models/
pause_media: true
auto_type: true
auto_format: false
refocus_window: true
visualizer_style: bars
visualizer_gradient: cyan_purple
debug: true
```

Практическое поведение:

- Первое нажатие правого цифрового Enter начинает запись.
- Второе физическое нажатие завершает запись.
- Обычный Enter должен оставаться нетронутым.
- Правый Enter определяется как `VK_RETURN` с Windows extended-key flag.
- Физический numpad Enter подавляется глобальным hook, чтобы не отправлять newline и не нажимать сфокусированную кнопку PiP.
- Injected/synthetic Enter игнорируется и не запускает запись.
- Auto-repeat удерживаемой клавиши подавляется до key-up.
- F9 больше не зарегистрирован как глобальная горячая клавиша.
- F10 остаётся отдельной функцией улучшения уже распознанного текста через Gemini.
- Автоматическое Gemini-форматирование после каждой записи сейчас выключено (`auto_format=false`).

README частично устарел: в нём встречаются Caps Lock/F8 и hold mode как примеры. Для фактической работы необходимо доверять `config.json` и коду, а не этим примерам README.

## 5. Полный рабочий поток

### 5.1 Нажатие правого Enter

Путь события:

```text
Windows low-level keyboard hook
→ _record_key_down("numpad_enter")
→ _queue_record_toggle()
→ отдельный thread `record-toggle`
→ _do_record_toggle()
→ on_record_toggle()
```

`_ptt_lock` сериализует быстрые start/stop, чтобы повторное нажатие не столкнулось с ещё не завершившейся остановкой микрофона.

### 5.2 Начало записи

`WhisperAppController._start_recording()`:

1. Запоминает окно, активное в момент старта.
2. Очищает preview и `pending_text`.
3. Запускает `AudioRecorder`.
4. Показывает overlay-эквалайзер.
5. Запускает проверку живости микрофона.
6. Пишет `Recording started...` в `_app.log`.
7. Запускает live transcription thread.
8. Отдельным фоновым thread запускает паузу медиа.

Запись намеренно начинается раньше паузы медиа, чтобы медленная Windows SMTC/UI Automation операция не задерживала начало захвата речи.

### 5.3 Захват аудио

`audio_capture.py` использует:

```text
sounddevice.InputStream
sample rate: 16000 Hz
channels: 1 (mono)
device: configured HyperX SoloCast index
storage: list of NumPy arrays under threading lock
```

Максимальный внутренний буфер фактически равен:

```text
16000 * 1800 samples = примерно 30 минут
```

Комментарий рядом с trimming-кодом всё ещё говорит «5 min», но значение константы соответствует 30 минутам.

Если PortAudio/USB поток падает, ошибка сохраняется в `AudioRecorder.last_error`. `stop()` всё равно пытается вернуть уже накопленные фреймы, чтобы длинная диктовка не исчезла полностью.

### 5.4 Live preview

Во время записи `_live_transcription_loop()`:

- просыпается каждую секунду;
- выполняет preview не чаще одного раза в две секунды;
- берёт последние пять секунд аудио;
- требует минимум одну секунду данных;
- вызывает `transcribe_fast()` с `beam_size=1`;
- не ждёт модель, если она занята финальной транскрибацией;
- использует VAD с `min_silence_duration_ms=500`.

### 5.5 Второе нажатие Enter и остановка

Текущая последовательность в toggle mode:

```text
increment _ptt_gen
→ MediaController.resume()
→ _stop_recording_and_type()
→ показать processing spinner
→ остановить live preview
→ AudioRecorder.stop()
→ получить полный NumPy audio buffer
```

Важно: медиа возобновляется ДО фактической остановки микрофона. Это подтверждается кодом `app_controller.py` в `on_record_toggle()` и `_do_ptt_stop()`.

### 5.6 Финальная обработка

После `recorder.stop()` отдельный thread:

1. Сохраняет исходное аудио в `_audio_backup`.
2. Вызывает финальный `Transcriber.transcribe()`.
3. При наличии текста сохраняет `pending_text`.
4. При включённом `auto_format` мог бы вызвать Gemini, но сейчас эта функция выключена.
5. Записывает результат в `history.json`.
6. Копирует текст в clipboard.
7. Возвращает фокус в окно, активное в момент начала записи.
8. Проверяет, что фокус действительно совпал.
9. Отправляет Ctrl+V через Win32 `keybd_event`.
10. Если фокус вернуть не удалось, текст остаётся в clipboard и History, но автоматически не вставляется.

Новая запись может стартовать, пока предыдущая запись ещё распознаётся. GPU-доступ сериализуется внутренним lock объекта `Transcriber`.

## 6. Whisper и качество распознавания

Файл:

```text
D:\whisper-typing\src\whisper_typing\transcriber.py
```

Модель:

```text
openai/whisper-large-v3-turbo
device=cuda
compute_type=int8_float16
language=null
```

Если CUDA не загружается, код пытается перейти на CPU.

Финальное распознавание:

```text
beam_size=5
condition_on_previous_text=False
vad_filter=True
min_silence_duration_ms=1000
```

Live preview:

```text
beam_size=1
condition_on_previous_text=False
vad_filter=True
min_silence_duration_ms=500
```

Перед Whisper есть RMS-проверка тишины с threshold `0.002`.

После Whisper выполняется фильтрация известных галлюцинаций. Среди них:

- `Продолжение следует`;
- русские/английские credits/subtitles phrases;
- `Спасибо за просмотр`;
- `Thank you for watching`;
- некоторые короткие повторяющиеся фразы.

Финальные ложные outro-фразы удаляются только как suffix полного текста, чтобы не удалять такие слова из середины нормальной диктовки.

## 7. История, логи и восстановление

Файл логики:

```text
D:\whisper-typing\src\whisper_typing\diagnostics.py
```

Лог:

```text
D:\whisper-typing\_app.log
```

Параметры ротации:

```text
2,000,000 bytes per file
3 backup files
UTF-8
```

История:

```text
D:\whisper-typing\history.json
```

Каждая запись может содержать:

```text
timestamp
text
status: ok | empty | error
audio_path
error
```

Лимиты:

```text
1000 history entries
100 WAV backups
```

Запись `history.json` атомарная: сначала создаётся `.json.tmp`, выполняется flush + fsync, затем файл заменяется. Повреждённый JSON переименовывается в `.json.corrupt`, а не молча перезаписывается.

При загрузке история умеет восстанавливать старые успешные транскрипции из ротированных `_app.log*`.

Tray menu `History` вызывает генерацию:

```text
D:\whisper-typing\_history.html
```

HTML содержит поиск, кнопки копирования и ссылки/проигрывание WAV при наличии файла.

## 8. Overlay и визуализация

Файл:

```text
D:\whisper-typing\src\whisper_typing\overlay.py
```

Текущий облегчённый режим:

```text
20 простых frequency bars
30 visual frames per second
FFT analysis 15 times per second
2048-sample FFT window (~128 ms at 16 kHz)
interpolation between FFT samples
one Tk Canvas object per bar
```

При остановке записи эквалайзер заменяется на прозрачный сине-голубой spinner:

```text
48x48 px
30 pre-rendered frames
~30 FPS
transparent background
gradient tail
```

Overlay работает в отдельном Tk thread. Важность визуализации вторична относительно записи и транскрибации; последние изменения специально уменьшили её нагрузку.

## 9. Подсистема паузы медиа

Это наиболее важный раздел для текущего аудита.

### 9.1 Заявленное поведение

При начале записи приложение должно:

1. Определить всё играющее медиа.
2. Поставить его на паузу.
3. Запомнить только то, что приложение действительно остановило.
4. Не запускать видео, которое пользователь уже сам поставил на паузу.
5. После второго Enter возобновить только остановленное приложением медиа.

### 9.2 Реальное покрытие

Текущий код не является универсальной паузой «любого видео во всём Windows».

Он покрывает только:

1. Приложения, которые публикуют Windows SMTC media session.
2. Видимые Chromium-окна, где UI Automation находит кнопку с известным именем.

Приложение без SMTC и без подходящей доступной Chrome-кнопки не будет остановлено.

Внешнее расширение Automatic Picture-in-Picture не входит в этот репозиторий. Его поведение и исходники приложение не контролирует.

### 9.3 Механизм №1: Windows SMTC

Реализация находится в классе `MediaController` внутри:

```text
D:\whisper-typing\src\whisper_typing\app_controller.py
```

Константы:

```text
overall timeout: 3.0 s
Playing status: 4
Paused status: 5
confirmation attempts: 5
confirmation delay: 0.05 s
```

Алгоритм:

1. Получает `GlobalSystemMediaTransportControlsSessionManager`.
2. Берёт все сессии через `get_sessions()`.
3. Если API недоступен, использует только `get_current_session()`.
4. Для каждой сессии со статусом Playing вызывает `try_pause_async()`.
5. До пяти раз проверяет точное состояние Paused.
6. Запоминает реальные session objects, а не application ID.
7. При resume проверяет, что сессия всё ещё Paused, и вызывает `try_play_async()`.

Исключения внутри обработки отдельных сессий подавляются без записи подробностей в лог.

Если `try_pause_async()` подействует с задержкой больше confirmation window, команда может фактически остановить видео, но сессия не попадёт в lease. Состояние тогда становится неотслеживаемым.

### 9.4 Механизм №2: Chrome/PiP PowerShell fallback

Python-часть:

```text
D:\whisper-typing\src\whisper_typing\browser_media_bridge.py
```

PowerShell-часть:

```text
D:\whisper-typing\src\whisper_typing\browser_media_bridge.ps1
```

Python запускает скрытый постоянный процесс:

```text
powershell.exe
-NoLogo
-NoProfile
-NonInteractive
-ExecutionPolicy Bypass
-File browser_media_bridge.ps1
```

Timeouts:

```text
helper startup: 5 s
command response: 3 s
```

Протокол — строки `pause`, `resume`, `stop` через stdin и newline-delimited JSON через stdout.

PowerShell helper:

1. Загружает `UIAutomationClient` и `UIAutomationTypes`.
2. Enumerates видимые top-level окна класса `Chrome_WidgetWin_1`.
3. Ищет descendants с ControlType `Button`.
4. Считает видео играющим, если имя кнопки соответствует:
   - `Pause`;
   - `Pause video`;
   - `Приостановить`;
   - `Пауза`;
   - `Остановить`.
5. Отбрасывает offscreen, слишком маленькие и слишком большие элементы.
6. Находит `Chrome_RenderWidgetHostHWND` под координатами кнопки.
7. Через `PostMessage` отправляет `WM_MOUSEMOVE`, `WM_LBUTTONDOWN`, `WM_LBUTTONUP`.
8. До 12 раз с задержкой 75 мс ждёт, что accessibility name станет `Play`.
9. Только после успешной проверки сохраняет control object в `$script:leases`.
10. Resume нажимает сохранённый control только если тот сейчас называется `Play`.

PowerShell повсеместно использует пустые `catch {}`. Python запускает helper с `stderr=subprocess.DEVNULL`. Поэтому значительная часть реальной причины отказа теряется.

## 10. Почему YouTube может Pause → Play во время записи

### 10.1 Два независимых контроллера одного видео

В `MediaController.pause_if_playing()` сначала выполняется Windows SMTC, затем browser fallback:

```text
SMTC pause all
→ BrowserMediaBridge.pause_playing()
```

Между SMTC session и UI Automation button нет общей идентичности. Приложение не определяет, что оба объекта относятся к одному YouTube video.

Вероятная гонка:

1. SMTC отправляет YouTube Pause.
2. YouTube останавливается.
3. UI Automation ещё некоторое время возвращает старое имя кнопки `Pause`.
4. Browser fallback повторно видит `Pause` и кликает кнопку.
5. Поскольку видео уже остановлено, toggle-клик запускает его обратно.
6. Проверка fallback ожидает `Play`, но получает `Pause`, поэтому lease не сохраняется.
7. Побочный запуск видео уже произошёл, хотя fallback сообщает `paused=0`.

Комментарий PowerShell-кода утверждает, что имя кнопки перечитывается непосредственно перед кликом, но перечитывание не гарантирует свежесть accessibility tree.

### 10.2 Resume выполняется раньше остановки микрофона

На втором правом Enter текущий код сначала делает:

```text
MediaController.resume()
```

и только затем:

```text
_stop_recording_and_type()
→ recorder.stop()
```

Следствия:

- YouTube может начать играть до фактической остановки аудиозахвата.
- Конец WAV может получить звук видео.
- Второе нажатие Enter может казаться медленным, поскольку `resume()` ждёт SMTC и browser helper.
- В худшем случае последовательные timeout могут занять несколько секунд до вызова `recorder.stop()`.

Это поведение одинаково присутствует и в toggle path, и в PTT stop path.

### 10.3 Stale lease healing может само запускать медиа

Перед созданием новой pause lease:

- Python SMTC controller вызывает `_resume_locked()`, если остались старые sessions.
- PowerShell `Pause-Playing` сначала вызывает `Resume-Leases`.

То есть начало новой записи может сначала воспроизвести медиа из старого незакрытого lease и только потом попытаться остановить его снова.

### 10.4 Потеря lease при timeout helper-а

Если PowerShell успел кликнуть кнопку, но Python не получил JSON в течение timeout:

1. Side effect уже мог произойти.
2. Python считает команду неуспешной.
3. Python завершает helper process.
4. `$script:leases` уничтожается вместе с процессом.
5. Приложение больше не знает, какое видео изменило.

### 10.5 External Automatic Picture-in-Picture extension

Расширение может самостоятельно реагировать на:

- смену активной вкладки;
- смену окна;
- закрытие/открытие PiP;
- внутренний playback state YouTube.

Оно может возобновить воспроизведение уже после команды приложения. В репозитории нет API-интеграции с расширением, только косвенное управление кнопкой/SMTC.

### 10.6 `_we_paused_media` не управляет поведением

Поле `WhisperAppController._we_paused_media` устанавливается в `True` после успешной паузы и несколько раз сбрасывается, но нигде не читается как условие. Оно не предотвращает ненужный resume и фактически является мёртвым состоянием.

## 11. Подтверждения из реального журнала

Текущий журнал:

```text
D:\whisper-typing\_app.log
```

### 11.1 Ошибка 2026-08-10

```text
2026-08-10 12:13:47 [INFO] Recording started...
2026-08-10 12:13:52 [INFO] Browser media fallback unavailable (Empty: ).
2026-08-10 12:14:33 [INFO] Stopping recording...
```

`Empty:` — это `queue.Empty`: Python не получил ready/command JSON response от PowerShell helper до timeout. По времени наиболее похоже на пятисекундный startup timeout, но лог не сообщает, на какой именно стадии возник timeout.

В этой записи отсутствует строка `Media paused and verified`, то есть controller не создал подтверждённую pause lease.

Отдельная безопасная проверка cold-start helper-а 2026-08-10, без команды Pause и без кликов по окнам, вернула:

```text
started=True
logs=[]
```

Следовательно, helper не сломан постоянно; сбой периодический и возникает при жизненном цикле процесса или выполнении команды.

### 11.2 Рассинхронизация 2026-08-09

```text
2026-08-09 17:58:14 [INFO] Recording started...
2026-08-09 17:58:15 [INFO] Media paused and verified (sessions=1, browser=1).
2026-08-09 17:58:24 [INFO] Media resumed (sessions=0/1, browser=0/1).
2026-08-09 17:58:24 [INFO] Stopping recording...
```

Наблюдения:

- SMTC и browser fallback одновременно создали по одному lease.
- При resume оба механизма сообщили 0 успешных resume из 1 lease.
- `Media resumed` записан раньше `Stopping recording`, что подтверждает порядок resume-before-recorder-stop.

Другой случай работал штатно:

```text
2026-08-09 18:02:26 [INFO] Media paused and verified (sessions=1, browser=0).
2026-08-09 18:02:49 [INFO] Media resumed (sessions=1/1, browser=0/0).
```

Это подтверждает, что проблема интермиттирующая и особенно подозрительна при одновременной работе двух механизмов.

## 12. Тесты и реальное покрытие

Папка:

```text
D:\whisper-typing\tests
```

Сейчас обнаружено 100 функций `test_*`. Последний полный обычный прогон завершался успешно.

Media tests проверяют:

- запоминание точного SMTC session object;
- отсутствие resume для заранее остановленной сессии;
- отсутствие lease при неподтверждённом pause;
- browser bridge participation через mock;
- debounce numpad Enter;
- неперехватывание обычного Enter;
- toggle start/stop;
- overlay frame cadence и количество Canvas objects.

Ключевое ограничение: media tests полностью используют `MagicMock`/`AsyncMock`. Нет настоящего end-to-end теста с:

- реальным Chrome;
- реальным YouTube;
- реальным Picture-in-Picture;
- Automatic Picture-in-Picture extension;
- настоящими WinRT SMTC sessions;
- одновременным SMTC + browser fallback для одного media source;
- delayed/stale accessibility name;
- PowerShell startup/command timeout;
- потерей JSON response после фактического клика;
- несколькими вкладками Chrome;
- несколькими приложениями-плеерами;
- быстрым вторым Enter во время незавершённой паузы.

Таким образом, unit-тесты подтверждают задуманную внутреннюю модель, но не подтверждают реальную работоспособность главной проблемной функции.

## 13. Дополнительные технические несоответствия

1. `README.md` не является точным описанием текущей конфигурации hotkey/mode.
2. `project-status.json` заявляет `Feature-complete. Maintenance.`, но не обновлялся после появления текущих проблем.
3. `typer.py` содержит старую медленную посимвольную печать, но основной поток вставляет текст через clipboard + Ctrl+V.
4. `_we_paused_media` записывается, но не читается.
5. Комментарий в `audio_capture.py` говорит о 5 минутах, тогда как константа допускает 30 минут.
6. Ошибки отдельных SMTC sessions молча подавляются.
7. PowerShell UI Automation ошибки молча подавляются.
8. PowerShell stderr отбрасывается.
9. Python логирует `Empty:` без указания, был это startup timeout или command timeout.
10. Browser fallback управляет состоянием через toggle-click, а не через идемпотентную команду `ensure_paused`.
11. Browser и SMTC leases не объединены в одну модель media identity.
12. Resume вызывается синхронно до остановки recorder.

## 14. Краткий handoff для получателя этого файла

Приложение работает из `D:\whisper-typing`. Главный controller — `src\whisper_typing\app_controller.py`. Запись и Whisper в целом работают, данные защищены WAV-бэкапом и `history.json`. Главная проблема — `MediaController`: он сначала управляет Windows SMTC sessions, затем тем же медиа через PowerShell UI Automation toggle-click. Между двумя каналами нет дедупликации. Это создаёт реальную возможность двойного переключения Pause → Play. Кроме того, при втором Enter медиа возобновляется до остановки микрофона. Текущий журнал подтверждает периодический timeout browser helper-а и случаи, когда одновременно создавались SMTC и browser leases, но последующий resume не подтверждался. Существующие unit-тесты не покрывают реальный Chrome/YouTube/PiP и гонку двух каналов.

## 15. Ограничения этого отчёта

- Исходный код в ходе подготовки файла не изменялся.
- Видео и Chrome не управлялись.
- Состояние media helper проверялось только безопасным cold-start без команды Pause.
- Содержимое `.env` и API keys не раскрывались.
- Этот файл содержит фактический контекст и диагностические выводы; отдельный промпт с требованием исправить/перепроектировать приложение пользователь планирует передать самостоятельно.
