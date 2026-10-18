"""Mapeo de las 62 etiquetas multi-intención de MULTI3NLU++ a las 5 categorías
del Proyecto.

A diferencia de MASSIVE (una intención por frase), cada frase de MULTI3NLU++
trae un *conjunto* de etiquetas que combinan un tipo de acción
(`request_info`, `booking`, `cancel_close_leave_freeze`...), una entidad de
dominio (`card`, `account`, `appointment`...) y a veces un modificador de
pregunta (`how_much`, `when`...). No hay un mapeo 1 a 1 posible: hace falta
una regla de prioridad sobre el conjunto completo de etiquetas de cada frase.
Documentado en DEVLOG.md ("Reetiquetado de MULTI3NLU++").

La regla se evalúa de arriba hacia abajo; gana la primera que matchea. Mismo
principio que usa el código real para decisiones deterministas (ej. el menú
de `app/agents/eleccion.py`): previsible y auditable en vez de una lista de
condiciones sueltas.
"""
from typing import Optional

# Encontrados por revisión manual de las 423 frases en español de
# "wrong_notworking_notshowing" + "lost_stolen" (ver DEVLOG.md, "Revisión
# manual de los 423 'reclamo'"). La etiqueta original mezcla "está roto/no
# funciona" con "no aparece", y "no aparece" a veces resulta ser el ciudadano
# NEGANDO que haya un problema ("No, no fue revertido") o corrigiendo un dato
# de identidad en una verificación ("la fecha de nacimiento no es correcta,
# es el 5 de mayo de 1962") — ninguna de las dos cosas es una queja. Se
# excluyen por coincidencia exacta de texto, no hay una regla de etiquetas
# que las distinga limpiamente de los más de 400 casos que sí son quejas
# reales.
EXCLUSIONES_REVISADAS_A_MANO = {
    "Está pendiente",
    "No, este no es el nombre correcto del beneficiario.",
    "No sé si fue revertida",
    "no tengo nada pendiente",
    "No, la fecha de nacimiento es incorrecta, parece que tengo que repetir eso.",
    "no, esa no es la suma correcta.",
    "no, esa es la hora correcta",
    "No, no fue revertido",
    "la fecha de nacimiento no es correcta, es el 5 de mayo de 1962",
    "No creo que podamos llegar a la hora de salida",
    "No, no se ha perdido",
    "No, no lo olvidé.",
    "no lo olvidé",
    "¿tenéis oficina de objetos perdidos?",
}

# Entidades de dominio bancario -> si acompañan a una acción ambigua de alta/
# activación, esa acción es una gestión administrativa (trámite), no un turno.
ENTIDADES_BANCARIAS = {
    "account", "card", "loan", "mortgage", "direct_debit", "standing_order",
    "credit", "debit", "overdraft", "savings", "cheque", "pin",
}

# Entidades de servicios de hotel -> si acompañan a esa misma acción ambigua,
# es más parecido a pedir/agendar un servicio (reserva) que a un trámite.
ENTIDADES_HOTEL_RESERVABLES = {
    "restaurant", "spa", "gym", "room_service", "parking", "swimming_pool",
    "appointment", "booking",
}

# Etiquetas puramente conversacionales/meta, sin contenido de dominio.
ETIQUETAS_CONVERSACIONALES = {
    "greet", "thank", "affirm", "deny", "dont_know", "acknowledge",
    "repeat", "end_call", "handoff",
}

# Palabras de pregunta inequívocas: en este dataset aparecen casi siempre
# sobre una frase con "?" (cuánto, por qué, cómo, cuánto tiempo, cuándo).
# Se usan tanto para reforzar "consulta" en el fallback final como para
# desambiguar una acción ambigua (ver regla 4 y "transfer_payment_deposit").
PALABRAS_PREGUNTA = {"how_much", "why", "how", "how_long", "when"}

# Modificadores comparativos/temporales: "more_higher_after" y
# "less_lower_before" (más/menos, antes/después) NO son palabras de pregunta
# confiables por sí solas — aparecen igual de seguido en una restricción
# sobre una acción ("necesito hacer esa transferencia antes del 4 de
# noviembre", tags: make_open_apply_setup_get_activate + transfer_payment_
# deposit + less_lower_before) que en una pregunta comparativa real. Por eso
# sólo entran como señal débil en el fallback final, nunca para desambiguar
# una acción — encontrado por inspección manual (ver DEVLOG.md).
MODIFICADORES_DEBILES = {"more_higher_after", "less_lower_before"}


def clasificar(tags: set[str]) -> Optional[tuple[str, float]]:
    """Devuelve (categoria, confianza) para un conjunto de etiquetas de
    MULTI3NLU++, o None si no hay ninguna señal utilizable (frase puramente
    conversacional sin acompañar un reclamo/consulta real)."""

    # 1) Reclamo: algo anda mal o se perdió/robó. Gana siempre, sin importar
    #    qué otra etiqueta de dominio acompañe — es la señal que MASSIVE no
    #    tenía (ver DEVLOG.md).
    if "wrong_notworking_notshowing" in tags:
        return ("reclamo", 0.90)
    if "lost_stolen" in tags:
        return ("reclamo", 0.88)

    # 2) Reserva: agendar/pedir un turno o servicio a futuro.
    if "booking" in tags:
        return ("reserva", 0.88)
    if "check_in" in tags or "check_out" in tags:
        return ("reserva", 0.75)

    # 3) Trámite: cancelar/cerrar, modificar, o pagar/transferir algo propio.
    #    "transfer_payment_deposit" (la 2da etiqueta más frecuente del
    #    dataset) necesita su propia regla: por defecto es una acción a
    #    ejecutar (trámite), salvo que también traiga una palabra de
    #    pregunta — ahí es alguien preguntando sobre una transferencia, no
    #    pidiendo hacerla. Encontrado por inspección manual: "¿cuándo vence
    #    mi próximo débito directo...?" y "¿cuál es el límite mensual...?"
    #    (ambos con "when"/"how_much" + transfer_payment_deposit, sin
    #    "request_info") caían en trámite siendo preguntas claras.
    if "cancel_close_leave_freeze" in tags:
        return ("tramite", 0.85)
    if "change" in tags:
        return ("tramite", 0.75)
    if "transfer_payment_deposit" in tags:
        if "request_info" in tags or (tags & PALABRAS_PREGUNTA):
            return ("consulta", 0.70)
        return ("tramite", 0.72)

    # 4) Alta/activación: ambigua por sí sola — la desambigua la entidad de
    #    dominio que la acompaña.
    if "make_open_apply_setup_get_activate" in tags:
        if tags & ENTIDADES_HOTEL_RESERVABLES:
            return ("reserva", 0.70)
        if tags & ENTIDADES_BANCARIAS:
            return ("tramite", 0.78)
        # Sin entidad reconocida: si además trae una palabra de pregunta
        # inequívoca, es más probable que esté pidiendo información que
        # ejecutando una acción. Encontrado por inspección manual: "¿cuánto
        # pagaría de más al cambiar libras a euros en Italia?" (how_much +
        # fees_interests + international + make_open_apply_setup_get_
        # activate) caía en trámite por descarte, siendo una consulta de
        # precio. Sólo PALABRAS_PREGUNTA (no los modificadores débiles):
        # ver el comentario de MODIFICADORES_DEBILES más arriba.
        if "request_info" in tags or (tags & PALABRAS_PREGUNTA):
            return ("consulta", 0.65)
        return ("tramite", 0.55)

    # 5) Consulta: pedir información, sin ejecutar ninguna acción.
    if "request_info" in tags:
        return ("consulta", 0.85)
    if "balance" in tags:
        return ("consulta", 0.80)
    if tags & PALABRAS_PREGUNTA:
        return ("consulta", 0.65)
    if tags & MODIFICADORES_DEBILES:
        return ("consulta", 0.45)

    # 6) Puramente conversacional, sin ninguna señal de dominio.
    if tags & ETIQUETAS_CONVERSACIONALES:
        return ("otro", 0.60)

    # 7) Sólo quedan entidades de dominio sueltas (ej. "card" sin ninguna
    #    acción): no hay suficiente señal para clasificar con confianza.
    return ("otro", 0.35)
