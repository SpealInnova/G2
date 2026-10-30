"""g2-uplink: envia a la plataforma sp-peek.com lo que g2-core guarda (D-009, D-046).

Solo LEE la base; cuando la plataforma confirma un lote le pide a g2-core que lo anote en la cola (``cola_resultado``).
El equipo siempre inicia la conexion (HTTPS): no se abre ningun puerto en la Pi.
"""
