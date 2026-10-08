#!/usr/bin/env bash
# =============================================================================
# aprovisionar_pi.sh  --  Prepara el sistema de la Raspberry Pi para G2
# =============================================================================
# Decisiones: D-024 (instalacion repetible), D-020 (audio por la Nextion),
# D-023 (ADC por SPI, periféricos por I2C, pantalla por UART). Ver
# MEMORIA_TECNICA.md y HARDWARE.md.
#
# Uso:
#   sudo bash aprovisionar_pi.sh              aplica los cambios
#   bash aprovisionar_pi.sh --verificar       solo muestra el estado (no cambia nada)
#
# Que hace (es IDEMPOTENTE: se puede ejecutar varias veces):
#   1. Habilita SPI (ADC ADS1263) e I2C (BME280, IMU, RTC...).
#   2. Libera el UART principal para la pantalla Nextion: activa el UART por
#      hardware y quita la consola serie. Para eso el UART principal debe dejar
#      de usarse con el Bluetooth, asi que se desactiva el Bluetooth (dtoverlay
#      disable-bt) y su servicio; ademas ahorra energia.
#   3. Instala sqlite3 (cliente, para diagnostico) y tmux (sesiones largas por SSH).
#
# Que NO hace (a proposito, por ahora): no cambia la contrasena del usuario, no
# desactiva el escritorio (lightdm) ni los servicios avahi-daemon, rpcbind y
# nfs-blkmap, no toca la red ni el acceso SSH.
#
# Seguridad: antes de modificar config.txt y cmdline.txt guarda una copia con
# la extension .g2-original (solo la primera vez), para poder volver atras.
# Los cambios de arranque exigen REINICIAR; el script lo avisa y no reinicia.
# =============================================================================

set -euo pipefail

CONFIG=/boot/firmware/config.txt
CMDLINE=/boot/firmware/cmdline.txt

# --- Estado (solo lectura) ----------------------------------------------------
mostrar_estado() {
    echo "== Estado actual =="
    printf "SPI habilitado en config.txt      : "; grep -qE '^dtparam=spi=on' "$CONFIG" && echo SI || echo NO
    printf "I2C habilitado en config.txt      : "; grep -qE '^dtparam=i2c_arm=on' "$CONFIG" && echo SI || echo NO
    printf "UART por hardware (enable_uart)   : "; grep -qE '^enable_uart=1' "$CONFIG" && echo SI || echo NO
    printf "Bluetooth desactivado (disable-bt): "; grep -qE '^dtoverlay=disable-bt' "$CONFIG" && echo SI || echo NO
    printf "Consola serie en cmdline.txt      : "; grep -qE 'console=(serial0|ttyAMA0|ttyS0)' "$CMDLINE" && echo "SI (debe quitarse)" || echo NO
    printf "Servicio bluetooth                : "; systemctl is-enabled bluetooth 2>&1 || true
    printf "sqlite3 / tmux instalados         : "
    command -v sqlite3 >/dev/null && printf "sqlite3=SI " || printf "sqlite3=NO "
    command -v tmux    >/dev/null && echo "tmux=SI"      || echo "tmux=NO"
    printf "Dispositivos activos ahora        : "; ls /dev/spidev* /dev/i2c-1 /dev/serial0 2>/dev/null | tr '\n' ' ' || true; echo
}

if [ "${1:-}" = "--verificar" ]; then
    mostrar_estado
    exit 0
fi

if [ "$(id -u)" -ne 0 ]; then
    echo "Este script cambia la configuracion del sistema: ejecutelo con sudo." >&2
    exit 1
fi

# --- Copias de seguridad (solo la primera vez) --------------------------------
for f in "$CONFIG" "$CMDLINE"; do
    [ -f "$f.g2-original" ] || cp -a "$f" "$f.g2-original"
done
antes=$(cat "$CONFIG" "$CMDLINE" | sha256sum)

# --- 1 y 2. SPI, I2C y UART mediante raspi-config (la via oficial) -------------
# do_X 0 = habilitar; do_serial_cons 1 = quitar la consola serie.
raspi-config nonint do_spi 0
raspi-config nonint do_i2c 0
raspi-config nonint do_serial_cons 1
raspi-config nonint do_serial_hw 0

# El UART principal (PL011) esta por omision unido al Bluetooth. Para dejarlo en
# los pines GPIO14/15 de la pantalla se desactiva el Bluetooth. La linea debe
# quedar bajo [all]: si el ultimo encabezado de config.txt no es [all], se agrega.
if ! grep -qE '^dtoverlay=disable-bt' "$CONFIG"; then
    ultimo=$(grep -E '^\[.*\]' "$CONFIG" | tail -n 1 || true)
    [ "$ultimo" = "[all]" ] || printf '\n[all]\n' >> "$CONFIG"
    printf '# G2: libera el UART principal para la pantalla Nextion y apaga el Bluetooth\n' >> "$CONFIG"
    printf 'dtoverlay=disable-bt\n' >> "$CONFIG"
fi

# Servicios del Bluetooth (el servicio hciuart puede no existir en Trixie).
systemctl disable --now bluetooth.service 2>/dev/null || true
systemctl disable hciuart.service 2>/dev/null || true

# --- 3. Paquetes -----------------------------------------------------------------
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends sqlite3 tmux

# --- Resultado ---------------------------------------------------------------------
despues=$(cat "$CONFIG" "$CMDLINE" | sha256sum)
echo
mostrar_estado
echo
if [ "$antes" != "$despues" ]; then
    echo ">>> REINICIO NECESARIO: la configuracion de arranque cambio."
else
    echo "Sin cambios de arranque: no hace falta reiniciar."
fi
