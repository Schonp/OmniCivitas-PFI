import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import borrar_hilos
from app.core.dependencies import get_current_user, requiere_rol
from app.db.crud.casos import listar_casos_de_ciudadano
from app.db.crud.ciudadanos import crear_ciudadano, esta_identificado, obtener_ciudadano_por_id
from app.db.crud.interacciones import actividad_de_casos
from app.db.crud.titulares import dar_de_baja_titular, datos_del_titular, rectificar_titular
from app.db.models import RolUsuario, Usuario
from app.db.session import get_db
from app.schemas.ciudadano import (
    CasoEnFichaOut,
    CiudadanoCreate,
    CiudadanoOut,
    CiudadanoRectificacion,
    FichaCiudadanoOut,
    UltimoMensajeOut,
)

# En la ficha alcanza con ver de qué iba el último mensaje.
MAX_CARACTERES_ULTIMO_MENSAJE = 200

router = APIRouter(prefix="/api/ciudadanos", tags=["ciudadanos"])


@router.post("", response_model=CiudadanoOut, status_code=status.HTTP_201_CREATED)
async def crear(
    datos: CiudadanoCreate,
    db: AsyncSession = Depends(get_db),
    _usuario=Depends(get_current_user),
) -> CiudadanoOut:
    return await crear_ciudadano(db, datos)


@router.get("/{ciudadano_id}", response_model=CiudadanoOut)
async def obtener(
    ciudadano_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _usuario=Depends(get_current_user),
) -> CiudadanoOut:
    ciudadano = await obtener_ciudadano_por_id(db, ciudadano_id)
    if ciudadano is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ciudadano no encontrado")
    return ciudadano


@router.get("/{ciudadano_id}/ficha", response_model=FichaCiudadanoOut)
async def ficha(
    ciudadano_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(get_current_user),
) -> FichaCiudadanoOut:
    """Los casos del vecino en todos los canales, para atenderlo con la historia
    completa en vez de caso por caso.

    El supervisor ve la ficha de cualquiera. El operador, solo la de un vecino
    con algún caso suyo (si no, 404, como un caso ajeno): ve todos sus casos,
    pero el resumen y el último mensaje solo de los que puede abrir.
    """
    ciudadano = await obtener_ciudadano_por_id(db, ciudadano_id)
    if ciudadano is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ciudadano no encontrado")

    casos = await listar_casos_de_ciudadano(db, ciudadano.id)
    es_operador = usuario_actual.rol == RolUsuario.operador
    if es_operador and not any(c.operador_asignado_id == usuario_actual.id for c in casos):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ciudadano no encontrado")

    actividad = await actividad_de_casos(db, [c.id for c in casos])
    en_ficha = []
    for caso in casos:
        del_caso = actividad[caso.id]
        puede_abrir = not es_operador or caso.operador_asignado_id == usuario_actual.id
        ultimo = None
        if puede_abrir and del_caso.ultimo is not None:
            ultimo = UltimoMensajeOut.model_validate(del_caso.ultimo).model_copy(
                update={"contenido": del_caso.ultimo.contenido[:MAX_CARACTERES_ULTIMO_MENSAJE]}
            )
        en_ficha.append(
            CasoEnFichaOut(
                id=caso.id,
                referencia=caso.referencia,
                tipo=caso.tipo,
                estado=caso.estado,
                canal_origen=caso.canal_origen,
                canal_actual=caso.canal_actual,
                operador_asignado=caso.operador_asignado,
                created_at=caso.created_at,
                updated_at=caso.updated_at,
                mensajes=del_caso.mensajes,
                recorrido=del_caso.recorrido,
                puede_abrir=puede_abrir,
                resumen_ia=caso.resumen_ia if puede_abrir else None,
                ultimo_mensaje=ultimo,
            )
        )

    # Los canales del vecino en el orden en que los fue usando: los casos vienen
    # del más reciente al más viejo.
    canales = []
    for caso in reversed(en_ficha):
        canales += [canal for canal in caso.recorrido if canal not in canales]
    momentos = [a.ultimo.timestamp for a in actividad.values() if a.ultimo is not None]
    return FichaCiudadanoOut(
        id=ciudadano.id,
        nombre=ciudadano.nombre,
        documento=ciudadano.documento,
        identificado=esta_identificado(ciudadano),
        canales=canales,
        primer_contacto=min((c.created_at for c in casos), default=None),
        ultimo_contacto=max(momentos, default=None),
        casos=en_ficha,
    )


# --- Derechos del titular (Ley 25.326) ------------------------------------------
# Solo el supervisor: el operador trabaja los casos sin ver datos de contacto, y
# exportar o borrar los datos de una persona no es parte de atender un caso.


async def _titular(db: AsyncSession, ciudadano_id: uuid.UUID):
    ciudadano = await obtener_ciudadano_por_id(db, ciudadano_id)
    if ciudadano is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ciudadano no encontrado")
    return ciudadano


@router.get("/{ciudadano_id}/datos")
async def exportar_datos(
    ciudadano_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _supervisor: Usuario = Depends(requiere_rol(RolUsuario.supervisor)),
) -> dict:
    """Derecho de acceso (RF-14): todo lo que el sistema guarda sobre el titular."""
    return await datos_del_titular(db, await _titular(db, ciudadano_id))


@router.patch("/{ciudadano_id}", response_model=CiudadanoOut)
async def rectificar(
    ciudadano_id: uuid.UUID,
    datos: CiudadanoRectificacion,
    db: AsyncSession = Depends(get_db),
    supervisor: Usuario = Depends(requiere_rol(RolUsuario.supervisor)),
) -> CiudadanoOut:
    """Derecho de rectificación (RF-14)."""
    ciudadano = await _titular(db, ciudadano_id)
    return await rectificar_titular(
        db, ciudadano, actor=supervisor.email, nombre=datos.nombre, email=datos.email, telefono=datos.telefono
    )


@router.post("/{ciudadano_id}/baja", status_code=status.HTTP_204_NO_CONTENT)
async def dar_de_baja(
    ciudadano_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    supervisor: Usuario = Depends(requiere_rol(RolUsuario.supervisor)),
) -> None:
    """Derecho de supresión (RF-13): borra sus datos y anonimiza su historial."""
    hilos = await dar_de_baja_titular(db, await _titular(db, ciudadano_id), actor=supervisor.email)
    await borrar_hilos(hilos)

