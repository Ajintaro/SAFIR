"""
SAFIR Surface — Omnikey RFID Reader Loop

Pollt einen am Surface angeschlossenen PC/SC Smart-Card-Reader (typisch:
HID Omnikey 5022, 5027, 5321, etc.) und feuert ein Callback pro gelesener
UID. Die UID wird als Hex-String (z.B. "8AEF10C3") weitergegeben — das
matchen wir serverseitig gegen ``patient["rfid_tag_id"]``.

Wir nutzen PC/SC via ``pyscard``. Auf Windows ist PC/SC nativ verfügbar,
``pyscard`` liefert Wheels via ``pip install pyscard``. Linux braucht
``pcscd`` + ``libpcsclite-dev``.

Das Modul ist **absichtlich defensiv**: Wenn pyscard fehlt oder kein
Reader angeschlossen ist, loggt es einmal eine Warnung und tut sonst
nichts — der Backend-Boot bricht nie.

Aufruf-Konvention:

    from backend.omnikey_reader import start_reader_loop
    asyncio.create_task(start_reader_loop(on_uid_callback))

``on_uid_callback`` ist ein async-Funktion die genau ein Argument bekommt:
den UID-Hex-String.
"""

import asyncio
import logging
from typing import Awaitable, Callable, Optional

log = logging.getLogger("safir.omnikey")

UidCallback = Callable[[str], Awaitable[None]]


# Debounce: Wenn dieselbe Karte liegen bleibt, feuern wir sie nur einmal.
# Erst wenn die Karte entfernt UND eine neue gelegt wird (oder 5 s Pause),
# feuert das Callback wieder.
_DEBOUNCE_SECONDS = 2.5

# Poll-Intervall für die PC/SC State-Abfrage
_POLL_INTERVAL = 0.25


def _apdu_get_uid() -> list[int]:
    """PC/SC APDU das bei fast allen PC/SC-Readern die Card-UID liefert.
    FF CA 00 00 00 — "Get Data: UID", Response = UID-Bytes + SW1 SW2."""
    return [0xFF, 0xCA, 0x00, 0x00, 0x00]


async def start_reader_loop(on_uid: UidCallback) -> None:
    """
    Hauptschleife: verbindet sich zum PC/SC Subsystem, wartet auf
    Card-Events, liest UID, feuert ``on_uid``. Läuft endlos — als
    asyncio.Task starten.

    Die eigentliche PC/SC-API (smartcard.*) ist synchron und blockiert.
    Wir rufen sie deshalb über ``loop.run_in_executor`` auf damit der
    FastAPI-Event-Loop frei bleibt.
    """
    try:
        from smartcard.System import readers as _list_readers
        from smartcard.Exceptions import NoCardException, CardConnectionException
        from smartcard.util import toHexString
    except ImportError as e:
        log.warning(
            "pyscard nicht installiert — Omnikey-Reader deaktiviert. "
            "Auf Windows: pip install pyscard. "
            f"(Import-Fehler: {e})"
        )
        return

    loop = asyncio.get_event_loop()
    last_uid: Optional[str] = None
    last_uid_time = 0.0
    current_reader_name: Optional[str] = None
    reader_obj = None  # smartcard.readers.Reader — typed loose

    def _find_reader():
        """Gibt den ersten verfügbaren Reader oder None zurück."""
        try:
            rs = _list_readers()
            if not rs:
                return None
            return rs[0]
        except Exception as ex:
            log.debug(f"Reader-Liste nicht verfügbar: {ex}")
            return None

    def _try_read_uid(reader):
        """Versucht eine Karte zu lesen. Gibt UID-Hex-String oder None.

        Exceptions werden geschluckt (keine Karte = kein Fehler).
        """
        try:
            conn = reader.createConnection()
            conn.connect()
            try:
                data, sw1, sw2 = conn.transmit(_apdu_get_uid())
                if sw1 == 0x90 and sw2 == 0x00 and data:
                    uid = "".join(f"{b:02X}" for b in data)
                    return uid
                return None
            finally:
                try:
                    conn.disconnect()
                except Exception:
                    pass
        except NoCardException:
            return None
        except CardConnectionException:
            return None
        except Exception as ex:
            log.debug(f"Read-UID Fehler: {ex}")
            return None

    log.info("Omnikey Reader-Loop gestartet — suche nach PC/SC Reader …")

    while True:
        try:
            # Reader finden / neu finden wenn weg
            if reader_obj is None:
                reader_obj = await loop.run_in_executor(None, _find_reader)
                if reader_obj is not None:
                    new_name = str(reader_obj)
                    if new_name != current_reader_name:
                        log.info(f"Omnikey Reader gefunden: {new_name}")
                        current_reader_name = new_name
                else:
                    # Noch kein Reader — nicht spammen, alle 5 s suchen
                    await asyncio.sleep(5.0)
                    continue

            # Poll: UID lesen versuchen
            uid = await loop.run_in_executor(None, _try_read_uid, reader_obj)

            now = loop.time()
            if uid is None:
                # Keine Karte aufgelegt — Debounce nach 5 s zurücksetzen
                if last_uid is not None and (now - last_uid_time) > 5.0:
                    last_uid = None
            else:
                # Karte gelesen — Debounce-Check
                if uid != last_uid or (now - last_uid_time) > _DEBOUNCE_SECONDS:
                    last_uid = uid
                    last_uid_time = now
                    log.info(f"Omnikey-Scan: UID {uid}")
                    try:
                        await on_uid(uid)
                    except Exception as cb_err:
                        log.error(f"on_uid Callback-Fehler: {cb_err}")
                else:
                    # Gleiche Karte noch im Debounce-Fenster
                    last_uid_time = now

            await asyncio.sleep(_POLL_INTERVAL)

        except asyncio.CancelledError:
            log.info("Omnikey Reader-Loop beendet")
            raise
        except Exception as ex:
            log.error(f"Omnikey Reader-Loop Fehler — Reader resetten: {ex}")
            reader_obj = None
            current_reader_name = None
            await asyncio.sleep(2.0)
