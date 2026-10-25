# Webseite

`server.py` stellt das private API-Backend und die Oberfläche unter `static/` bereit. Der reguläre Start erfolgt zusammen mit Jarvis über `python start.py --services jarvis` im Repository-Stamm. Beide Bot-Profile teilen das private Control-Verzeichnis.

Die Oberfläche kann alternativ statisch gehostet werden, wenn derselbe Ursprung `/api/` an dieses Backend weiterleitet. `DASHBOARD_PUBLIC_URL`, Host/Origin und HTTPS entsprechend der [Repository-Anleitung](../README.md) konfigurieren. API-Schlüssel oder Bot-Tokens gehören niemals in JavaScript oder statische Dateien.
