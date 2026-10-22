"""g2-ui: interfaz de la pantalla Nextion (D-005, D-029).

  * ``protocolo``  codigos de pagina y control, eventos, ordenes y colores (fuente unica);
  * ``vistas``     del estado del nucleo a lo que muestra cada pagina (funciones puras);
  * ``enlace``     el puerto serie real y una pantalla emulada para pruebas;
  * ``datos``      lecturas de la base (solo lectura) y de la red;
  * ``interfaz``   navegacion, pintado, parpadeo, sonido y acuse.

Se ejecuta con ``python3 -m g2.pantalla`` (ver ``__main__.py``).
"""
