from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import ipaddress
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

app = FastAPI()


class ScanRequest(BaseModel):
    ip: str


@app.get("/health")
def health():
    return {"status": "online"}


@app.post("/scan")
def scan(request: ScanRequest):
    # IP-Adresse prüfen
    try:
        target = ipaddress.ip_address(request.ip)
    except ValueError:
        raise HTTPException(status_code=400, detail="Ungültige IP-Adresse")

    # Nur öffentliche IP-Adressen erlauben
    if not target.is_global:
        raise HTTPException(
            status_code=403,
            detail="Nur öffentliche IP-Adressen erlaubt"
        )

    # Nmap starten
    command = [
        "nmap",
        "-Pn",
        "-sT",
        "-sV",
        "--version-light",
        "--open",
        "-p-",
        "-oX",
        "-",
        str(target)
    ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=900
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=504,
            detail="Nmap-Scan Timeout"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

    if result.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=result.stderr or "Nmap-Scan fehlgeschlagen"
        )

    # XML-Ausgabe parsen
    try:
        root = ET.fromstring(result.stdout)
    except ET.ParseError:
        raise HTTPException(
            status_code=500,
            detail="Nmap-Ausgabe konnte nicht verarbeitet werden"
        )

    host = root.find("host")

    if host is None:
        raise HTTPException(
            status_code=500,
            detail="Keine Host-Daten in der Nmap-Ausgabe"
        )

    # Host-Status
    status_element = host.find("status")
    host_status = (
        status_element.get("state")
        if status_element is not None
        else "unknown"
    )

    # Hostname
    hostname = None
    hostname_element = host.find("./hostnames/hostname")

    if hostname_element is not None:
        hostname = hostname_element.get("name")

    # Offene Ports und erkannte Dienste
    open_ports = []

    for port in host.findall("./ports/port"):
        state_element = port.find("state")

        if state_element is None or state_element.get("state") != "open":
            continue

        service_element = port.find("service")

        service = {
            "port": int(port.get("portid")),
            "protocol": port.get("protocol"),
            "state": "open",
            "service": None,
            "product": None,
            "version": None,
            "extrainfo": None,
            "tunnel": None,
            "cpe": []
        }

        if service_element is not None:
            service["service"] = service_element.get("name")
            service["product"] = service_element.get("product")
            service["version"] = service_element.get("version")
            service["extrainfo"] = service_element.get("extrainfo")
            service["tunnel"] = service_element.get("tunnel")

            service["cpe"] = [
                cpe.text
                for cpe in service_element.findall("cpe")
                if cpe.text
            ]

        open_ports.append(service)

    # Scan-Dauer
    finished = root.find("./runstats/finished")
    elapsed = (
        float(finished.get("elapsed"))
        if finished is not None and finished.get("elapsed")
        else None
    )

    return {
        "ip": str(target),
        "hostname": hostname,
        "host_status": host_status,
        "scan_success": True,
        "scan_time": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": elapsed,
        "open_ports_count": len(open_ports),
        "open_ports": open_ports
    }
