"""Nucleo de G2 (g2-core): unico escritor de la base de datos (D-005).

Lee los sensores, convierte la tension a % de oxigeno, promedia por intervalo, guarda las lecturas
y evalua las alarmas por sensor (D-032). Modulos:

  * ``senal``    conversion de tension a % de O2 y agregado por intervalo (promedio, minimo, maximo);
  * ``alarmas``  motor de alarmas con retardo, histeresis, acuse y salidas de los relevos;
  * ``fuentes``  de donde salen las tensiones (el ADC real o una fuente simulada);
  * ``salidas``  los relevos de alarma (D-033); por ahora solo la version emulada;
  * ``nucleo``   el ciclo que une todo.

Se ejecuta con ``python3 -m g2.nucleo`` (ver ``__main__.py``).
"""
