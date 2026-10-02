"""Fecha o Voxel Cut se estiver aberto (usado pelo instalador e pelo desinstalador)."""
import time, urllib.request
for porta in (8770,):
    try:
        urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{porta}/api/quit", data=b"{}", method="POST"), timeout=2)
        time.sleep(1.5)
    except Exception:
        pass
