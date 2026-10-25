# Mittelkap · Jarvis, Ultron und Bot-Studio

Zwei Discord-Bots mit deutscher Bedienung und einer selbst gehosteten Verwaltungswebsite. Dieses öffentliche Repository enthält **Quellcode und bereinigte Beispiele**. Tokens, Webkonten, Passwörter, Serverdaten, Protokolle und persönliche Konfigurationen sind nicht enthalten.

## Vier Bereiche

| Ordner | Aufgabe |
| --- | --- |
| [Jarvis](Jarvis) | Begrüßung, Profillinks, Geburtstage, Aktivität/Rangkarte, Inhaltsmeldungen und positive Moderationsaktionen |
| [Ultron](Ultron) | Abschiede, Banns, Kicks und zeitweises Stummschalten |
| [Webseite](Webseite) | Python-Backend und Oberfläche: Konten/Rechte, Einstellungen, Protokolle, Mitglieder und Embed-Editor |
| [Allgemein](Allgemein) | Gemeinsame Anleitung, Environment-Beispiel, Paket-/Exportwerkzeuge und Font-/Prüfhinweise |

## Installation und Start

Python **3.12 oder 3.13** verwenden und `python -m pip install -r requirements.txt` ausführen. Die privaten Environment-Werte stehen beschrieben in [Allgemein/Manager.env.example](Allgemein/Manager.env.example); echte Werte im Prozessmanager oder einer privaten Umgebung hinterlegen. Die Beispieldatei wird nicht automatisch geladen.

Für zwei getrennte Prozessmanager-Profile jeweils dieses Repository vollständig auschecken:

| Profil | Startbefehl | Startet |
| --- | --- | --- |
| Jarvis | `python start.py --services jarvis` | Jarvis und das Website-Backend |
| Ultron | `python start.py --services ultron` | ausschließlich Ultron |

Beide Profile müssen denselben **absoluten** Pfad `DCBOTS_DASHBOARD_DIR` verwenden. Dort liegen die gemeinsamen Konten und Steuerungsaufträge. Als Einstieg pro Bot funktionieren auch `python Jarvis/main.py` und `python Ultron/main.py`; sie reichen an die Startsteuerung im Repository-Stamm weiter. Vor dem Start prüft `python start.py --services jarvis --check` beziehungsweise `--services ultron --check` ausschließlich Dateien, Variablen und Bibliotheken, ohne Discord-Verbindung.

Alternativ startet `python start.py --services all` alle drei Dienste in einem Profil. Die Alternativen nicht gleichzeitig mit denselben Tokens betreiben. Der Supervisor leitet Stoppsignale weiter und beendet die zu seinem Profil gehörenden Prozesse. Der tatsächliche Discord-Online-Status wird separat durch die Bots gemeldet.

## Einrichtung

Die mitgelieferten Bot-Konfigurationen haben leere Links, Quellen, Rollen und Kanalziele. Diese nach dem Start über `/einstellungen` beziehungsweise die Website einrichten. Discord benötigt die Intents **Server Members** und **Message Content** sowie die jeweils erforderlichen Kanal-/Moderationsrechte.

`DASHBOARD_PUBLIC_URL` muss exakt zur Browseradresse passen. Das Backend hört standardmäßig auf Port 8765; ein Reverse-Proxy erhält Host/Origin und leitet `/api/` unverändert weiter. Für öffentlichen Zugriff HTTPS verwenden. Beim ersten Einrichten wird ein eigener zufälliger `DASHBOARD_SETUP_KEY` benötigt; anschließend im Browser das Passwort für das Inhaberkonto **basti** festlegen. Teammitglieder bekommen getrennte Konten und Rechte.

**Projektbindung:** Die bestehende Schutzregel für Bastis Discord-ID `965593518745731152` ist bewusst erhalten. Die ID ist kein Token. Dieses Projekt ist auf diesen Inhaber zugeschnitten; für einen unabhängigen Fork müssen Identitäts-/Schutzregeln bewusst geprüft werden. Der Bot kann Discords Rollenreihenfolge nicht umgehen.

## Gestaltung und Daten

38 Kategorien mit Beispielen, 24 lokale Designs in sieben Layouts und ein PNG-Renderer für echte Schriften, Farben und Schatten. Auswahl und Vorschau speichern oder senden nichts automatisch. Funktionen und Grenzen beschreibt [Allgemein/STUDIO_V4.md](Allgemein/STUDIO_V4.md).

Laufzeitdaten liegen in den jeweiligen Bot-Datenordnern und dem privaten gemeinsamen Control-Verzeichnis. Sie gehören nicht in Git. Bestehende Datenbanken vor einem Umzug konsistent sichern und getrennt übertragen; nie mit diesem bereinigten Quellcode-Export überschreiben.

Die enthaltenen freien Schriften Archivo, Roboto und Roboto Mono enthalten ihre Original-OFL-Lizenzen und Herkunftsnachweise unter `Jarvis/assets/fonts` und `Ultron/assets/fonts`. Es werden keine Microsoft-Schriften oder Filmreferenzbilder verteilt. Die früheren Figuren-GIFs sind nicht Bestandteil dieses Exports.

Die öffentliche Exportprüfung steht in [Allgemein/export-scan.json](Allgemein/export-scan.json). Sie dokumentiert die ausgeführten statischen Prüfungen und ist keine Zusicherung, dass beliebige spätere Dateien geheimnisfrei sind. Änderungen erneut prüfen, bevor sie veröffentlicht werden. Eine laufende Bereitstellung wird durch dieses Repository nicht behauptet.
