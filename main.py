#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
media-watcher — main.py

FTPRush-Struktur:
  incoming/
    Filme/
      Movie.Name.2024/              <- release_dir (Arbeitsordner)
        [VOLLSTÄNDIG 26F]           <- CRC-Signal (Trigger, wird sofort gelöscht)
        movie.name.2024.rar
        movie.name.2024.r00 ...
        movie.name.2024.sfv
        subs/
          subs.rar
          subs.sfv

Pipeline:
  1. CRC-Ordner löschen
  2. Subs entpacken  (subs/*.rar -> subs/, nur DE/Forced behalten)
  3. Main-RAR entpacken
  4. Cleanup         (RAR, SFV, NFO, Bilder, Dot-Files weg)
  4b.x265-Konvertierung via FFmpeg (HEVC wird übersprungen)
  5. Filebot         (--output Outgoing/Release.Name/)
  6. Outgoing nach Plex verschieben
  7. Outgoing-Unterordner + leerer Release-Ordner aufräumen

Aufruf:
    python main.py              # nutzt DEBUG / DRY_RUN aus config.py
    python main.py --dry-run    # erzwingt Dry-Run unabhängig von config
"""

import argparse
import glob
import logging
import os
import platform
import re
import shutil
import subprocess as _sp
import sys
import time
from datetime import datetime
from pathlib import Path

import rarfile
import requests
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

import config


# ── CLI-Argumente ──────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="Media Watcher")
parser.add_argument("--dry-run", action="store_true",
                    help="Kein Entpacken / Löschen / Verschieben")
ARGS = parser.parse_args()

DRY_RUN = ARGS.dry_run or config.DRY_RUN
DEBUG   = config.DEBUG


# ── Plattform ──────────────────────────────────────────────────────────────────
IS_WINDOWS  = platform.system() == "Windows"
UNRAR_BIN   = config.UNRAR_BIN_WIN   if IS_WINDOWS else config.UNRAR_BIN_UNIX
FILEBOT_BIN = config.FILEBOT_BIN_WIN if IS_WINDOWS else config.FILEBOT_BIN_UNIX

rarfile.UNRAR_TOOL = UNRAR_BIN


# ── Logging ────────────────────────────────────────────────────────────────────
def _setup_logging() -> logging.Logger:
    log_dir = Path(config.LOG_DIR)
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        log_dir = Path(".")

    today    = datetime.now().strftime("%d-%m-%Y")
    log_file = log_dir / f"watcher_{today}.log"
    err_file = log_dir / f"watcher_error_{today}.log"

    fmt     = "%(asctime)s [%(levelname)s] %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    logger = logging.getLogger("watcher")
    logger.setLevel(logging.DEBUG if DEBUG else logging.INFO)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.DEBUG if DEBUG else logging.INFO)
    ch.setFormatter(logging.Formatter(fmt, datefmt))
    logger.addHandler(ch)

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG if DEBUG else logging.INFO)
    fh.setFormatter(logging.Formatter(fmt, datefmt))
    logger.addHandler(fh)

    eh = logging.FileHandler(err_file, encoding="utf-8")
    eh.setLevel(logging.ERROR)
    eh.setFormatter(logging.Formatter(fmt, datefmt))
    logger.addHandler(eh)

    return logger


log = _setup_logging()

if DRY_RUN:
    log.info("=== DRY-RUN MODUS AKTIV — keine destruktiven Aktionen ===")


# ── Telegram ───────────────────────────────────────────────────────────────────
def telegram(msg: str) -> None:
    if not config.TELEGRAM_ENABLED:
        return
    try:
        url = (f"https://api.telegram.org/bot{config.TELEGRAM_BOT_ID}"
               f"/sendMessage?chat_id={config.TELEGRAM_CHAN_ID}&text={msg}")
        requests.post(url, timeout=10)
        log.debug(f"Telegram gesendet: {msg}")
    except Exception as exc:
        log.warning(f"Telegram fehlgeschlagen: {exc}")


# ── Hilfsfunktionen ────────────────────────────────────────────────────────────
def _run(cmd: list[str], cwd: str | None = None) -> int:
    log.debug(f"CMD: {' '.join(cmd)}" + (f"  (cwd={cwd})" if cwd else ""))
    if DRY_RUN:
        log.info(f"[DRY-RUN] würde ausführen: {' '.join(cmd)}")
        return 0
    result = _sp.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.stdout.strip():
        log.debug(f"STDOUT: {result.stdout.strip()}")
    if result.stderr.strip():
        log.debug(f"STDERR: {result.stderr.strip()}")
    return result.returncode


def _remove(path: Path) -> None:
    log.debug(f"Lösche: {path}")
    if DRY_RUN:
        log.info(f"[DRY-RUN] würde löschen: {path}")
        return
    try:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)
    except OSError as exc:
        log.error(f"Fehler beim Löschen von {path}: {exc}")


def _move(src: Path, dst: Path) -> None:
    log.info(f"Verschiebe: {src}  ->  {dst}")
    if DRY_RUN:
        log.info(f"[DRY-RUN] würde verschieben: {src}  ->  {dst}")
        return
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
    except OSError as exc:
        log.error(f"Fehler beim Verschieben {src} -> {dst}: {exc}")
        raise


# ── Schritt 0: Startup-Scan ────────────────────────────────────────────────────
def startup_scan() -> None:
    """
    Einmaliger Scan beim Start — verarbeitet bereits vorhandene
    [VOLLSTÄNDIG ...]-Ordner die während eines Absturzes verpasst wurden.
    """
    log.info("Startup-Scan: Suche nach verpassten Releases...")
    watch_root = Path(config.WATCH_ROOT)
    found = 0

    for section in config.WATCH_SECTIONS:
        section_dir = watch_root / section
        if not section_dir.is_dir():
            continue

        for release_dir in section_dir.iterdir():
            if not release_dir.is_dir():
                continue

            for sub in release_dir.iterdir():
                if sub.is_dir() and config.COMPLETE_MARKER.lower() in sub.name.lower():
                    log.info(f"Startup-Scan gefunden: [{section}] {release_dir.name}")
                    found += 1
                    time.sleep(config.COMPLETE_SETTLE_TIME)
                    process_release(release_dir, sub, section)
                    break

    if found == 0:
        log.info("Startup-Scan: Nichts gefunden, alles sauber.")
    else:
        log.info(f"Startup-Scan: {found} Release(s) nachverarbeitet.")


# ── Schritt 1: CRC-Ordner entfernen ───────────────────────────────────────────
def remove_crc_dir(crc_path: Path) -> None:
    log.info(f"Entferne CRC-Ordner: {crc_path.name}")
    _remove(crc_path)


# ── Schritt 2 + 3: Entpacken ──────────────────────────────────────────────────
def _unrar_python(rar_path: Path, dest: Path) -> bool:
    try:
        log.debug(f"rarfile entpackt: {rar_path}")
        if not DRY_RUN:
            with rarfile.RarFile(str(rar_path)) as rf:
                rf.extractall(str(dest))
        return True
    except Exception as exc:
        log.warning(f"rarfile Fehler ({rar_path.name}): {exc} — versuche CLI-Fallback")
        return False


def _unrar_cli(rar_path: Path, dest: Path) -> bool:
    rc = _run([UNRAR_BIN, "x", "-inul", "-y", str(rar_path), str(dest)])
    if rc != 0:
        log.error(f"unrar CLI ebenfalls fehlgeschlagen für {rar_path.name}")
        return False
    return True


def unpack_rar(rar_path: Path, dest: Path) -> bool:
    log.info(f"Entpacke: {rar_path.name}  ->  {dest}")
    if not _unrar_python(rar_path, dest):
        return _unrar_cli(rar_path, dest)
    return True


def unpack_subs(release_dir: Path) -> None:
    """Entpackt RARs im subs/-Unterordner, behält nur DE/Forced Subs."""
    subs_dir = release_dir / "subs"
    if not subs_dir.is_dir():
        subs_dir = release_dir / "Subs"
        if not subs_dir.is_dir():
            log.debug(f"Kein subs/-Ordner: {release_dir.name}")
            return

    log.info(f"Entpacke Subs: {subs_dir}")
    for rar in sorted(subs_dir.glob("*.rar")):
        unpack_rar(rar, subs_dir)

    keep_patterns = [p.lower() for p in config.SUBS_KEEP_PATTERNS]
    for f in subs_dir.iterdir():
        if not f.is_file():
            continue
        if f.suffix.lower() in {".rar", ".sfv", ".nfo"}:
            _remove(f)
            continue
        name_lower = f.name.lower()
        if not any(p in name_lower for p in keep_patterns):
            log.debug(f"Sub nicht gewünscht, entferne: {f.name}")
            _remove(f)
        else:
            log.debug(f"Sub behalten: {f.name}")


def unpack_release(release_dir: Path) -> bool:
    """Entpackt Haupt-RAR. part01.rar bevorzugt, sonst erstes RAR."""
    rars = sorted(release_dir.glob("*.rar"))
    if not rars:
        log.warning(f"Keine RAR-Dateien in: {release_dir.name}")
        return False
    main_rar = next(
        (r for r in rars if re.search(r"part0?1\.rar$", r.name, re.IGNORECASE)),
        rars[0]
    )
    return unpack_rar(main_rar, release_dir)


# ── Schritt 4: Cleanup ────────────────────────────────────────────────────────
def cleanup(release_dir: Path) -> None:
    """Entfernt Archive, SFV, NFO, Bilder, Dot-Files. Behält MKV und subs/."""
    log.info(f"Cleanup: {release_dir.name}")

    for root, dirs, files in os.walk(release_dir, topdown=False):
        root_path = Path(root)

        # CRC-Ordner nicht nochmal anfassen
        dirs[:] = [d for d in dirs
                   if config.COMPLETE_MARKER.lower() not in d.lower()]

        for d in dirs:
            if d.lower() in config.CLEANUP_DIRS:
                _remove(root_path / d)

        for fname in files:
            fpath = root_path / fname
            lower = fname.lower()
            try:
                is_zero = fpath.stat().st_size == 0
            except OSError:
                is_zero = False
            is_trash = (
                any(lower.endswith(ext) for ext in config.CLEANUP_EXTENSIONS)
                or fname.startswith(".")
                or is_zero
                or fname.endswith("-missing")
                or fname.endswith("-bad")
            )
            if is_trash:
                _remove(fpath)

    for pattern in config.CLEANUP_GLOB_PATTERNS:
        for fpath in glob.glob(str(release_dir / pattern)):
            _remove(Path(fpath))

    for subdir in release_dir.iterdir():
        if subdir.is_dir() and subdir.name.lower() != "subs":
            try:
                if not any(subdir.iterdir()):
                    _remove(subdir)
            except OSError:
                pass


# ── Schritt 4b: x265-Konvertierung ───────────────────────────────────────────
def convert_to_x265(release_dir: Path, section: str) -> bool:
    """
    Konvertiert alle MKV/MP4/AVI in release_dir nach x265.
    Bereits HEVC-Dateien werden übersprungen.
    Original wird nach Erfolg gelöscht, x265-Datei bekommt den Originalnamen.
    """
    if not config.FFMPEG_ENABLED or section not in config.FFMPEG_SECTIONS:
        return True

    video_exts = {".mkv", ".mp4", ".avi"}
    files = [f for f in release_dir.rglob("*") if f.suffix.lower() in video_exts]

    if not files:
        log.warning(f"x265: Keine Videodateien gefunden in {release_dir.name}")
        return True

    for src in files:
        try:
            probe = _sp.run(
                [config.FFPROBE_BIN, "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(src)],
                capture_output=True, text=True, timeout=30
            )
            codec = probe.stdout.strip().lower()
        except Exception as exc:
            log.error(f"ffprobe Fehler bei {src.name}: {exc}")
            return False

        if codec == "hevc":
            log.info(f"x265: bereits HEVC, überspringe {src.name}")
            continue

        log.info(f"x265: Konvertiere {src.name}  (codec={codec})")

        tmp_out = src.with_suffix(".x265_tmp.mkv")

        if DRY_RUN:
            log.info(f"[DRY-RUN] würde konvertieren: {src.name} -> {tmp_out.name}")
            continue

        rc = _run([
            config.FFMPEG_BIN, "-hide_banner", "-nostats", "-nostdin",
            "-i", str(src),
            "-c:v", "libx265",
            "-preset", config.FFMPEG_PRESET,
            "-crf", str(config.FFMPEG_CRF),
            "-c:a", "copy",
            "-c:s", "copy",
            "-threads", str(config.FFMPEG_THREADS),
            str(tmp_out)
        ])

        if rc != 0 or not tmp_out.exists():
            log.error(f"x265: FFmpeg fehlgeschlagen für {src.name}")
            _remove(tmp_out)
            return False

        _remove(src)
        tmp_out.rename(src)
        log.info(f"x265: Fertig -> {src.name}")

    return True


# ── Schritt 5: Filebot ────────────────────────────────────────────────────────
def run_filebot(release_dir: Path, section: str) -> Path | None:
    """
    Startet Filebot mit --output in einen release-isolierten Outgoing-Unterordner.
    Gibt den Outgoing-Unterordner zurück (auch im Dry-Run zur Simulation).
    Gibt None zurück bei Fehler.
    """
    db = "TheMovieDB" if section in config.MOVIEDB_SECTIONS else "TheTVDB"

    outgoing_release = Path(config.FILEBOT_OUTGOING) / release_dir.name

    if not DRY_RUN:
        outgoing_release.mkdir(parents=True, exist_ok=True)
    else:
        log.info(f"[DRY-RUN] würde erstellen: {outgoing_release}")

    cmd = [
        FILEBOT_BIN, "-rename", str(release_dir),
        "--db", db,
        "--lang", config.FILEBOT_LANG,
        "--format", config.FILEBOT_FORMAT,
        "--output", str(outgoing_release),
        "-r",
        "-non-strict",
    ]

    log.info(f"Filebot: {release_dir.name}  (db={db})")
    rc = _run(cmd)

    if rc != 0:
        log.error(f"Filebot fehlgeschlagen für {release_dir.name} (rc={rc})")
        return None

    return outgoing_release


# ── Schritt 6 + 7: Verschieben + Aufräumen ────────────────────────────────────
def move_to_plex(outgoing_release: Path, release_dir: Path, section: str) -> None:
    dest_root = config.DESTINATIONS.get(section)
    if not dest_root:
        msg = f"Kein Ziel-Alias für Section '{section}' — {release_dir.name} bleibt liegen"
        log.error(msg)
        telegram(f"[media-watcher] {msg}")
        return

    if DRY_RUN:
        log.info(f"[DRY-RUN] würde Outgoing scannen: {outgoing_release}")
        log.info(f"[DRY-RUN] würde verschieben nach: {dest_root}")
        return

    if not outgoing_release.exists():
        msg = f"Outgoing-Ordner fehlt nach Filebot: {outgoing_release}"
        log.error(msg)
        telegram(f"[media-watcher] {msg}")
        return

    # Filebot legt Movies\ oder TV Shows\ als Zwischenebene an
    # -> eine Ebene tiefer gehen und deren Inhalt verschieben
    moved = 0
    for subdir in outgoing_release.iterdir():
        if not subdir.is_dir():
            continue
        for item in subdir.iterdir():
            dest = Path(dest_root) / item.name
            try:
                _move(item, dest)
                log.info(f"[OK] {item.name}  ->  {dest}")
                moved += 1
            except OSError as exc:
                msg = f"Verschieben fehlgeschlagen: {item.name} -> {dest}: {exc}"
                log.error(msg)
                telegram(f"[media-watcher] {msg}")

    if moved == 0:
        msg = f"Filebot hat nichts umbenannt für: {release_dir.name}"
        log.error(msg)
        telegram(f"[media-watcher] {msg}")

    _remove(outgoing_release)

    try:
        remaining = list(release_dir.iterdir())
        if not remaining:
            _remove(release_dir)
            log.debug(f"Leerer Release-Ordner entfernt: {release_dir.name}")
        else:
            log.warning(f"Release-Ordner nicht leer: {[f.name for f in remaining]}")
    except OSError:
        pass


# ── Haupt-Pipeline ─────────────────────────────────────────────────────────────
def process_release(release_dir: Path, crc_dir: Path, section: str) -> None:
    name = release_dir.name
    log.info(f"{'='*60}")
    log.info(f"Verarbeite: [{section}] {name}")
    log.info(f"{'='*60}")

    if any(kw in name.lower() for kw in config.IGNORE_DIRS):
        log.info(f"Ignoriert (IGNORE_DIRS): {name}")
        return

    try:
        # 1. CRC-Ordner sofort wegräumen
        remove_crc_dir(crc_dir)

        # 2. Subs entpacken + filtern
        unpack_subs(release_dir)

        # 3. Main-RAR entpacken
        if not unpack_release(release_dir):
            msg = f"Entpacken fehlgeschlagen: {name}"
            log.error(msg)
            telegram(f"[media-watcher] {msg}")
            return

        # 4. Cleanup
        cleanup(release_dir)

        # 4b. x265-Konvertierung
        if not convert_to_x265(release_dir, section):
            msg = f"x265-Konvertierung fehlgeschlagen: {name}"
            log.error(msg)
            telegram(f"[media-watcher] {msg}")
            return

        # 5. Filebot -> Outgoing/Release.Name/
        outgoing_release = run_filebot(release_dir, section)
        if outgoing_release is None:
            msg = f"Filebot fehlgeschlagen: {name}"
            log.error(msg)
            telegram(f"[media-watcher] {msg}")
            return

        # 6. Outgoing nach Plex + 7. Aufräumen
        move_to_plex(outgoing_release, release_dir, section)

    except Exception as exc:
        msg = f"Unbehandelte Exception bei {name}: {exc}"
        log.exception(msg)
        telegram(f"[media-watcher] {msg}")


# ── Watchdog Event-Handler ─────────────────────────────────────────────────────
class ReleaseHandler(FileSystemEventHandler):
    """
    Reagiert auf Ordner-Events unterhalb WATCH_ROOT.
    Trigger: Unterordner dessen Name COMPLETE_MARKER enthält.

    Erwartete Struktur:
      incoming/Filme/Movie.Name.2024/[VOLLSTÄNDIG 26F]
                     ^^^^^^^^^^^^^^^ release_dir
                                     ^^^^^^^^^^^^^^^^^ crc_dir (Trigger)
    """

    def __init__(self) -> None:
        super().__init__()
        self._processed: set[str] = set()

    def on_created(self, event) -> None:
        if not event.is_directory:
            return
        self._check(Path(event.src_path))

    def on_moved(self, event) -> None:
        if not event.is_directory:
            return
        self._check(Path(event.dest_path))

    def _check(self, crc_path: Path) -> None:
        folder_name = crc_path.name
        log.debug(f"Ordner-Event: {crc_path}")

        if config.COMPLETE_MARKER.lower() not in folder_name.lower():
            return

        release_dir = crc_path.parent

        section = self._resolve_section(release_dir)
        if not section:
            log.debug(f"Keine passende Section für: {release_dir}")
            return

        dedup_key = str(release_dir)
        if dedup_key in self._processed:
            log.debug(f"Bereits verarbeitet, skip: {release_dir.name}")
            return
        self._processed.add(dedup_key)

        log.info(f"CRC-Complete erkannt: {folder_name}")
        log.info(f"Release: {release_dir.name}  |  Section: {section}")

        time.sleep(config.COMPLETE_SETTLE_TIME)

        process_release(release_dir, crc_path, section)

    def _resolve_section(self, path: Path) -> str | None:
        """Section = direkter Unterordner von WATCH_ROOT."""
        watch_root = Path(config.WATCH_ROOT)
        try:
            rel = path.relative_to(watch_root)
            section = rel.parts[0]
            if section in config.WATCH_SECTIONS:
                return section
        except (ValueError, IndexError):
            pass
        return None


# ── Watcher starten ────────────────────────────────────────────────────────────
def main() -> None:
    watch_root = Path(config.WATCH_ROOT)
    if not watch_root.exists():
        log.error(f"WATCH_ROOT existiert nicht: {watch_root}")
        sys.exit(1)

    outgoing = Path(config.FILEBOT_OUTGOING)
    if not DRY_RUN:
        outgoing.mkdir(parents=True, exist_ok=True)

    log.info(f"Media-Watcher gestartet — Root: {watch_root}")
    log.info(f"Outgoing:  {outgoing}")
    log.info(f"Sections:  {config.WATCH_SECTIONS}")
    log.info(f"Debug={DEBUG}  DryRun={DRY_RUN}")

    handler = ReleaseHandler()

    startup_scan()

    try:
        observer = Observer()
        observer.schedule(handler, str(watch_root), recursive=True)
        log.info("Verwende nativen Observer")
    except Exception:
        observer = PollingObserver(timeout=config.POLL_INTERVAL)
        observer.schedule(handler, str(watch_root), recursive=True)
        log.info("Verwende Polling-Observer (Netzlaufwerk/Fallback)")

    observer.start()
    log.info("Watcher läuft. STRG+C zum Beenden.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("Beende Watcher...")
        observer.stop()
    observer.join()
    log.info("Watcher beendet.")


if __name__ == "__main__":
    main()