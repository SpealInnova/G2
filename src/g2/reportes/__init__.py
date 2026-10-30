"""Reportes en PDF de las lecturas, para llevarlos a una memoria USB (D-044).

  * ``rango``     rango de fechas (dias completos, maximo una semana) y zona horaria;
  * ``consulta``  lee las lecturas y alarmas de la base (solo lectura), junta cada pareja de sensores y marca las alertas;
  * ``pdf``       dibuja el PDF y lo cifra (la contrasena es el nombre del equipo);
  * ``usb``       busca la memoria USB (debe llamarse igual que el equipo), copia el archivo y la desmonta;
  * ``trabajo``   el trabajo completo, que corre en un PROCESO aparte para no estorbar la medicion (``python3 -m g2.reportes``).
"""
