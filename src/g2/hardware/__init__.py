"""Acceso al hardware de G2 (convertidor analogico-digital, y mas adelante I2C y GPIO).

Regla de diseño (D-024): todo dispositivo se maneja a traves de una interfaz pequeña
que tiene una implementacion real (en la Raspberry Pi) y un emulador (para probar en
cualquier PC). El codigo de G2 solo conoce la interfaz.
"""
