# dev/ai/news

Русскоязычный Telegram-бот, который автоматически собирает свежие IT/AI-новости из подобранного списка источников, отбирает самое интересное с помощью лёгкой LLM, кратко пересказывает и публикует в соответствующие темы группового форума. Под каждым постом можно задавать вопросы — отвечает та же модель, опираясь на содержимое поста.

Преемник старого проекта `IT_AI_New`, переписан с нуля на Python с упором на модульность, экономию токенов и открытый исходный код.

## Что умеет

- **Сбор** новостей из ~45 RSS/HTML источников (приоритеты A–D, см. `config/sources.yaml`).
- **Триаж** — дешёвая модель оценивает интересность по заголовку и описанию (0–10), отсеивает мусор до того, как тратить токены на полный текст.
- **Резюме** — короткий разговорный русский, без воды, с ссылкой на оригинал в конце.
- **Публикация в темы форума** — целевая тема (Нейросети / Железо / Инструменты / Блокировки / Айти) определяется AI-классификатором на основе заголовка и резюме. Темы с флагом `no_autopublish` (Игры, Разговоры, Приветствия) исключаются из автопостинга.
- **Перепост из публичных TG-каналов** — отдельный фоновый цикл скрейпит `t.me/s/{channel}` (например, [@NewAITracker](https://t.me/NewAITracker) для новых AI-моделей), пересылает посты с картинками в нужную тему и припиской `Sponsored by @...`. Конфигурится в `config/channels.yaml`. Эти посты идут мимо AI-пайплайна — текст уже курируется автором канала.
- **Дополнения** — если новая новость — это развитие уже опубликованной (например, два источника про *iPhone 19*), бот публикует её как ответ на исходный пост, а не дубликат. Решение принимается через косинусную близость embeddings + контрольный judge-вопрос модели, чтобы отличить «то же событие» от «та же широкая тема».
- **Q&A под постом** — пользователь отвечает на пост → бот отвечает в той же ветке, передавая модели только summary поста как контекст (а не полную статью — экономия).
- **Роли + гранулярные права** — `owner` / `admin` / `moderator` / `trusted` / `user`. Каждое действие (мут, бан, удаление, статистика, назначение ролей, доступ к меню, обход rate-limit на Q&A и т. п.) — отдельный permission, переключаемый per-role через inline-меню `/admin`. Команды `/role`, `/mute`, `/ban`, `/delete`, `/stats`, `/whoami`.
- **Inline админ-панель** `/admin` — разделы «Роли / Права / Статистика / Источники / Настройки», все права настраиваются кликами по чекбоксам.
- **Привязка тем форума командой** — `/bindtopic` внутри нужной темы открывает inline-меню с рубриками; `/topics` показывает текущие привязки; `/unbindtopic <Имя>` снимает. Привязки хранятся в БД и переопределяют дефолты из `topics.yaml` — править файл вручную не нужно.
- **Статистика для админов** — `/stats [часов]`: посты, разбивка по темам и источникам, топ обсуждаемых, расход токенов по моделям/операциям, активные пользователи, mute/ban.
- **Приветствие новых участников** — при входе в группу бот пишет приветствие (тема настраивается, текст в `settings.yaml`), сообщение и сервисный «X joined» удаляются через 30 секунд.
- **Авто-обновление из git** — фоновая задача периодически делает `git fetch`, при наличии новых коммитов — `git pull --ff-only`, при изменении `requirements.txt` ещё и `pip install -r`, и рестарт через `os.execv`.

## Экономия токенов

Бот спроектирован вокруг идеи «не думать дороже, чем надо»:

1. RSS даёт title + description — это бесплатно.
2. Embeddings (`openai-3-small`, 512 dims) считаются один раз и кешируются в SQLite — используются для дедупа и поиска кандидатов на дополнение.
3. Триаж — `gemini-fast` с `max_tokens=5`, ответ строго числом 0–10.
4. Полный текст статьи скачивается **только** для прошедших триаж, и режется до ~6–8 КБ.
5. Resume пишется один раз и хранится — Q&A под постом получает в контекст summary, а не оригинал.
6. Addition-detection: сначала косинусная близость > 0.82 (бесплатно), и только потом cheap-judge «ДА/НЕТ» с `max_tokens=3`.

Все запросы к модели логируются в таблицу `ai_usage` с разбивкой по моделям и операциям — `/stats` показывает текущий расход.

## Стек

- Python 3.13+
- [aiogram 3.x](https://docs.aiogram.dev/) — Telegram-бот
- [Pollinations API](https://gen.pollinations.ai) (OpenAI-совместимый) — `gemini-fast` для текста, `openai-3-small` для embeddings
- SQLite — единственное хранилище, без внешних зависимостей
- aiohttp + feedparser + bs4/lxml — сбор источников

## Структура

```
src/
  main.py                  — entry point, поднимает бота, пайплайн и updater
  utils/                   — конфиг, логгер
  storage/                 — SQLite (posts, embeddings, users/roles, qa_log, ai_usage, audit)
  ai/                      — Pollinations клиент, промпты, высокоуровневые AI-таски
  sources/                 — RSS-парсер, выкачка полной статьи
  pipeline/                — оркестрация: fetch → triage → embed → dedup → addition → summarize → publish
  bot/                     — aiogram dispatcher, publisher, handlers (qa, admin)
  updater/                 — git auto-update + os.execv
config/
  sources.yaml             — список источников (сгенерирован из исследовательского xlsx)
  topics.yaml              — маппинг focus → message_thread_id (заполняется вручную после создания тем)
  settings.yaml            — параметры пайплайна, модерации, публикации
data/                      — SQLite-база, gitignored
```

## Источники

Список собран в `config/sources.yaml` — 45 рабочих RU/EN ресурсов с приоритетами A/B/C/D. Заблокированные и таймаутные источники из исследования отфильтрованы. Исходная таблица — `IT_SOURCES.xlsx`.

## Открытый код

Все секреты — только в `.env` (см. `.env.example`). `data/`, `*.sqlite`, логи — в `.gitignore`. Промпты вынесены в `src/ai/prompts.py`, конфиги — в `config/*.yaml`, чтобы можно было править без знания питона.

## Полный список источников

51 RSS/HTML источник, отсортированы по приоритету (`A` > `B` > `C` > `D`). Заблокированные в РФ и таймаутные ресурсы из исследования отфильтрованы. Конфиг — `config/sources.yaml`, отдельно есть Telegram-каналы в `config/channels.yaml`.

| # | Приоритет | Источник | Язык | Фокус | Заметки |
|---|-----------|----------|------|-------|---------|
| 1 | A | [Ars Technica](https://arstechnica.com) | EN | Аналитика/Наука/Tech | Парсить RSS полностью. Фильтр по тегам. Отсеять: игры. Брать: глубокие статьи и научные открытия. |
| 2 | A | [BleepingComputer](https://www.bleepingcomputer.com) | EN | Кибербезопасность/Malware | ОТЛИЧНЫЙ security-источник. RSS полностью. Брать: security breaches/malware/уязвимости. |
| 3 | A | [CNews](https://cnews.ru) | RU | IT-бизнес/Аналитика | Лучший RU источник. Отсеять: пресс-релизы. Брать: аналитика рынка и M&A. |
| 4 | A | [CSS-Tricks](https://css-tricks.com) | EN | CSS/Фронтенд | RSS полностью. Мало контента но высокого качества. Брать: всё. |
| 5 | A | [GitHub Blog](https://github.blog) | EN | GitHub/Open-source | Парсить RSS полностью. Мало шума. Брать: всё — каждая статья важна. |
| 6 | A | [Habr News](https://habr.com/ru/news/) | RU | IT/Программирование | RSS + фильтр рейтинг >50. Отсеять: переводы/холивары. Брать: оригинальные статьи. |
| 7 | A | [Hacker News](https://news.ycombinator.com) | EN | Startups/Программирование | hnrss.org с points>50. Отсеять: Show HN/jobs. Брать: высокорейтинговые обсуждения. |
| 8 | A | [Lobsters](https://lobste.rs) | EN | Программирование | RSS с фильтром score. Брать: высокорейтинговые посты о новых технологиях. |
| 9 | A | [LWN.net](https://lwn.net) | EN | Linux kernel | ОТЛИЧНЫЙ источник. RSS полностью. Ничего не отсеивать. Брать: всё. |
| 10 | A | [PC Gamer](https://www.pcgamer.com) | EN | Игры/PC | Релизы, обзоры, индустрия PC-игр. |
| 11 | A | [SecurityLab](https://www.securitylab.ru) | RU | Кибербезопасность | Лучший RU security-источник. RSS полностью. Брать: уязвимости/security trends/аналитика. |
| 12 | A | [Smashing Magazine](https://www.smashingmagazine.com) | EN | Фронтенд/UX/Дизайн | RSS полностью. Низкая частота — высокое качество. Брать: всё. |
| 13 | A | [StopGame](https://stopgame.ru) | RU | Игры/Релизы/Обзоры | Крупнейший RU игровой портал. Релизы, обзоры, индустрия. |
| 14 | A | [TechCrunch](https://techcrunch.com) | EN | Стартапы/Венчур | RSS по категориям. Отсеять: мелкие funding rounds. Брать: крупные сделки и IPO. |
| 15 | A | [The Guardian Tech](https://www.theguardian.com/technology) | EN | Tech policy/Privacy | RSS. Отсеять: обзоры гаджетов. Брать: tech policy/privacy/cybersecurity. |
| 16 | A | [VC.ru Tech](https://vc.ru/tech) | RU | IT-бизнес/Стартапы | RSS. Отсеять: мнения без фактов. Брать: аналитика и крупные сделки. |
| 17 | A | [VentureBeat](https://venturebeat.com) | EN | AI/Enterprise/Игры | RSS по категориям (AI/Enterprise). Отсеять: игры. Брать: AI-исследования/enterprise tech. |
| 18 | B | [3DNews](https://3dnews.ru) | RU | Железо/Софт/Гаджеты | RSS по категориям (Hardware/Software). Отсеять: скидки/пресс-релизы. Брать: обзоры нового железа и аналитику. |
| 19 | B | [4PDA](https://4pda.to) | RU | Мобильные устройства | RSS. Отсеять: прошивки/моддинг/скидки. Брать: обзоры флагманов/сравнения. |
| 20 | B | [9to5Mac](https://9to5mac.com) | EN | Apple/iOS/macOS | RSS + фильтр по ключевым словам. Отсеять: слухи. Брать: обновления OS и новые продукты. |
| 21 | B | [AnandTech](https://www.anandtech.com) | EN | Глубокие обзоры железа | RSS. Брать: подробные обзоры CPU/GPU/Storage. Лучший для hardware. |
| 22 | B | [DEV.to](https://dev.to) | EN | Программирование/Карьера | ОГРОМНОЙ поток. RSS с фильтром reactions>100. Отсеять: beginner/career. Брать: популярные технические статьи. |
| 23 | B | [Eurogamer](https://www.eurogamer.net) | EN | Игры/Индустрия | Игровые новости и аналитика. |
| 24 | B | [Mozilla Blog](https://blog.mozilla.org) | EN | Firefox/Web standards | RSS полностью. Брать: Firefox updates/web privacy/internet policy. |
| 25 | B | [Notebookcheck](https://www.notebookcheck.net) | EN/DE | Ноутбуки/Смартфоны | RSS. Отсеять: мелкие анонсы. Брать: обзоры с бенчмарками. |
| 26 | B | [OSNews](https://www.osnews.com) | EN | Операционные системы | RSS. Брать: новые OS/обновления/аналитика. |
| 27 | B | [Overclockers.ru](https://overclockers.ru) | RU | Железо/Разгон/Игры | RSS. Отсеять: форум/игры. Брать: обзоры железа/разгон/бенчмарки. |
| 28 | B | [Packet Storm](https://packetstormsecurity.com) | EN | Эксплоиты/Уязвимости | RSS. Отсеять: старые эксплоиты (>30 дней). Брать: новые уязвимости/security tools. |
| 29 | B | [Phoronix](https://www.phoronix.com) | EN | Linux hardware | RSS по категориям. Отсеять: мелкие обновления драйверов. Брать: релизы Mesa/Kernel. |
| 30 | B | [Raspberry Pi News](https://www.raspberrypi.com/news/) | EN | Raspberry Pi/Embedded | RSS полностью. Мало но качественно. Брать: новые продукты/проекты. |
| 31 | B | [Reddit r/programming](https://reddit.com/r/programming) | EN | Программирование | RSS с фильтром upvotes>500. Отсеять: мемы/холивары. Брать: крупные релизы. |
| 32 | B | [Rock Paper Shotgun](https://www.rockpapershotgun.com) | EN | Игры/PC | Авторский игровой блог о PC. |
| 33 | B | [Tech.eu](https://tech.eu) | EN | Европейские стартапы | RSS. Отсеять: мелкие funding rounds. Брать: крупные сделки/европейские тренды. |
| 34 | B | [The Verge](https://www.theverge.com) | EN | Поп-культура/Tech | RSS с фильтрацией. Отсеять: стриминги/развлечения. Брать: tech policy и AI-новости. |
| 35 | B | [Tom's Hardware](https://www.tomshardware.com) | EN | Железо/Обзоры | RSS по категориям (CPU/GPU). Отсеять: deals. Брать: обзоры нового железа и бенчмарки. |
| 36 | B | [ZDNET](https://www.zdnet.com) | EN | Enterprise/Cloud/AI | RSS с фильтрацией. Отсеять: sponsored. Брать: enterprise news и cloud computing. |
| 37 | B | [Игромания](https://www.igromania.ru) | RU | Игры/Новости | RU-новости игр. |
| 38 | B | [Хайтек+](https://hightech.plus) | RU | Технологии/Наука | RSS. Отсеять: deals/пресс-релизы. Брать: наука/гаджеты/космос/IT-аналитика. |
| 39 | B | [Хакер (xakep.ru)](https://xakep.ru) | RU | Хакинг/Безопасность/DIY | RSS. Отсеять: статьи >30 дней. Брать: уязвимости/security tools/DIY hardware. |
| 40 | C | [Android Central](https://androidcentral.com) | EN | Android/Мобильные | RSS с фильтрацией. Отсеять: how-to/аксессуары. Брать: глобальные обновления Android. |
| 41 | C | [Android Police](https://www.androidpolice.com) | EN | Android/Google | RSS. Отсеять: app reviews/how-to. Брать: обновления Android/Google анонсы. |
| 42 | C | [CNET](https://www.cnet.com) | EN | Обзоры/Tech новости | МНОГО шума. Жёсткая фильтрация. Отсеять: deals/how-to/sponsored. Брать: крупные анонсы. |
| 43 | C | [Engadget](https://www.engadget.com) | EN | Гаджеты/Tech | RSS с фильтрацией. Отсеять: скидки/how-to/игры. Брать: крупные анонсы. |
| 44 | C | [Futurism](https://futurism.com) | EN | Наука/AI/Космос | RSS. Отсеять: clickbait. Брать: AI-новости/космос/научные открытия. |
| 45 | C | [GamingOnLinux](https://www.gamingonlinux.com) | EN | Игры/Linux | Игры на Linux/Steam Deck/Proton. |
| 46 | C | [Rozetked](https://rozetked.me) | RU | Гаджеты/Железо | HTML-парсинг. Отсеять: short-новости/слухи. Брать: обзоры флагманов. |
| 47 | C | [Silicon Republic](https://www.siliconrepublic.com) | EN | Технологии/Стартапы | RSS. Отсеять: career advice/events. Брать: tech новости/анонсы. |
| 48 | C | [Windows Central](https://www.windowscentral.com) | EN | Microsoft/Windows/Xbox | RSS по категориям. Отсеять: deals/gaming. Брать: Windows updates/Surface. |
| 49 | C | [XDA Developers](https://www.xda-developers.com) | EN | Android/Моддинг | RSS. Отсеять: how-to/custom ROM. Брать: крупные анонсы Android. |
| 50 | D | [GadgetMatch](https://www.gadgetmatch.com) | EN | Гаджеты | HTML-парсинг. Низкий приоритет — дублирует другие источники. |
| 51 | D | [Mashable](https://mashable.com) | EN | Поп-культура/Tech | МНОГО шума мало ценности. Жёсткая фильтрация. Отсеять: мемы/viral. Брать: редко — крупные события. |

### Telegram-каналы

| Канал | Целевая тема | Подпись |
|-------|--------------|---------|
| [@NewAITracker](https://t.me/NewAITracker) | Нейросети | Sponsored by @NewAITracker |
