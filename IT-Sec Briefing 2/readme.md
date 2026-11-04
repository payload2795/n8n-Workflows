# IT Security Monitoring mit n8n, Shodan und Nmap

## 1. Zweck

Dieser Workflow überwacht definierte öffentliche IT-Assets und erstellt
daraus einen automatisierten Sicherheitsbericht.

Pro aktivem Asset werden:

1.  die Asset-Daten aus der n8n Data Table geladen,
2.  Informationen von Shodan abgefragt,
3.  ein eigener Nmap-Scan durchgeführt,
4.  erwartete und tatsächlich gefundene Ports verglichen,
5.  Shodan- und Nmap-Ergebnisse zusammengeführt,
6.  gemeldete CVEs über Shodan und NVD bewertet,
7.  CVEs mit der tatsächlich erkannten Software von Nmap korreliert,
8.  ein Gesamtrisiko pro Asset berechnet,
9.  ein HTML-Dashboard als E-Mail versendet.

Der Workflow kann manuell oder automatisch über den Schedule Trigger
gestartet werden.

------------------------------------------------------------------------

# 2. Voraussetzungen

Benötigt werden:

-   eine laufende n8n-Installation
-   Docker / Docker Compose
-   Zugriff von n8n auf den Nmap-Scanner-Container
-   eine n8n Data Table namens `security_assets`
-   eine SMTP-Credential in n8n
-   Internetzugriff für Shodan und NVD
-   öffentliche IP-Adressen als Scanziele

Der Nmap-Scanner akzeptiert absichtlich nur öffentliche IP-Adressen.

> Wichtig: Scanne nur Systeme, für die du ausdrücklich eine Berechtigung
> hast.

------------------------------------------------------------------------

# 3. Aufbau des Workflows

Vereinfacht sieht der Ablauf so aus:

``` text
Schedule / Manual Trigger
          │
          ▼
     security_assets
          │
          ├──────────────► Shodan
          │
          └──────────────► Nmap Scanner
                                │
                                ▼
                         Portvergleich
                                │
                 ┌──────────────┴──────────────┐
                 ▼                             ▼
          Netzwerk-Risiko                 CVE-Prüfung
                                               │
                                     Shodan CVE / NVD
                                               │
                                      CVE-Korrelation
                                               │
                 └──────────────┬──────────────┘
                                ▼
                       Asset Risk Management
                                │
                                ▼
                       HTML Security Report
                                │
                                ▼
                              E-Mail
```

Der Workflow enthält außerdem einen separaten `Error Trigger`, der bei
Workflow-Fehlern eine Fehler-Mail versendet.

------------------------------------------------------------------------

# 4. Asset-Verwaltung

Die überwachten Systeme werden über die n8n Data Table `security_assets`
gesteuert.

Entscheidend ist die Spalte:

``` text
active
```

Nur Assets mit:

``` text
active = true
```

werden verarbeitet.

Typische Felder sind:

``` text
name
ip
environment
expected_ports
active
```

Beispiel:

``` text
name: ReverseProxy
ip: 89.107.163.59
environment: Production
expected_ports: 80,443
active: true
```

## Bedeutung von `expected_ports`

`expected_ports` definiert die Ports, die auf dem jeweiligen System
bewusst erreichbar sein sollen.

Beispiel:

``` text
80,443
```

Wenn Nmap zusätzlich Port `8080` findet, wird dieser als unerwarteter
Port bewertet.

Wenn Nmap Port `443` nicht findet, wird dies als fehlender erwarteter
Port dokumentiert.

Ein fehlender Port ist dabei nicht automatisch ein Sicherheitsproblem.
Er kann beispielsweise auf einen Dienstfehler oder eine
Konfigurationsänderung hinweisen.

------------------------------------------------------------------------

# 5. Shodan-Abfrage

Für jedes Asset wird folgende Shodan InternetDB-Abfrage verwendet:

``` text
https://internetdb.shodan.io/<IP>
```

Die IP wird aus dem Asset übernommen.

Shodan liefert unter anderem:

-   bekannte Ports
-   bekannte CVEs
-   weitere öffentlich bekannte Informationen zum Ziel

Der Workflow verwendet Shodan damit als externe Sicht auf das Asset.

Wichtig:

Shodan und Nmap messen nicht exakt dasselbe zum selben Zeitpunkt.
Unterschiede sind daher möglich und werden im Report ausdrücklich
dargestellt.

------------------------------------------------------------------------

# 6. Nmap-Scanner

Der Nmap-Scanner läuft als eigener Container.

Die API stellt zwei Endpunkte bereit:

``` text
GET /health
POST /scan
```

Ein Scan wird beispielsweise so ausgelöst:

``` json
{
  "ip": "89.107.163.59"
}
```

Der Scanner prüft zunächst die IP-Adresse.

Private oder nicht öffentliche Adressen werden abgelehnt.

Danach wird Nmap mit folgendem Prinzip ausgeführt:

``` text
-Pn
-sT
-sV
--version-light
--open
-p-
-oX -
```

Das bedeutet vereinfacht:

-   `-Pn` -- Host nicht über Ping-Erkennung ausschließen
-   `-sT` -- TCP Connect Scan
-   `-sV` -- Dienste und Versionen erkennen
-   `--version-light` -- leichtere Versionserkennung
-   `--open` -- nur offene Ports ausgeben
-   `-p-` -- alle TCP-Ports scannen
-   `-oX -` -- XML auf stdout ausgeben

Der Scanner gibt die gefundenen Ports inklusive erkannter Dienste,
Produkte, Versionen und CPEs an n8n zurück.

------------------------------------------------------------------------

# 7. Netzwerk-Risiko

Der Workflow betrachtet ausschließlich Nmap als Grundlage für die
Bewertung unerwarteter Ports.

Ein Port gilt als unerwartet, wenn:

``` text
Nmap-Port
    ≠
expected_ports
```

Beispiel:

``` text
Expected:
80,443

Nmap:
22,80,443,8080
```

Ergebnis:

``` text
Unerwartet:
22,8080
```

Der Netzwerkstatus wird dann auf:

``` text
WARNING
```

gesetzt.

Sind keine unerwarteten Ports vorhanden:

``` text
OK
```

Wenn der Nmap-Scan fehlschlägt:

``` text
UNKNOWN
```

Der Workflow vermeidet damit, einen fehlgeschlagenen Scan
fälschlicherweise als sicheren Zustand zu bewerten.

------------------------------------------------------------------------

# 8. Vergleich Nmap vs. Shodan

Der Report unterscheidet:

``` text
common
```

Ports, die beide Quellen kennen.

``` text
only_nmap
```

Ports, die aktuell nur Nmap findet.

``` text
only_shodan
```

Ports, die Shodan kennt, Nmap aktuell aber nicht findet.

Zusätzlich werden folgende Abweichungen separat betrachtet:

``` text
unexpected_nmap
missing_expected
```

Damit kann unterschieden werden zwischen:

-   bewusst erwarteten Ports
-   unerwartet offenen Ports
-   historischen / extern bekannten Shodan-Ports
-   aktuell nicht erreichbaren Ports

------------------------------------------------------------------------

# 9. CVE-Verarbeitung

Die CVEs aus Shodan werden zunächst einzeln verarbeitet.

Für jede CVE wird die Shodan-CVE-Datenbank abgefragt.

Anschließend erfolgt ein Lookup gegen die NVD:

``` text
https://services.nvd.nist.gov/rest/json/cves/2.0
```

Die Bewertung berücksichtigt:

-   CVSS
-   EPSS
-   KEV
-   Beschreibung
-   betroffene Produkte / CPEs

Die grundsätzliche Risikologik ist:

``` text
KEV oder CVSS >= 9
    → CRITICAL

CVSS >= 7
    → HIGH

CVSS >= 4
    → MEDIUM

sonst
    → LOW
```

Diese Einstufung ist zunächst eine Bewertung der CVE selbst.

Sie bedeutet noch nicht, dass das konkrete Asset tatsächlich verwundbar
ist.

------------------------------------------------------------------------

# 10. CVE-Korrelation

Ein wichtiger Teil des Workflows ist die zusätzliche Korrelation mit
Nmap.

Die CVE wird nicht einfach als "betroffen" angenommen.

Stattdessen wird geprüft, ob Nmap das zur CVE passende Produkt und
gegebenenfalls eine passende Version erkannt hat.

Mögliche Ergebnisse sind:

``` text
CPE_VERSION_MATCH
```

Möglicher Versions-Treffer.

``` text
PRODUCT_MATCH_VERSION_UNKNOWN
```

Produkt erkannt, Version aber nicht zuverlässig bekannt.

``` text
RELATED_PRODUCT_REVIEW
```

Ähnliches Produkt erkannt. Manuelle Prüfung erforderlich.

``` text
VERSION_NOT_AFFECTED
```

Erkannte Version passt nicht zum betroffenen Versionsbereich.

``` text
PRODUCT_NOT_OBSERVED
```

Das betroffene Produkt wurde nicht auf dem Asset nachgewiesen.

``` text
NO_NVD_DATA
```

Keine verwertbaren NVD-Daten vorhanden.

------------------------------------------------------------------------

# 11. Warum "Mögliche CVE" nicht gleich "betroffen" bedeutet

Das ist für die Interpretation des Reports besonders wichtig.

Shodan kann eine CVE für eine IP-Adresse melden, ohne dass damit
automatisch bewiesen ist, dass die aktuell laufende Software tatsächlich
betroffen ist.

Der Workflow versucht deshalb zusätzlich:

``` text
CVE
 ↓
NVD
 ↓
betroffenes Produkt
 ↓
Nmap erkannte Software
 ↓
Version
 ↓
Korrelation
```

Erst ein passender CPE-/Versions-Treffer ist ein starker technischer
Hinweis.

Auch dieser Treffer sollte bei kritischen Systemen manuell verifiziert
werden.

------------------------------------------------------------------------

# 12. Gesamtrisiko eines Assets

Das Asset-Risiko wird getrennt von der CVE-Einzelbewertung berechnet.

Aktuell gilt vereinfacht:

``` text
KEV-Kandidat + mögliche Produktkorrelation
    → HIGH
```

oder:

``` text
mögliche CVE
+
HIGH/CRITICAL CVE-Risiko
+
Produktkorrelation
    → HIGH
```

oder:

``` text
mögliche CVE
oder unerwartete Ports
    → MEDIUM
```

ansonsten:

``` text
LOW
```

Wichtig:

``` text
confirmed_cves = 0
```

ist im aktuellen Workflow bewusst so gesetzt.

Der Report behauptet damit nicht, eine CVE endgültig bestätigt zu haben.

------------------------------------------------------------------------

# 13. Testmodus

Der Node:

``` text
Test_CVE
```

ist aktuell deaktiviert.

Er kann verwendet werden, um testweise CVEs in den Workflow
einzuspeisen.

Beispielsweise:

``` text
CVE-2021-44228
CVE-2023-34362
```

Für einen normalen Produktivbetrieb sollte der Node deaktiviert bleiben.

------------------------------------------------------------------------

# 14. HTML-Report

Der Node:

``` text
Generate HTML Report
```

erzeugt die komplette HTML-Mail.

Der Report enthält:

-   Gesamtbewertung
-   Anzahl der Assets
-   Risiko-Verteilung
-   mögliche CVE-Treffer
-   KEV-Kandidaten
-   unerwartete Ports
-   bestätigte CVEs
-   Asset-Übersicht
-   CVE-Details
-   Netzwerk- und Portanalyse
-   Nmap/Shodan-Vergleich
-   Scaninformationen
-   Hinweise zur Interpretation

Die E-Mail wird anschließend über den SMTP-Node versendet.

------------------------------------------------------------------------

# 15. Zeitplan

Der Workflow besitzt einen `Schedule Trigger`.

Aktuell ist dieser auf:

``` text
06:00 Uhr
```

eingestellt.

Zusätzlich kann der Workflow über:

``` text
When clicking ‘Execute workflow’
```

manuell gestartet werden.

Das ist besonders praktisch für Tests.

------------------------------------------------------------------------

# 16. Nmap-Scanner installieren

## 16.1 Verzeichnis anlegen

Im selben Docker-Compose-Projekt wie n8n sollte beispielsweise folgende
Struktur verwendet werden:

``` text
projekt/
├── docker-compose.yml
└── nmap-scanner/
    ├── Dockerfile
    ├── requirements.txt
    └── app.py
```

Die Dateien `Dockerfile`, `requirements.txt` und `app.py` kommen aus
diesem Projekt.

------------------------------------------------------------------------

## 16.2 Dockerfile

Das Dockerfile basiert auf Python Alpine und installiert Nmap direkt im
Container.

``` dockerfile
FROM python:3.12-alpine

RUN apk add --no-cache nmap nmap-scripts

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

EXPOSE 8080

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
```

------------------------------------------------------------------------

## 16.3 requirements.txt

``` text
fastapi
uvicorn
```

------------------------------------------------------------------------

## 16.4 docker-compose.yml

Der Scanner wird als eigener Service eingebunden:

``` yaml
nmap-scanner:
  build:
    context: ./nmap-scanner
  container_name: nmap-scanner
  restart: unless-stopped
  networks:
    - default
  expose:
    - "8080"
```

`expose` veröffentlicht den Port nicht nach außen.

Der Port ist damit innerhalb des Docker-Netzwerks erreichbar.

Das ist für diesen Anwendungsfall sinnvoller als:

``` yaml
ports:
  - "8080:8080"
```

Denn die Scanner-API muss nicht aus dem Internet erreichbar sein.

------------------------------------------------------------------------

# 17. Scanner bauen und starten

Im Verzeichnis mit der `docker-compose.yml`:

``` bash
docker compose build nmap-scanner
```

Danach:

``` bash
docker compose up -d nmap-scanner
```

Status prüfen:

``` bash
docker compose ps
```

Logs ansehen:

``` bash
docker compose logs -f nmap-scanner
```

Der Container sollte als laufend angezeigt werden.

------------------------------------------------------------------------

# 18. Scanner testen

Zuerst den Health-Endpunkt testen.

Innerhalb des Docker-Netzwerks:

``` bash
curl http://nmap-scanner:8080/health
```

Erwartete Antwort:

``` json
{
  "status": "online"
}
```

Danach kann ein Scan getestet werden:

``` bash
curl -X POST http://nmap-scanner:8080/scan \
  -H "Content-Type: application/json" \
  -d '{"ip":"8.8.8.8"}'
```

Das Ergebnis enthält unter anderem:

``` json
{
  "ip": "8.8.8.8",
  "host_status": "up",
  "scan_success": true,
  "open_ports_count": 1,
  "open_ports": []
}
```

Die tatsächlichen Ports hängen natürlich vom Ziel und vom Zeitpunkt des
Scans ab.

------------------------------------------------------------------------

# 19. Verbindung von n8n zum Scanner

Im n8n-Workflow wird aktuell folgende URL verwendet:

``` text
http://172.18.0.7:8080/scan
```

Das ist eine feste Docker-IP.

## Besser: Docker-Service-Namen verwenden

Wenn n8n und der Scanner im selben Docker-Netzwerk laufen, sollte die IP
nicht fest im Workflow hinterlegt werden.

Besser ist:

``` text
http://nmap-scanner:8080/scan
```

Das ist robuster, weil sich Container-IPs ändern können.

### Empfehlung

Den Node `nmap-scan` auf folgende URL ändern:

``` text
http://nmap-scanner:8080/scan
```

Voraussetzung ist, dass beide Container im selben Docker-Netzwerk
hängen.

------------------------------------------------------------------------

# 20. n8n HTTP Request Node

Der Node `nmap-scan` verwendet:

``` text
Method:
POST
```

URL:

``` text
http://nmap-scanner:8080/scan
```

Header:

``` text
Content-Type: application/json
```

Body:

``` json
{
  "ip": "{{ $json.ip }}"
}
```

Timeout:

``` text
960000
```

Das sind 16 Minuten.

Der Scanner selbst verwendet einen Nmap-Timeout von 900 Sekunden, also
15 Minuten.

Die zusätzliche Minute im n8n-Timeout ist sinnvoll, damit n8n nicht vor
dem Scanner abbricht.

------------------------------------------------------------------------

# 21. Fehlerbehandlung

Der Nmap-Node verwendet:

``` text
onError: continueRegularOutput
```

Damit kann der Workflow trotz eines fehlgeschlagenen Scans weiterlaufen.

Der Netzwerk-Risikocode erkennt anschließend:

``` text
scan_success != true
```

und setzt:

``` text
network_risk = UNKNOWN
```

Das ist wichtig.

Ein fehlgeschlagener Scan darf nicht als:

``` text
OK
```

interpretiert werden.

------------------------------------------------------------------------

# 22. Workflow-Fehler-Mail

Der separate:

``` text
Error Trigger
```

überwacht Fehler des Workflows.

Bei einem Fehler wird eine eigene HTML-Mail erzeugt.

Sie enthält:

-   Workflow
-   Workflow-ID
-   Execution-ID
-   fehlerhaften Node
-   Zeitpunkt
-   Fehlerbeschreibung

Damit kann zwischen einem Sicherheitsbefund und einem technischen
Workflow-Fehler unterschieden werden.

------------------------------------------------------------------------

# 23. Betriebsempfehlung

Für den produktiven Betrieb empfehle ich:

### 1. Scanner nicht ins Internet veröffentlichen

Nicht:

``` yaml
ports:
  - "8080:8080"
```

verwenden.

Stattdessen:

``` yaml
expose:
  - "8080"
```

und Kommunikation nur über das Docker-Netzwerk.

### 2. Service-Namen statt Container-IP

Nicht:

``` text
http://172.18.0.7:8080/scan
```

sondern:

``` text
http://nmap-scanner:8080/scan
```

### 3. Nur autorisierte Ziele scannen

Der Scanner ist ein aktiver Portscanner.

Die Nutzung sollte auf eigene oder ausdrücklich freigegebene Systeme
beschränkt werden.

### 4. `expected_ports` sauber pflegen

Die Qualität der Netzwerkbewertung hängt direkt davon ab.

Eine falsche Asset-Konfiguration produziert unnötige Warnungen.

### 5. CVE-Hinweise nicht blind als Schwachstellen behandeln

Besonders wichtig sind:

``` text
CPE_VERSION_MATCH
```

und:

``` text
PRODUCT_MATCH_VERSION_UNKNOWN
```

Diese Ergebnisse sollten bei relevanten Systemen manuell überprüft
werden.

------------------------------------------------------------------------

# 24. Typischer täglicher Ablauf

Um 06:00 Uhr:

``` text
1. Aktive Assets laden
2. Shodan-Daten abrufen
3. Nmap-Scan starten
4. Ports vergleichen
5. Netzwerk-Risiko berechnen
6. Shodan-CVEs aufteilen
7. CVE-Daten von Shodan abrufen
8. NVD-Daten abrufen
9. Nmap-Software mit CVEs korrelieren
10. Asset-Risiko berechnen
11. HTML-Dashboard erzeugen
12. E-Mail versenden
```

Das Ergebnis ist damit eine tägliche Momentaufnahme der extern
sichtbaren Sicherheitslage.

------------------------------------------------------------------------

# 25. Troubleshooting

## Scanner antwortet nicht

Prüfen:

``` bash
docker compose ps
```

und:

``` bash
docker compose logs nmap-scanner
```

Danach aus dem n8n-Container testen:

``` bash
curl http://nmap-scanner:8080/health
```

Wenn das nicht funktioniert, befinden sich n8n und Scanner
wahrscheinlich nicht im selben Docker-Netzwerk.

------------------------------------------------------------------------

## `403 Nur öffentliche IP-Adressen erlaubt`

Das ist beabsichtigt.

Der Scanner akzeptiert keine:

``` text
10.0.0.0/8
172.16.0.0/12
192.168.0.0/16
127.0.0.0/8
```

und generell keine nicht global erreichbaren IP-Adressen.

------------------------------------------------------------------------

## Nmap läuft in einen Timeout

Der vollständige Scan aller TCP-Ports kann je nach Ziel länger dauern.

Prüfen:

``` text
nmap timeout = 900 Sekunden
n8n timeout  = 960 Sekunden
```

Ein sehr langsames oder stark gefiltertes Ziel kann deshalb zu einem
Timeout führen.

------------------------------------------------------------------------

## Shodan und Nmap liefern unterschiedliche Ports

Das ist normal.

Mögliche Ursachen:

-   unterschiedliche Scanzeitpunkte
-   Firewall-Regeln
-   temporäre Dienste
-   Filterung
-   Routing
-   Änderungen seit dem Shodan-Scan

Deshalb wird der Unterschied im Report als Information dargestellt und
nicht automatisch als Schwachstelle bewertet.

------------------------------------------------------------------------

# 26. Wichtige Designentscheidung

Der Workflow trennt bewusst drei Dinge:

``` text
Was ist bekannt?
        ↓
Shodan / NVD

Was ist aktuell erreichbar?
        ↓
Nmap

Was bedeutet das für das konkrete Asset?
        ↓
Korrelation + Risikobewertung
```

Diese Trennung ist wichtig, weil ein allgemeiner CVE-Hinweis nicht
automatisch bedeutet, dass das konkrete System verwundbar ist.

------------------------------------------------------------------------

# 27. Empfohlene nächste Ausbaustufen

Sinnvolle Erweiterungen wären:

1.  **Scanner-Authentifizierung**
    -   z.  B. API-Key zwischen n8n und Scanner.
2.  **Rate Limiting**
    -   verhindert unbeabsichtigte Scan-Fluten.
3.  **Scan-Historie**
    -   Ports und Risiken über mehrere Tage vergleichen.
4.  **Change Detection**
    -   neue offene Ports besonders hervorheben.
5.  **CVE-Historie**
    -   neue CVEs gegenüber dem letzten Lauf markieren.
6.  **Schweregrad pro Asset**
    -   Production-Systeme stärker gewichten als Testsysteme.
7.  **Explizite Bestätigung**
    -   `CPE_VERSION_MATCH` erst nach manueller Prüfung als bestätigt
        markieren.
8.  **Scanner-Netzwerk absichern**
    -   eigenes Docker-Netzwerk und nur die notwendige Kommunikation
        erlauben.

------------------------------------------------------------------------

# 28. Kurzfassung

Der Workflow ist kein einfacher Portscanner.

Er kombiniert:

``` text
Asset-Inventar
+
Shodan
+
Nmap
+
NVD
+
CVE-Korrelation
+
Risikobewertung
+
HTML-Reporting
```

Der entscheidende Punkt ist die Korrelation:

``` text
CVE gefunden
    ≠
System verwundbar
```

Erst die Kombination aus externen Informationen, aktuell erkanntem
Dienst, Produkt und Version liefert eine belastbarere Aussage.

Der Nmap-Scanner sollte dabei ausschließlich intern im Docker-Netzwerk
erreichbar sein und über den Service-Namen:

``` text
http://nmap-scanner:8080/scan
```

angesprochen werden.
