import csv
import io
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.resumen import generar_resumen_caso
from app.core.dependencies import get_current_user, requiere_rol
from app.db.crud.auditoria import listar_auditoria_de_caso
from app.db.crud.casos import (
    actualizar_resumen_caso,
    asignar_caso,
    cambiar_estado_caso,
    contar_casos,
    contar_casos_por_estado,
    crear_caso,
    esperas_de_casos,
    listar_casos,
    obtener_caso_por_id,
    responder_caso,
)
from app.db.crud.ciudadanos import obtener_ciudadano_por_id
from app.db.crud.interacciones import listar_interacciones_de_caso
from app.db.crud.usuarios import obtener_usuario_por_id
from app.db.models import Caso, EstadoCaso, RolUsuario, Usuario
from app.db.session import get_db
from app.schemas.auditoria import AuditoriaOut
from app.schemas.caso import (
    CasoAsignacionUpdate,
    CasoCreate,
    CasoEstadoUpdate,
    CasoOut,
    ConteoCasosOut,
    RespuestaOperadorCreate,
)
from app.schemas.interaccion import InteraccionOut

router = APIRouter(prefix="/api/casos", tags=["casos"])

solo_supervisor = requiere_rol(RolUsuario.supervisor)


def _filtro_de_visibilidad(usuario: Usuario) -> uuid.UUID | None:
    """El operador solo ve su propia bandeja; el supervisor ve todo el organismo."""
    return usuario.id if usuario.rol == RolUsuario.operador else None


async def _caso_visible(db: AsyncSession, caso_id: uuid.UUID, usuario: Usuario) -> Caso:
    """404 y no 403 cuando el caso no es del operador: confirmar que existe ya
    filtraría información de un ciudadano que no le corresponde."""
    caso = await obtener_caso_por_id(db, caso_id)
    if caso is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Caso no encontrado")
    if usuario.rol == RolUsuario.operador and caso.operador_asignado_id != usuario.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Caso no encontrado")
    return caso


@router.post("", response_model=CasoOut, status_code=status.HTTP_201_CREATED)
async def crear(
    datos: CasoCreate,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(solo_supervisor),
) -> CasoOut:
    if await obtener_ciudadano_por_id(db, datos.ciudadano_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ciudadano no encontrado")

    return await crear_caso(db, datos, actor=usuario_actual.email)


@router.get("", response_model=list[CasoOut])
async def listar(
    response: Response,
    estado: EstadoCaso | None = Query(default=None),
    q: str | None = Query(default=None, max_length=100),
    sin_asignar: bool = Query(default=False),
    limite: int = Query(default=50, ge=1, le=200),
    desplazamiento: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(get_current_user),
) -> list[CasoOut]:
    operador_id = _filtro_de_visibilidad(usuario_actual)
    filtros = {
        "estado": estado,
        "busqueda": q,
        "operador_id": operador_id,
        "solo_sin_asignar": sin_asignar and operador_id is None,
    }

    casos = await listar_casos(db, limite=limite, desplazamiento=desplazamiento, **filtros)
    response.headers["X-Total-Count"] = str(await contar_casos(db, **filtros))

    esperas = await esperas_de_casos(db, casos)
    return [
        CasoOut.model_validate(caso).model_copy(update={"esperando_desde": esperas.get(caso.id)})
        for caso in casos
    ]


@router.get("/conteos", response_model=ConteoCasosOut)
async def conteos(
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(get_current_user),
) -> ConteoCasosOut:
    """Contadores de los filtros de la bandeja, con la visibilidad del rol."""
    por_estado = await contar_casos_por_estado(
        db, operador_id=_filtro_de_visibilidad(usuario_actual)
    )
    return ConteoCasosOut(todos=sum(por_estado.values()), por_estado=por_estado)


@router.get("/exportar")
async def exportar(
    db: AsyncSession = Depends(get_db),
    _usuario: Usuario = Depends(solo_supervisor),
) -> Response:
    """Descarga de los casos para reportes del organismo."""
    casos = await listar_casos(db, limite=200)

    salida = io.StringIO()
    planilla = csv.writer(salida, delimiter=";")
    planilla.writerow(
        [
            "caso_id",
            "ciudadano",
            "documento",
            "tipo",
            "estado",
            "motivo_cierre",
            "canal_origen",
            "canal_actual",
            "operador_asignado",
            "creado",
            "actualizado",
        ]
    )
    for caso in casos:
        planilla.writerow(
            [
                caso.id,
                caso.ciudadano.nombre,
                caso.ciudadano.documento,
                caso.tipo.value,
                caso.estado.value,
                caso.motivo_cierre or "",
                caso.canal_origen.value,
                caso.canal_actual.value,
                caso.operador_asignado.nombre if caso.operador_asignado else "",
                caso.created_at.isoformat(),
                caso.updated_at.isoformat(),
            ]
        )

    return Response(
        content=salida.getvalue().encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="casos-omnicivitas.csv"'},
    )


@router.get("/{caso_id}", response_model=CasoOut)
async def obtener(
    caso_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(get_current_user),
) -> CasoOut:
    caso = await _caso_visible(db, caso_id, usuario_actual)
    esperas = await esperas_de_casos(db, [caso])
    return CasoOut.model_validate(caso).model_copy(
        update={"esperando_desde": esperas.get(caso.id)}
    )


@router.patch("/{caso_id}/estado", response_model=CasoOut)
async def cambiar_estado(
    caso_id: uuid.UUID,
    datos: CasoEstadoUpdate,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(get_current_user),
) -> CasoOut:
    caso = await _caso_visible(db, caso_id, usuario_actual)
    return await cambiar_estado_caso(
        db, caso, datos.estado, actor=usuario_actual.email, motivo=datos.motivo
    )


@router.patch("/{caso_id}/asignacion", response_model=CasoOut)
async def asignar(
    caso_id: uuid.UUID,
    datos: CasoAsignacionUpdate,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(solo_supervisor),
) -> CasoOut:
    caso = await obtener_caso_por_id(db, caso_id)
    if caso is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Caso no encontrado")

    operador: Usuario | None = None
    if datos.operador_asignado_id is not None:
        operador = await obtener_usuario_por_id(db, str(datos.operador_asignado_id))
        if operador is None or not operador.activo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Operador no encontrado"
            )

    return await asignar_caso(db, caso, operador, actor=usuario_actual.email)


@router.post("/{caso_id}/resumen", response_model=CasoOut)
async def resumir(
    caso_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(get_current_user),
) -> CasoOut:
    """Genera (o regenera) con IA el resumen del caso para el operador."""
    caso = await _caso_visible(db, caso_id, usuario_actual)

    try:
        resumen = await generar_resumen_caso(db, caso)
    except Exception as excepcion:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="El servicio de IA no está disponible: intente de nuevo más tarde",
        ) from excepcion

    if resumen is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El caso todavía no tiene interacciones para resumir",
        )

    caso = await actualizar_resumen_caso(db, caso, resumen, actor=usuario_actual.email)
    esperas = await esperas_de_casos(db, [caso])
    return CasoOut.model_validate(caso).model_copy(
        update={"esperando_desde": esperas.get(caso.id)}
    )


@router.post(
    "/{caso_id}/respuesta",
    response_model=InteraccionOut,
    status_code=status.HTTP_201_CREATED,
)
async def responder(
    caso_id: uuid.UUID,
    datos: RespuestaOperadorCreate,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(get_current_user),
) -> InteraccionOut:
    """Respuesta al ciudadano sobre el canal actual, o nota interna del organismo."""
    caso = await _caso_visible(db, caso_id, usuario_actual)
    if caso.estado == EstadoCaso.cerrado and not datos.interna:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El caso está cerrado: reabralo antes de responder",
        )

    return await responder_caso(
        db, caso, datos.contenido, actor=usuario_actual.email, interna=datos.interna
    )


@router.get("/{caso_id}/interacciones", response_model=list[InteraccionOut])
async def interacciones(
    caso_id: uuid.UUID,
    limite: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(get_current_user),
) -> list[InteraccionOut]:
    await _caso_visible(db, caso_id, usuario_actual)
    return await listar_interacciones_de_caso(db, caso_id, limite=limite)


@router.get("/{caso_id}/auditoria", response_model=list[AuditoriaOut])
async def auditoria(
    caso_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(get_current_user),
) -> list[AuditoriaOut]:
    await _caso_visible(db, caso_id, usuario_actual)
    return await listar_auditoria_de_caso(db, caso_id)
