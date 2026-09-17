import platform
import subprocess
from typing import Dict, Any


class SmartHealthChecker:
    """Pre-flight check inspecting Windows S.M.A.R.T. and predictive failure metrics."""

    @classmethod
    def check_drive_health(cls, drive_letter: str) -> Dict[str, Any]:
        clean = drive_letter.strip("\\").upper()
        if platform.system() != "Windows":
            return {"healthy": True, "warning": False, "status": "Healthy (Simuliert)", "message": "OK"}

        try:
            cmd = 'powershell -NoProfile -Command "Get-PhysicalDisk | Select-Object DeviceId, FriendlyName, OperationalStatus, HealthStatus | ConvertTo-Json"'
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
            if res.returncode == 0 and res.stdout.strip():
                txt = res.stdout
                if "Unhealthy" in txt or "Warning" in txt or "PredictiveFailure" in txt:
                    return {"healthy": False, "warning": True, "status": "Caution", "message": "S.M.A.R.T. Fehler gemeldet!"}
            return {"healthy": True, "warning": False, "status": "Healthy", "message": "Integrität normal."}
        except Exception as ex:
            return {"healthy": True, "warning": False, "status": "Unknown", "message": str(ex)}

