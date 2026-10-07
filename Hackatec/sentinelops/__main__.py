import sys
print("1. Archivo de arranque leído correctamente.")
from .main import main

if __name__ == "__main__":
    print("2. Arrancando el sistema SentinelOps...")
    sys.exit(main())