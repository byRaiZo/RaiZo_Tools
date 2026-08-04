# RaiZo Tools

Windows-приложение для локальной разработки DayZ: запуск сервера и клиента,
пресеты, моды, миссии, CFG, логи и сборка PBO.

Проект основан на полном коде
[KR_QTS](https://github.com/KRdayzmodding/KR_QTS) ревизии
`3be692cb37b7e33686cd00e272280c87e075a086`.

Отличия RaiZo Tools:

- нет рабочей папки `KR_Debug`;
- конфиги, `profiles`, `mpmissions`, `MODS` и `keys` используются прямо в
  корне DayZ Server;
- автоматически создаётся только `DayZServer\MODS`;
- `storage_*` всегда сохраняется при обновлении миссии;
- Mikero/pboProject заменён встроенным PBO Builder byRaiZo;
- настройки находятся в `%LOCALAPPDATA%\RaiZo_Tools`;
- EXE называется `RaiZoTools.exe`.

## Запуск и сборка

```powershell
pip install -r requirements.txt
python main.py
python tools/build.py --clean
```

Сборка: `dist\RaiZo Tools\RaiZoTools.exe` и один актуальный ZIP.

## Команды и ярлыки пресетов

```powershell
RaiZoTools.exe server start  --preset "Diag" --target server
RaiZoTools.exe server start  --preset "Diag" --target all
RaiZoTools.exe server stop   --preset "Diag" --target all
RaiZoTools.exe server status --preset "Diag" --target all
```

`--target` принимает `server`, `client` или `all`. Ветка берётся из пресета;
при необходимости её можно заменить через `--branch stable|experimental`.
Кнопка с иконкой ссылки рядом с выбором пресета создаёт готовый `.lnk` для
запуска или остановки без консольного окна.

## Лицензия

GPLv3. Уведомления находятся в `THIRD_PARTY_NOTICES.md`.
