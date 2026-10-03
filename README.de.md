# Escape the Backrooms Trainer

[简体中文](README.md) | [English](README.en.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | **Deutsch** | [Français](README.fr.md) | [Español](README.es.md) | [Русский](README.ru.md) | [Português](README.pt-BR.md)

Ein Informations-Overlay mit Spaßfunktionen für *Escape the Backrooms* (Steam 1943950, UE 4.27). Reines Python, nur Standardbibliothek. Das Tool liest und schreibt den Spielspeicher von außen und setzt einen kleinen Hook auf `UObject::ProcessEvent`, um die spieleigenen UFunctions im Game-Thread aufzurufen.

> Nur für den Einzelspielermodus oder deine eigene Lobby (mit Freunden, die Bescheid wissen) – zum Spaß und zum Lernen von UE-Reverse-Engineering.
> Dieses Projekt steht in keiner Verbindung zu Fancy Games oder Steam. Nutzung auf eigene Gefahr; nach Spielupdates können Offsets und Signaturen ungültig werden.
>
> Hinweis: Das Bildschirm-Panel und die Meldungen sind derzeit nur auf vereinfachtem Chinesisch.

## Funktionen

**Overlay** (nur lesend, verändert das Spiel nicht)
- Zeigt Monster, Gegenstände, Ausgänge, Absturzzonen und Mitspieler mit Entfernung auf dem Bildschirm an; Ziele außerhalb des Bildes bekommen einen Pfeil am Bildschirmrand
- Panel oben links: Level, Koordinaten, Ausdauer, Entfernung zum nächsten Monster (rot unter 15 m), Ausgänge und Gegenstandsliste
- Radar oben rechts (Blickrichtung oben, 40 m Reichweite, entfernte Monster am Rand); Mitspielerliste mit Name, lebendig/tot, Entfernung und Verstand
- Blendet sich aus, wenn das Spiel nicht im Vordergrund ist; beendet sich, wenn das Spiel geschlossen wird

**Hotkeys** (deine Rolle wird automatisch erkannt: Einzelspieler / Host / Client)

| Taste | Host / Einzelspieler | Client |
|---|---|---|
| F5 | Nächstes Monster übernehmen (WASD bewegen, Maus drehen, Leertaste springen, Shift rennen); erneut drücken, um in den eigenen Körper zurückzukehren | Zur Sicht des nächsten Monsters wechseln (nur zuschauen) |
| F6 | Alle Monster einfrieren / auftauen | Nicht verfügbar |
| F7 | Fliegen + durch Wände gehen (Leertaste hoch, Strg runter) | Nicht verfügbar |
| F2 | Geschwindigkeitsboost + unendliche Ausdauer | Geschwindigkeitsboost (über Server-RPC) |
| F3 | Third-Person-Ansicht | Gleich |
| F4 / Shift+F4 | Skin wechseln: Kostüme aus dem Spiel (für andere sichtbar) oder Modelle von Monstern/Figuren im Level (nur für dich sichtbar) | Gleich |
| Einfg | Zum nächsten Ausgang teleportieren | Nicht verfügbar |
| Entf | Dich an der Todesstelle wiederbeleben | Sendet eine Respawn-Anfrage an den Host (meist ignoriert) |
| F11 | Unverwundbar: Monster, Stürze und Ertrinken können dich nicht töten (nur du, nicht deine Mitspieler) | Nicht verfügbar |
| F1 | Nachtsicht: höhere Belichtung, ohne Vignette, Körnung und chromatische Aberration | Gleich |
| Alt+1 | Freie Kamera: Kamera vom Körper lösen und frei fliegen (WASD, Leertaste/Strg hoch/runter, Shift schneller) | Gleich |
| Alt+2 | Verstand auf Maximum halten | Gleich |
| Alt+3 | Spieleigenen Tempo- und Ausdauerschub auslösen | Gleich |
| Alt+4 | Supersprung | Gleich |
| Alt+5 | Durch Wände: Server bitten, deine Kollision abzuschalten | Experimentell: bittet den Host, deine Kollision abzuschalten |
| Alt+6 | Nächsten herumliegenden Gegenstand aus der Ferne aufheben | Gleich (hängt davon ab, ob der Host die Entfernung prüft) |
| Alt+7 | Aus der Ferne mit dem interaktiven Objekt im Fadenkreuz interagieren | Gleich (hängt davon ab, ob der Host die Entfernung prüft) |
| Alt+8 | Den mit Bild↑/Bild↓ gewählten Gegenstand in einen freien Inventarplatz schreiben | Gleich |
| Bild↑ / Bild↓ + Pos1 | Gegenstand auswählen und in die Hand spawnen | Gleich |
| F8 / F9 / F10 | Overlay ausblenden / Gegenstandsmarker umschalten / Marker für interaktive Objekte umschalten | Gleich |
| Ende | Alle Änderungen zurücksetzen, Hook entfernen und beenden | Gleich |

## Verwendung

1. Stelle das Spiel auf **Fenstermodus** oder **randloses Fenster** (exklusiver Vollbildmodus verdeckt das Overlay) und betritt ein Level.
2. Entweder:
   - `ETB-Trainer.exe` aus den Releases herunterladen und doppelklicken (kein Python nötig), oder
   - Python 3.10+ installieren, den Quellcode herunterladen und `启动覆盖层.bat` („Overlay starten“) doppelklicken bzw. `python etb_overlay.py` ausführen.
3. Zum Beenden **Ende** drücken. Vorher werden Übernahme, Einfrieren, Fliegen, Skins usw. zurückgesetzt, danach wird der Hook entfernt.

Die Einzeldatei-exe ist mit PyInstaller gepackt und wird von Antivirenprogrammen eventuell fälschlich gemeldet. Wenn dich das stört, starte das Tool aus dem Quellcode.

## Dateien

| Datei | Beschreibung |
|---|---|
| `etb_overlay.py` | Einstiegspunkt: Overlay-Fenster, Speicherlesen, Actor-Klassifizierung, Projektion von Welt- auf Bildschirmkoordinaten |
| `etb_trainer.py` | Hotkey-Funktionen, laufen in einem Hintergrund-Thread des Overlay-Prozesses |
| `etb_call.py` | ProcessEvent-Hook + UFunction-Aufrufer, der Parameter per Reflection packt (unterstützt Batches) |
| `etb_ue.lua` | Cheat-Engine-Skript: findet GNames / GObjects / GWorld per AOB, mit Hilfsfunktionen für Namen, Reflection und Actor-Iteration |
| `NOTES.md` | Reverse-Engineering-Notizen (Chinesisch): Globals, Zeigerketten, Offsets, Funktionsweise des Hooks |
| `FUNCTIONS.md` | Liste aufrufbarer Funktionen (chinesische Beschreibungen; Auswahl + vollständige Signaturen von 1729 Funktionen in 212 Spielklassen) |

## Funktionsweise

- Beim Start werden die ausführbaren Sektionen des Hauptmoduls per AOB-Signatur durchsucht, um `GNames` (FNamePool), `GUObjectArray` und `GWorld` zu finden. Alles Weitere wird anhand des UE-4.27-Layouts und der Laufzeit-Reflection gelesen.
- Die ersten 19 Bytes von `ProcessEvent` werden durch einen `jmp` in eine Code-Cave ersetzt. Die Cave prüft, ob der aktuelle Thread der Game-Thread ist, sichert sich das Aufruf-Flag per `lock cmpxchg`, führt die von außen geschriebenen Aufrufe als Batch aus, führt dann den ursprünglichen Prolog aus und springt zurück. So laufen alle Spielfunktionsaufrufe im eigenen Hauptthread des Spiels.
- Rollenerkennung: Ist `Actor::Role` des lokalen Charakters Authority, unterscheidet `World::NetDriver` zwischen Einzelspieler und Host; AutonomousProxy bedeutet Client.

Details in [NOTES.md](NOTES.md) (Chinesisch).

## Kompatibilität

Erstellt und getestet mit Steam-Build 24997718. Meldet das Tool nach einem Spielupdate „AOB 没找到“ (AOB nicht gefunden) oder „ProcessEvent 开头字节和预期不同“ (unerwarteter ProcessEvent-Prolog), müssen die Adressen neu ermittelt werden.

## Lizenz

[MIT](LICENSE)
