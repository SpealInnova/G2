#!/usr/bin/env bash
# Instala (o actualiza) los servicios de G2 en la Raspberry Pi. Repetible: se puede ejecutar de nuevo.
#
#   sudo ./scripts/instalar_servicios.sh             # instala y habilita (arrancan solos al encender)
#   sudo ./scripts/instalar_servicios.sh --iniciar   # ademas los (re)inicia ahora
#   sudo ./scripts/instalar_servicios.sh --quitar    # los detiene y los deshabilita
#
# Servicios: g2-core (lectura, alarmas y base de datos) y g2-ui (pantalla Nextion). Tambien instala la regla de
# polkit (systemd/50-g2.rules) que permite a g2-core reiniciar los servicios y el equipo cuando lo pide la pantalla.
# Mientras corren ocupan el ADC (g2-core) y el puerto serie (g2-ui): para usar las herramientas de banco
# (tools/banco) hay que detener el servicio correspondiente (sudo systemctl stop g2-core / g2-ui) y volver
# a iniciarlo despues.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Ejecute con sudo." >&2
    exit 1
fi
cd "$(dirname "$0")/.."
servicios="g2-core g2-ui"
regla="/etc/polkit-1/rules.d/50-g2.rules"

if [ "${1:-}" = "--quitar" ]; then
    for s in $servicios; do
        systemctl disable --now "$s.service" 2>/dev/null || true
        rm -f "/etc/systemd/system/$s.service"
    done
    rm -f "$regla"
    systemctl daemon-reload
    echo "Servicios de G2 quitados."
    exit 0
fi

# g2-core guarda en esta carpeta; el usuario pi debe poder escribirla.
install -d -o pi -g pi -m 0755 /home/pi/g2/datos
for s in $servicios; do
    install -m 0644 "systemd/$s.service" "/etc/systemd/system/$s.service"
done
install -d -m 0755 /etc/polkit-1/rules.d
install -m 0644 systemd/50-g2.rules "$regla"
systemctl daemon-reload
for s in $servicios; do
    systemctl enable "$s.service"
done
echo "Servicios instalados y habilitados (arrancan solos al encender): $servicios"
echo "Regla de polkit instalada: $regla"
if [ "${1:-}" = "--iniciar" ]; then
    for s in $servicios; do                       # primero el nucleo, despues la interfaz
        systemctl restart "$s.service"
    done
    sleep 4
    systemctl --no-pager --lines=4 status $(printf '%s.service ' $servicios) || true
fi
