# Allgemein

Dieser Bereich enthält gemeinsame Start-/Paketwerkzeuge und öffentliche Anleitung. Maßgeblich für den Start ist [../start.py](../start.py), die gemeinsame Abhängigkeitsliste steht unter [../requirements.txt](../requirements.txt).

- `Manager.env.example`: ausschließlich leere Zugangsdaten und generische Beispieladressen. Nicht als echte Konfiguration veröffentlichen.
- `STUDIO_V4.md`: Funktions- und Bedienübersicht ohne private Bereitstellungsdaten.
- `build_packages.py`: explizite Paket-Packliste; `python Allgemein/build_packages.py --output-dir <privater-ausgabeordner>` erzeugt Codepakete.
- `export_repository.py`: erzeugt aus dem Quellprojekt einen neuen bereinigten Unterordner `Repository`; vorhandene unbekannte Dateien führen zum Abbruch. Quellkonfigurationen werden nicht verändert. Der Export liest keine privaten Dateien und führt keine Veröffentlichung aus.
- `export-manifest.json`: Dateipfade und SHA-256-Prüfsummen des Quellcode-Exports.
- `export-scan.json`: Prüfbericht ohne gefundene Geheimniswerte; die bewusst erhaltene Schutz-ID wird nur über ihre Fundstellen dokumentiert.

Die gebündelten Schriften liegen in beiden Botordnern mit ihren vollständigen SIL-OFL-Lizenzen und Quellenangaben. Die Website benutzt das gleiche Kartenmodul wie Jarvis. Kein Test, Start oder Export löst automatisch eine Moderation oder Privatnachricht aus.
