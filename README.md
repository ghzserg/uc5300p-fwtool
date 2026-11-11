# uc5300p-fwtool

Распаковка, правка и сборка прошивки видеорегистратора **Urive G600 (UC5300P)** на чипе AIT.
Работает в два этапа и в Docker:

```
stock/UC5300P.bin ──unpack──▶ work/ (папки и файлы, которые можно править) ──pack──▶ release/UC5300P.bin
```

Что можно менять, не трогая код прошивки:

| Что | Где лежит после `unpack` |
|---|---|
| Тексты интерфейса (1053 строки) | `work/app/strings/strings.tsv` |
| Шрифты (7 шт., 14–24 px), каждый глиф PNG-файлом | `work/app/fonts/fontN_NNpx/glyphs/*.png` |
| Таблица «код → символ» | `work/app/charmap.json` |
| Голосовые подсказки (MP3), база камер `rp_cam.idb` | `work/volumes/volN/files/*` |
| Остальное (загрузчики, код приложения) | `work/container/…` как есть, побайтно |

`pack` сам пересчитывает всё, что проверяет устройство: **CRC16 каждого раздела** (его проверяет загрузчик при каждом старте;
несовпадение = регистратор зависает на «CRC check fail») и **MD5 заголовка** (его проверяет код обновления с SD).
Формат описан в [docs/FORMAT.md](docs/FORMAT.md).

> Без правок `unpack` → `pack` даёт **побайтно тот же файл**, что и исходный (проверяется тестом).

## Одна команда: переведённая прошивка

```bash
make ru FW=stock/UC5300P.bin                          # русская прошивка -> release/UC5300P.bin
make ru ENGINE=rhvoice VOICE=anna                     # то же, с выбранным голосом
make ru-novoice                                       # только тексты, без озвучки (быстро, без TTS)

# без Docker
fwtool translate stock/UC5300P.bin release/UC5300P.bin --engine rhvoice --voice anna
```

Команда делает всё сама: распаковывает, применяет оверлей `ru` (тексты, шрифты), озвучивает подсказки выбранным голосом,
собирает прошивку и проверяет её (MD5, CRC16, эмуляция процедуры обновления устройства).
Рабочее дерево по умолчанию временное; чтобы править его руками — `--work work --keep-work` или обычные `unpack`/`pack` ниже.

## Голоса озвучки

Движки выбираются через `--engine` / `ENGINE=`, голос — `--voice` / `VOICE=`. `auto` берёт RHVoice **anna**,
иначе Piper **irina**, иначе eSpeak.

| Движок | Голоса | Заметки |
|---|---|---|
| `rhvoice` | все русские голоса, найденные в системе: в образе из пакета `rhvoice-russian` это `aleksandr`, `aleksandr-hq`, `anna`, `arina`, `artemiy`, `elena`, `evgeniy-rus`, `irina`, `mikhail`, `pavel`, `tatiana`, `victoria`, `vitaliy`, `yuriy` | список берётся из `voice.info` установленных голосов; новые голоса RHVoice положите в `/usr/local/share/RHVoice/voices` или в каталог из `FWTOOL_RHVOICE_DIRS` |
| `piper` | `irina` (жен.), `denis`, `dmitri`, `ruslan`, либо путь к своему `.onnx` | нейросеть, модель скачивается при первом запуске; свои модели — каталог `FWTOOL_PIPER_DIR` |
| `espeak` | `ru`, `ru+f2`, `ru+f3`, `ru+f4`, `ru+m3`, `ru+m5` | роботизированный, запасной вариант |
| `cmd` | любой | `--tts-cmd 'mytts --out {out} --text {text}'`: `{text}` и `{out}` подставляются сами |

Выбрать голос на слух: `make sample` (или `fwtool voices --sample "Переход в режим движения."`) пишет по WAV-файлу
на каждый доступный голос в `voice-samples/`. Список: `make voices`.

## Быстрый старт

Нужны Docker и `make`. Оригинальную прошивку положите в `stock/UC5300P.bin` (в репозиторий она не входит).

```bash
make image                 # собрать Docker-образ
make unpack                # этап 1: stock/UC5300P.bin -> work/
make overlay OVERLAY=ru    # (по желанию) русские тексты и кириллические глифы
make voice ENGINE=rhvoice VOICE=anna   # (по желанию) озвучка, см. «Голоса озвучки»
#   ...правьте файлы в work/ ...
make pack                  # этап 2: work/ -> release/UC5300P.bin + проверки
```

`make pack` запускает три проверки: MD5 и CRC16 разделов (то же, что делает устройство) и **эмуляцию собственной
процедуры обновления из прошивки** (Unicorn): она отвечает, примет ли устройство файл.

Готовый файл — `release/UC5300P.bin` (+ `release/BUILD_INFO.json` с SHA-256).
Выложить на GitHub: `make release TAG=v1.0` (нужен `gh`), либо через workflow `release.yml` по тегу.

### Без Docker

```bash
pip install '.[emulate]'
fwtool unpack stock/UC5300P.bin work
fwtool overlay overlays/ru work
fwtool pack work release/UC5300P.bin --verify --emulate
fwtool info stock/UC5300P.bin          # разделы и тома
fwtool verify some.bin --emulate       # проверить любой файл как устройство
```

## Как прошивать

1. Сохраните оригинальный `UC5300P.bin` отдельно (на ПК и на запасной карте).
2. Положите новый файл **в корень** SD-карты под именем **`UC5300P.bin`**
   (имя зашито в прошивке: `SD:\UC5300P.bin`).
3. Выключите питание, вставьте карту, включите. Не отключайте питание во время обновления.
4. Для отката положите оригинальный файл тем же способом.

⚠️ **Риск.** Модификация прошивки — на вашу ответственность. Если загрузчик не пройдёт CRC раздела, устройство зависнет
и перепрошить его с SD нельзя (код обновления находится в самой прошивке); у многих устройств нет UART. Инструмент
пересчитывает эти значения и проверяет их, но на железе проект не гарантирует успех. Для первой проверки
используйте вариант без изменений кода (только голос или только тексты).

## Правка текстов

`work/app/strings/strings.tsv` — три колонки: `id`, `enc`, `text`.

* `enc=ascii` — обычная латиница; `k2` — строки со «слоговыми» кодами (корейский и всё, что вы добавите);
  `k0` — строки старого 18-пиксельного шрифта (остатки, лучше не трогать).
* Экранирование: `\\` — обратная косая, `\xHH` — сырой байт, `\cAAAA` — двухбайтный код без известного символа.
* Строка меняется — её старое место освобождается, новый текст записывается в свободные области.
  Свободного места мало: **удлинять строки можно только за счёт укорочения/обнуления других**
  (пустой `text` обнуляет строку; в оверлее `ru` так освобождены неиспользуемые меню фотокамеры, id 218–382).
  Если места не хватает, `pack` сообщит об этом.
* Новые символы нужны глифы: в `charmap.json` у каждого слота (код = `0xA1A1 + слот`) записан символ;
  картинка глифа — `glyphs/<код>.png` в каждом шрифте (чёрное = пиксель). Оверлей делает это автоматически
  (рендерит из DejaVu Sans Condensed) и использует слоты корейских слогов, которые больше нигде не нужны.

## Оверлеи

`overlays/<имя>/` — это данные, а не код:

* `overlay.json` — параметры, `strings.tsv` — `id <TAB> новый текст <TAB> справка (оригинал, игнорируется)`,
* `voice.json` — `имя_файла: текст для озвучки` (используется `make voice`).

В `overlays/ru` лежит русификация: 697 строк (всё меню, диалоги, ошибки), 64 голосовые фразы.
Свой язык: скопируйте папку, поправьте тексты, `make overlay OVERLAY=<имя>`.

## Тесты и CI

```bash
make test                                   # юнит-тесты (CRC, FAT, строки, шрифты, контейнер)
FWTOOL_STOCK=stock/UC5300P.bin make test    # + интеграционные на реальной прошивке
```

`.github/workflows/ci.yml` гоняет юнит-тесты. `release.yml` по тегу `v*` собирает `release/UC5300P.bin` из закоммиченного
`work/`, если вы решите его хранить.

## Юридическое

Код проекта — MIT. **Прошивка производителя — чужая интеллектуальная собственность**: в репозиторий она не входит

---

## English summary

`fwtool` unpacks the Urive G600 (UC5300P, AIT SoC) firmware into editable files (UI strings, bitmap fonts as PNG,
voice MP3s, FAT volumes), then repacks it and recomputes the per-section CRC16 (checked by the boot loader) and the
header MD5 (`MD5("VDRAC999" + data[0x20:])`, checked by the on-device updater). Unmodified unpack→pack is byte-identical.
`make unpack`, edit `work/`, `make pack`; the result is `release/UC5300P.bin`. See `docs/FORMAT.md` for the format.
The stock firmware is not included. Use at your own risk - a wrong CRC can brick a device without UART access.
