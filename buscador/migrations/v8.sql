-- v8: corrige el registro de cuota en peticiones rechazadas.
--
-- Antes, `probar_conexion` marcaba `cuota_consumida = 1` incluso cuando la API
-- rechazaba la petición con 400/401/403. Esas peticiones no generan tokens ni
-- consumen cuota, y el error quedaba contado como si el modelo hubiera
-- respondido: el resumen de consumo mostraba más cuota gastada que la real y
-- escondía la diferencia entre un intento fallido y una generación exitosa.
--
-- La reparación es deliberadamente estrecha: sólo filas sin tokens (entrada y
-- salida en 0) en estado de error. Una respuesta que sí generó tokens no se
-- toca, aunque el esquema haya sido inválido, porque esa cuota sí se consumió.
UPDATE ai_calls
   SET cuota_consumida = 0
 WHERE cuota_consumida <> 0
   AND tokens_entrada = 0
   AND tokens_salida = 0
   AND estado IN ('error', 'invalida');

-- Sin este PRAGMA, `inicializar()` vuelve a ejecutar la migración en un bucle
-- infinito porque la versión nunca avanza.
PRAGMA user_version = 8;
