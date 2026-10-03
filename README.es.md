# Escape the Backrooms Trainer

[简体中文](README.md) | [English](README.en.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | [Deutsch](README.de.md) | [Français](README.fr.md) | **Español** | [Русский](README.ru.md) | [Português](README.pt-BR.md)

Un overlay de información con funciones divertidas para *Escape the Backrooms* (Steam 1943950, UE 4.27). Escrito en Python puro, solo con la biblioteca estándar. Lee y escribe la memoria del juego desde fuera e instala un pequeño hook en `UObject::ProcessEvent` para llamar a las UFunctions del propio juego en el hilo del juego.

> Solo para el modo de un jugador o tu propia sala (con amigos que lo sepan), para divertirse y aprender ingeniería inversa de UE.
> Este proyecto no tiene ninguna relación con Fancy Games ni con Steam. Úsalo bajo tu propia responsabilidad; los offsets y firmas pueden dejar de funcionar tras una actualización del juego.
>
> Nota: el panel en pantalla y los mensajes están, por ahora, solo en chino simplificado.

## Funciones

**Overlay** (solo lectura, no modifica el juego)
- Muestra en pantalla monstruos, objetos, salidas, zonas de caída y compañeros con su distancia; los objetivos fuera de pantalla tienen una flecha en el borde
- Panel superior izquierdo: nivel, coordenadas, resistencia, distancia al monstruo más cercano (en rojo a menos de 15 m), lista de salidas y objetos
- Radar en la esquina superior derecha (orientado a la cámara, alcance 40 m, monstruos lejanos fijados en el borde); lista de compañeros con nombre, vivo/muerto, distancia y cordura
- Se oculta cuando el juego no está en primer plano y se cierra cuando se cierra el juego

**Atajos de teclado** (tu rol se detecta automáticamente: un jugador / anfitrión / cliente)

| Tecla | Anfitrión / un jugador | Cliente |
|---|---|---|
| F5 | Poseer al monstruo más cercano (WASD para moverse, ratón para girar, Espacio para saltar, Mayús para correr); pulsa otra vez para volver a tu cuerpo | Cambiar a la vista del monstruo más cercano (solo mirar) |
| F6 | Congelar / descongelar a todos los monstruos | No disponible (oculto) |
| F7 | Volar + atravesar paredes (Espacio sube, Ctrl baja) | No disponible (oculto) |
| F2 | Aumento de velocidad + resistencia infinita | Aumento de velocidad (mediante RPC de servidor) |
| F3 | Vista en tercera persona | Igual |
| F4 / Mayús+F4 | Cambiar de aspecto: trajes del juego (visibles para los demás) o modelos de monstruos/personajes del nivel (solo visibles para ti) | Igual |
| Insert | Teletransportarse a la salida más cercana | No disponible (oculto) |
| Supr | Revivir en el lugar donde moriste | No disponible (oculto) |
| F11 | Invencible: ni monstruos, ni caídas, ni ahogamiento pueden matarte (solo a ti, no a tus compañeros) | No disponible (oculto) |
| F1 | Visión nocturna: más exposición, sin viñeta, grano ni aberración cromática | Igual |
| Alt+1 | Cámara libre: separar la cámara del cuerpo y volar con ella (WASD, Espacio/Ctrl subir/bajar, Mayús más rápido) | Igual |
| Alt+2 | Cordura bloqueada al máximo | Igual |
| Alt+3 | Activar el aumento de velocidad + resistencia del propio juego | Igual |
| Alt+4 | Supersalto | Igual |
| Alt+5 | Atravesar paredes: pedir al servidor que desactive tu colisión | No disponible (oculto) |
| Alt+6 | Recoger a distancia el objeto tirado más cercano | Igual (depende de si el anfitrión comprueba la distancia) |
| Alt+7 | Interactuar a distancia con el elemento bajo la mira | Igual (depende de si el anfitrión comprueba la distancia) |
| Alt+8 | Escribir el objeto elegido con RePág/AvPág en un hueco libre del inventario | Igual |
| Alt+9 | Bloquear las animaciones de susto (solo lo que ves; no evita la muerte) | Igual |
| RePág / AvPág + Inicio | Elegir un objeto y generarlo en tus manos | Igual |
| F8 / F9 / F10 | Ocultar overlay / mostrar objetos / mostrar elementos interactivos | Igual |
| Fin | Revertir todos los cambios, quitar el hook y salir | Igual |

- Modelos propios como aspecto: pon un pak de mod en `Paks\~mods` del juego, añade su ruta en `custom_skins.txt` y cámbialo con F4. Ver [MODDING.md](MODDING.md) (en chino)

## Uso

1. Pon el juego en modo **ventana** o **ventana sin bordes** (la pantalla completa exclusiva tapa el overlay) y entra en un nivel.
2. Elige una opción:
   - descarga `ETB-Trainer.exe` desde Releases y haz doble clic (no necesita Python), o
   - instala Python 3.10+, descarga el código fuente y haz doble clic en `启动覆盖层.bat` («iniciar overlay»), o ejecuta `python etb_overlay.py`.
3. Pulsa **Fin** para salir. Primero se revierten la posesión, la congelación, el vuelo, los aspectos, etc., y después se quita el hook.

El exe de un solo archivo está empaquetado con PyInstaller y algunos antivirus pueden marcarlo como falso positivo. Si te preocupa, ejecútalo desde el código fuente.

## Archivos

| Archivo | Descripción |
|---|---|
| `etb_overlay.py` | Punto de entrada: ventana del overlay, lectura de memoria, clasificación de actores, proyección de mundo a pantalla |
| `etb_trainer.py` | Funciones de los atajos, ejecutadas en un hilo en segundo plano del proceso del overlay |
| `etb_call.py` | Hook de ProcessEvent + llamador de UFunctions que arma los parámetros por reflexión (admite llamadas por lotes) |
| `etb_ue.lua` | Script de Cheat Engine: localiza GNames / GObjects / GWorld por AOB, con funciones auxiliares para nombres, reflexión y recorrido de actores |
| `NOTES.md` | Notas de ingeniería inversa (en chino): globales, cadenas de punteros, offsets, funcionamiento del hook |
| `FUNCTIONS.md` | Lista de funciones invocables (descripciones en chino; selección + firmas completas de 1729 funciones en 212 clases del juego) |

## Cómo funciona

- Al iniciar, escanea las secciones ejecutables del módulo principal con firmas AOB para encontrar `GNames` (FNamePool), `GUObjectArray` y `GWorld`. Todo lo demás se lee según la estructura de UE 4.27 y la reflexión en tiempo de ejecución.
- Los primeros 19 bytes de `ProcessEvent` se sustituyen por un `jmp` a una code cave. Esta comprueba que el hilo actual es el hilo del juego, reserva la bandera de llamada con `lock cmpxchg`, ejecuta el lote de llamadas escrito desde fuera, luego ejecuta el prólogo original y vuelve. Así, todas las llamadas a funciones del juego ocurren en el propio hilo principal del juego.
- Detección del rol: si `Actor::Role` del personaje local es Authority, `World::NetDriver` distingue entre un jugador y anfitrión; AutonomousProxy significa cliente.

Más detalles en [NOTES.md](NOTES.md) (en chino).

## Compatibilidad

Escrito y probado en el build de Steam 24997718. Si tras una actualización aparece «AOB 没找到» (AOB no encontrado) o «ProcessEvent 开头字节和预期不同» (prólogo de ProcessEvent inesperado), hay que volver a localizar las direcciones.

## Licencia

[MIT](LICENSE)
