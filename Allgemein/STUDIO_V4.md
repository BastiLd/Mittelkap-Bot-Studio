# Bot-Studio V4 · Funktionen und Bedienung

Öffentliche Funktionsübersicht. Installation: [Repository-Anleitung](../README.md). Lokale Bereitstellungsdaten und Prüfprotokolle sind nicht Teil dieses Dokuments.

## Zusammenarbeit mit gezielten Rechten

Unter **Konten & Darstellung** gibt es 28 einzeln vergebbare Freigaben. Neben Botfunktionen kann Basti nun fünf Aufgaben zur Webkontenverwaltung delegieren: Anlegen, Anzeigenamen bearbeiten, Passwörter zurücksetzen, Funktionsrechte vergeben und Sperren/Freischalten.

Delegierte Verwalter bearbeiten nur fremde normale Konten innerhalb ihrer eigenen Freigaben. Sie geben höchstens eigene Funktionsrechte weiter. Sie können weder Bastis Inhaberkonto noch andere Webverwalter oder die eigenen Rechte verändern. Nur Basti kann Verwaltungsrechte delegieren. Der feste Inhaber `basti` bleibt aktiv, behält alle Rechte und kann nicht entfernt werden.

Vorhandene Passwörter und Konten werden übernommen. Änderungen von Rechten, Passwort oder Kontostatus entziehen bestehende Sitzungen und wartende Aufträge mit altem Berechtigungsstand. Website und Bot prüfen die Berechtigung unabhängig. Moderationsprotokolle nennen den tatsächlichen Webauftraggeber.

## Deine Ansicht und Community

Die persönliche Themenauswahl umfasst **Dunkel**, **Mitternacht**, **Graphit**, **Retro** und **Papier**. Bewegungen lassen sich reduzieren. **Name · ID** beziehungsweise **ID · Name** gilt für Mitglieder, Kanäle und Rollen. Name und ID können einzeln kopiert werden; ohne Zwischenablagefreigabe erscheint der Wert zum manuellen Kopieren.

**Mitglieder & Rollen** zeigt den verfügbaren Gesamtbestand ohne feste 1000er-Grenze. Die Auswahl kombiniert Namens-/ID-Suche mit einer oder mehreren Rollen: mindestens eine oder alle ausgewählten Rollen. Dazu kommen Filter für Administratoren, Menschen und Bots. „Administrator“ basiert auf der Discord-Berechtigung, nicht auf dem Rollennamen.

Der Bot vervollständigt seinen Mitgliederbestand beim Verbinden mit einem zeitlich begrenzten Abruf. Dashboard-Aktualisierungen verwenden diesen Bestand und starten keinen vollständigen Discord-Abruf alle fünf Sekunden. Eine unvollständige Liste bleibt als solche erkennbar. Aktuelle Banns werden ebenfalls eingelesen, sofern Discord die nötigen Rechte gewährt.

## Lokaler Design-Marktplatz und echte Bildkarten

Der Nachrichteneditor enthält **38 kategoriespezifische Beispiele** und **24 lokale Designs in sieben Layouts**. Der Marktplatz lässt Designs suchen, filtern und vergleichen. Er braucht weder Kauf noch externen Designdienst. Ein Design verändert zunächst nur den Entwurf; vorhandene Texte bleiben erhalten. **Vorlage speichern** aktiviert die Vorlage. **Versand prüfen** öffnet eine separate Bestätigung für eine zusätzliche Nachricht.

Die Layouts heißen Klassisch, Konsole, Magazin, Ebenen, Bauplan, Fokus und Eintrittskarte. Für Willkommen, Abschied und Geburtstag können Hintergrund, Akzent, Schrift, Rundung, Überschrift und Zusatztext angepasst werden. Ebenenzahl, X-/Y-Versatz, Weichzeichnung, Schattenfarbe und Deckkraft verändern die tatsächlichen PNG-Pixel. Vorschau und Bot verwenden denselben Renderer. Null Ebenen beziehungsweise null Deckkraft schaltet den Schatten aus.

Die Beispieldaten sind vom gespeicherten Vorlagentext getrennt. Ein manuell bestätigter Beispielversand ist ausdrücklich als Beispiel gekennzeichnet; ein Bannbeispiel erzeugt keinen Bann. Für echte Protokolldetails sollte `{description}` erhalten bleiben. Kartentexte erlauben `{name}` und `{server}`. JSON-Import lädt zunächst einen Entwurf, JSON-Export sichert die Vorlage.

Discord bestimmt weiterhin Schrift und Layout des normalen Embed-Texts. Unsere Typografie und Schatten werden als Bildkarte gerendert. Windows nutzt vorhandene native Schriften. Im Paket liegen **Archivo**, **Roboto** und **Roboto Mono** mit Original-Lizenzen und dokumentierten Prüfsummen, sodass sich Überschrift, Sans-Schrift und Konsole auch auf einem Linux-Server ohne zusätzliche Schriftpakete unterscheiden. Die bisherigen Figuren-GIFs bleiben deaktiviert.

## Moderation erweitern, Ergebnisse ehrlich anzeigen

| Ultron | Jarvis |
|---|---|
| `/bannen` – Zugang sperren | `/entbannen` – Zugangssperre aufheben |
| `/kicken` – Mitglied entfernen | `/einladen` – freiwillige Rückkehr ermöglichen |
| `/stummschalten` – zeitweise Kommunikation sperren | `/stummschaltungaufheben` – Timeout beenden |

Im Dashboard haben diese Aktionen getrennte Rechte und eine konkrete Bestätigung vor der Ausführung. Ziel, Name, ID, Grund, auslösender Account, Zeitpunkt und Ergebnis bleiben dauerhaft gespeichert. Die Liste früherer Ziele hilft beim Entbannen und Einladen; unbekannte historische Kicks werden nicht erfunden.

Ein „Entkicken“ gibt es bei Discord nicht. Eine entfernte Person kann eine neue Einladung erhalten und selbst wieder beitreten. `/einladen` prüft zuerst, dass kein Bann mehr besteht. Ein Bann wird dafür nicht automatisch aufgehoben.

Einladungen gelten 24 Stunden und für eine Verwendung. Sie brauchen einen ausgewählten Textkanal und das Recht **Einladung erstellen**. Der Grund ist frei formulierbar und erscheint auch in einer ausdrücklich gewünschten Privatnachricht. Bei `/entbannen` ist die private Einladung optional. Eine geschlossene DM oder unklare Zustellung hebt eine erfolgreiche Entbannung nicht auf. Aktionsstatus und Zustellstatus werden getrennt protokolliert; es gibt keine automatische Wiederholung der Privatnachricht.

Basti mit Discord-ID **965593518745731152** bleibt vor Bann, Kick und Timeout geschützt. Rollen- und Botrechte werden vor Aktionen erneut geprüft. Der Bot kann Discords Rollenreihenfolge nicht umgehen. Ein Update, Start oder bloßes Öffnen der Oberfläche führt keine Moderationsaktion und keine private Einladung aus.

## Beibehaltene Funktionen

- Jarvis liefert die einzige neutrale Rangkarte unter `/rang`; Text-, Sprachchat- und Sprachnachrichten-XP bleiben einstellbar.
- `/geburtstag` erklärt die private Eingabe von Tag/Monat, den öffentlichen Zielkanal und den Grußtermin; Standard 00:00 Uhr Europe/Vienna, ohne Alter.
- Kanalziele unterstützen Textkanäle und konkrete Forum-Beiträge. Das Forum selbst ist kein Nachrichtenkanal.
- Befehlsnamen, Beschreibungen, Antwortsichtbarkeit und erlaubte Aufrufkanäle bleiben änderbar. Neue Namen werden über **Befehle aktualisieren** übertragen.
- Protokolle behalten belegte Quellen- und Ankündigungsverweise über Neustarts hinweg. Rückscan: standardmäßig 50 passende eigene Nachrichten je Kategorie/Befehl und Ziel; alternativ 100, eigene Anzahl, alle oder keine.
- Livestream-Ankündigungen können ab Erkennung verzögert werden. Der Bot aktualisiert verfügbare Titel/Thumbnails beim fälligen Abruf und verwirft beendete Streams. Anbieterzugänge bleiben gesondert erforderlich.

## Erweiterung: Hilfe, XP und mehrere Server

- Jede Seite besitzt eine ausführliche deutsche Gesamterklärung. Einzelne Felder, Quellen, Wartezeiten und Abschnitte haben eigene anklickbare i-Erklärungen; auch die Bot-Auswahl und ihr Geltungsbereich werden erklärt.
- **XP & Events** gehört zu Jarvis. Das gesonderte Recht `manage.xp` erlaubt Hinzufügen, Abziehen und Setzen für einzelne Mitglieder, mehrere Rollen oder alle menschlichen Mitglieder. Vor der Ausführung wird die Auswahl bestätigt. Der Bot prüft das vollständige Mitgliederverzeichnis; die Änderung und ihr Verlauf werden atomar gespeichert und nicht doppelt gebucht.
- Zeitlich begrenzte Booster können sofort oder geplant starten. Sie gelten für Mitglieder, Rollen oder den Server, bleiben nach Neustarts erhalten und enden automatisch. Bei Überschneidungen gilt der höchste passende Faktor. Manuelle oder schon verdiente XP werden nicht multipliziert. Abziehen endet bei null; bestehende Levelrollen werden nicht automatisch entfernt.
- Neu verbundene Discord-Server erscheinen in der Auswahl. Ihre Ziele, Quellen, Links, Verwaltungsrollen und eigenen Vorlagen beginnen ohne fremde Serverzuordnungen. Es gibt bewusst keine automatische Kanalzuweisung. Ein fehlender Bot führt nicht zum stillen Wechsel auf einen anderen Server.
- WebHafen kann den Branch `main` des öffentlichen Repositorys verwenden. Als Website-Ordner ausschließlich **`Webseite/public`** auswählen; die Dateiauswahl leer lassen. Dort liegen nur die fertigen öffentlichen Website-Dateien. `/api/` wird weiterhin an das private Python-Backend geleitet.
- Website-Updates und Bot-Updates sind getrennt: WebHafen aktualisiert die Oberfläche. Python-Änderungen müssen zusätzlich in den beiden Bot-Manager-Profilen aus Git übernommen und die Dienste danach gestartet werden. Konten, Tokens und Datenbanken gehören nicht zum Website-Import.

