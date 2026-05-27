# media-watcher

Überwacht Download-Ordner, entpackt Releases nach FTPRush CRC-Bestätigung,
jagt alles durch Filebot und verschiebt ins Plex-Ziel.

## Setup

```bash
pip install -r requirements.txt
```

Externe Binaries (in PATH oder in config.py anpassen):
- `unrar` / `unrar.exe`
- `filebot` / `filebot.exe`

## Konfiguration

`config.py` öffnen und anpassen:
1. `WATCH_ROOT` — FTPRush Download-Zielordner
2. `DESTINATIONS` — Plex-Alias-Pfade pro Section
3. `TELEGRAM_BOT_ID` / `TELEGRAM_CHAN_ID` — Bot-Credentials
4. `UNRAR_BIN_WIN` etc. — Pfade zu Binaries falls nicht in PATH
5. `DEBUG = True/False`
6. `DRY_RUN = True/False`

## Starten

```bash
# Dry-Run (Standard solange DRY_RUN=True in config.py)
python main.py

# Dry-Run erzwingen (unabhängig von config.py)
python main.py --dry-run

# Produktiv (DRY_RUN=False in config.py)
python main.py
```

## Ablauf pro Release

1. FTPRush beendet Download und benennt Ordner: `[VOLLSTÄNDIG 13F] Release.Name`
2. Watcher erkennt COMPLETE_MARKER im Ordnernamen
3. Ordner wird in `Release.Name` umbenannt
4. Subs entpacken (`subs/*.rar` → `subs/`)
5. Haupt-RAR entpacken (part01 bevorzugt, sonst erstes RAR)
6. Cleanup: RAR, SFV, NFO, Bilder, Dot-Files löschen
7. Filebot: Renamen + Subs (`TheMovieDB` oder `TheTVDB` je nach Section)
8. Verschieben nach `DESTINATIONS[section]`
9. Telegram nur bei Fehler

## Logging

Tagesbasierte Logfiles in `LOG_DIR`:
- `watcher_DD-MM-YYYY.log` — alles (DEBUG=True) oder INFO
- `watcher_error_DD-MM-YYYY.log` — nur Fehler
