"""Mapeo de las 60 intenciones de MASSIVE (es) a las 5 categorías del Proyecto.

Decisión documentada en DEVLOG.md ("Reetiquetado de MASSIVE"): como MASSIVE es
un dataset de asistente de propósito general (alarmas, IoT, música...) y no de
atención ciudadana, el mapeo no busca equivalencia de dominio sino de *patrón
de comportamiento* — preguntar información, agendar algo, cancelar/gestionar
algo propio, o chau — como warm-start de la clasificación antes de que los
ejemplos de tool calling (manuales) enseñen el dominio real.

confianza: heurística fija por intención (qué tan inequívoco es el mapeo a la
categoría elegida), no una medición. Documentado así en DEVLOG.md.
"""

# intención MASSIVE -> (categoría del Proyecto, confianza heurística)
MAPEO: dict[str, tuple[str, float]] = {
    # --- consulta: pedir información, sin ejecutar una acción propia ---
    "alarm_query": ("consulta", 0.85),
    "calendar_query": ("consulta", 0.85),
    "cooking_query": ("consulta", 0.80),
    "cooking_recipe": ("consulta", 0.75),
    "datetime_convert": ("consulta", 0.80),
    "datetime_query": ("consulta", 0.85),
    "email_query": ("consulta", 0.85),
    "email_querycontact": ("consulta", 0.80),
    "lists_query": ("consulta", 0.80),
    "music_query": ("consulta", 0.75),
    "news_query": ("consulta", 0.85),
    "qa_currency": ("consulta", 0.85),
    "qa_definition": ("consulta", 0.85),
    "qa_factoid": ("consulta", 0.85),
    "qa_maths": ("consulta", 0.85),
    "qa_stock": ("consulta", 0.85),
    "recommendation_events": ("consulta", 0.75),
    "recommendation_locations": ("consulta", 0.75),
    "recommendation_movies": ("consulta", 0.70),
    "social_query": ("consulta", 0.75),
    "takeaway_query": ("consulta", 0.80),
    "transport_query": ("consulta", 0.85),
    "transport_traffic": ("consulta", 0.85),
    "weather_query": ("consulta", 0.90),
    # --- reserva: agendar/reservar algo para un momento futuro ---
    "alarm_set": ("reserva", 0.85),
    "calendar_set": ("reserva", 0.90),
    "takeaway_order": ("reserva", 0.75),
    "transport_taxi": ("reserva", 0.80),
    "transport_ticket": ("reserva", 0.85),
    # --- tramite: alta/baja/gestión administrativa sobre algo propio,
    #     sin tool todavía (igual que "tramite" en el sistema real: escala) ---
    "alarm_remove": ("tramite", 0.75),
    "calendar_remove": ("tramite", 0.75),
    "email_addcontact": ("tramite", 0.70),
    "email_sendemail": ("tramite", 0.70),
    "lists_createoradd": ("tramite", 0.70),
    "lists_remove": ("tramite", 0.70),
    # --- otro: comandos de dispositivo, chitchat, sin correlato en el dominio ---
    "audio_volume_down": ("otro", 0.90),
    "audio_volume_mute": ("otro", 0.90),
    "audio_volume_other": ("otro", 0.85),
    "audio_volume_up": ("otro", 0.90),
    "general_greet": ("otro", 0.90),
    "general_joke": ("otro", 0.90),
    "general_quirky": ("otro", 0.85),
    "iot_cleaning": ("otro", 0.90),
    "iot_coffee": ("otro", 0.90),
    "iot_hue_lightchange": ("otro", 0.90),
    "iot_hue_lightdim": ("otro", 0.90),
    "iot_hue_lightoff": ("otro", 0.90),
    "iot_hue_lighton": ("otro", 0.90),
    "iot_hue_lightup": ("otro", 0.90),
    "iot_wemo_off": ("otro", 0.90),
    "iot_wemo_on": ("otro", 0.90),
    "music_dislikeness": ("otro", 0.85),
    "music_likeness": ("otro", 0.85),
    "music_settings": ("otro", 0.85),
    "play_audiobook": ("otro", 0.85),
    "play_game": ("otro", 0.85),
    "play_music": ("otro", 0.85),
    "play_podcasts": ("otro", 0.85),
    "play_radio": ("otro", 0.85),
    "social_post": ("otro", 0.80),
}

# Nota: "reclamo" no tiene ninguna intención de MASSIVE mapeada — hallazgo
# documentado en DEVLOG.md ("MASSIVE no tiene ninguna intención de queja/
# reclamo"). Esa categoría depende por completo de los ejemplos manuales.

assert len(MAPEO) == 60, f"Se esperaban 60 intenciones de MASSIVE, hay {len(MAPEO)}"
