# -*- coding: utf-8 -*-
# config.py — Media Watcher Konfiguration
# DEBUG=True      -> alles wird geloggt, kein Dry-Run zwang
# DRY_RUN=True    -> keine destruktiven Aktionen (löschen/verschieben/entpacken)
# CLI-Flag --dry-run überschreibt DRY_RUN unabhängig von DEBUG

# ── Betrieb ────────────────────────────────────────────────────────────────────
DEBUG   = True
DRY_RUN = True   # auf False setzen wenn produktiv

# ── Pfade ──────────────────────────────────────────────────────────────────────
# Eingehende Downloads (FTPRush Zielordner)
# Windows-Beispiel: "D:\\Downloads\\"
# Linux-Beispiel:   "/opt/Downloads/"
WATCH_ROOT = "D:\\Downloads\\Incoming\\"
FILEBOT_OUTGOING = "D:\\Downloads\\Outgoing\\"

# Überwachte Unterordner (genau so benennen wie FTPRush sie ablegt)
WATCH_SECTIONS = ["Filme", "Filme-4K", "Serien", "Dokus"]

# Ziel-Aliase nach Filebot (Section -> finales Plex-Verzeichnis)
# Windows: "//nas/plex/Filme"
# Linux:   "/mnt/plex/Filme"
DESTINATIONS = {
    "Filme":    r"\\NAS/Filme/Movies/",
    "Filme-4K": r"\\NAS/Filme-4K/Movies/",
    "Serien":   r"\\NAS/Serien/TV Shows/",
    "Dokus":    r"\\NAS/Dokus/TV Shows/",
}

# ── Binaries ───────────────────────────────────────────────────────────────────
# Windows
UNRAR_BIN_WIN   = "C:\\Program Files\\WinRAR\\unRAR.exe"
RAR_BIN_WIN     = "C:\\Program Files\\WinRAR\\RAR.exe"
FILEBOT_BIN_WIN = "C:\\Program Files\\Filebot\\filebot.exe"

# Linux / macOS
UNRAR_BIN_UNIX   = "/usr/bin/unrar"
RAR_BIN_UNIX     = "/usr/bin/rar"
FILEBOT_BIN_UNIX = "/usr/bin/filebot"

# ── Filebot ────────────────────────────────────────────────────────────────────
FILEBOT_LANG   = "de"
FILEBOT_FORMAT = "{plex}"   # Plex-kompatibles Namensschema

# ── FFmpeg / x265 ──────────────────────────────────────────────────────────────
FFMPEG_ENABLED  = True
FFMPEG_BIN      = "ffmpeg"       # im PATH, oder Vollpfad: "C:\\ffmpeg\\bin\\ffmpeg.exe"
FFPROBE_BIN     = "ffprobe"
FFMPEG_PRESET   = "medium"
FFMPEG_CRF      = 23
FFMPEG_THREADS  = 4

# Sections die konvertiert werden sollen
FFMPEG_SECTIONS = ["Filme", "Filme-4K", "Serien", "Dokus"]

# Sections die TheMovieDB nutzen (alles andere -> TheTVDB)
MOVIEDB_SECTIONS = ["Filme", "Filme-4K"]

# ── Logging ────────────────────────────────────────────────────────────────────
# Windows-Beispiel: "M:\\Logs\\"
# Linux-Beispiel:   "/var/log/media-watcher/"
LOG_DIR = "C:\\bin\\watch_and_process\\logs"

# ── Telegram ───────────────────────────────────────────────────────────────────
# Nur bei harten Fehlern / nicht zuordenbaren Releases
TELEGRAM_ENABLED = False
TELEGRAM_BOT_ID  = "ABCD"
TELEGRAM_CHAN_ID  = "-1001234567890"

# ── Watcher ────────────────────────────────────────────────────────────────────
# Polling-Intervall in Sekunden (watchdog fallback)
POLL_INTERVAL = 5

# Wie lange warten nachdem [VOLLSTÄNDIG ...] erkannt wurde (Sekunden)
# Puffer damit FTPRush den letzten Block wirklich geschlossen hat
COMPLETE_SETTLE_TIME = 3

# FTPRush CRC-Check Prefix (case-insensitive enthält-Prüfung)
COMPLETE_MARKER = "[VOLLSTÄNDIG"

# Subs die behalten werden wenn "subs" im Release-Name vorkommt (case-insensitive enthält-Prüfung)
SUBS_KEEP_PATTERNS = ["forced", "deutsch", "german", ".de.", "_de_", ".ger.", "_ger_"]

# Ordner die grundsätzlich ignoriert werden (auch als Release-Name)
IGNORE_DIRS = {"proof", "sample", "subs"}

# Dateierweiterungen die nach dem Entpacken gelöscht werden
CLEANUP_EXTENSIONS = {".rar", ".sfv", ".nfo", ".nzb", ".jpg",
                      ".jpeg", ".png", ".diz", ".chk"}
CLEANUP_GLOB_PATTERNS = ["*.r[0-9][0-9]", "*.s[0-9][0-9]", "*.t[0-9][0-9]"]

# Unterordner die nach dem Cleanup gelöscht werden
CLEANUP_DIRS = {"proof", "sample", "covers"}
