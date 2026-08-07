"""Artefactos del modelo: la base como fuente de verdad, el disco como cache.

El escenario que estos tests reproducen es el de produccion: el job que entrena
y el servicio que predice corren en maquinas distintas con discos efimeros. Si
el modelo solo vive en disco, la API nunca lo ve — y el sintoma no es un error
claro sino un 409 permanente en `/veredicto`.
"""

from __future__ import annotations

import numpy as np
import pytest
from sqlalchemy import select

from app.ml.almacen import cargar_modelo, cargar_poisson_activo, guardar_en_base
from app.ml.modelo import ModeloPrediccion
from app.ml.persistencia import ARCHIVO_PUNTERO, guardar_poisson
from app.ml.poisson import ModeloPoissonBivariado
from app.modelos.prediccion import VersionModelo

VERSION = "v20260807T0000"


@pytest.fixture
def artefactos(tmp_path, db):
    """Entrena algo minimo, lo guarda en disco y registra la version activa."""
    X = np.array([[i % 5, i % 3, 0, 0, 0, 7, 7, 1, 1, 1, 1, 1500 + i, 1500] for i in range(30)])
    y = np.array(["L", "E", "V"] * 10, dtype=object)

    modelo = ModeloPrediccion().entrenar(X, y)
    modelo.guardar(tmp_path, VERSION)

    poisson = ModeloPoissonBivariado()
    poisson.parametros.partidos_usados = 100
    guardar_poisson(poisson, tmp_path, VERSION)

    db.add(VersionModelo(version=VERSION, algoritmo="logistica", activa=True))
    db.flush()
    guardar_en_base(db, VERSION, tmp_path)
    db.flush()
    return tmp_path


def _borrar_disco(directorio):
    """Simula el reinicio del servicio: el disco vuelve al estado del build."""
    for archivo in directorio.iterdir():
        archivo.unlink()


class TestGuardado:
    def test_los_artefactos_quedan_en_la_base(self, db, artefactos):
        fila = db.execute(select(VersionModelo)).scalar_one()
        assert fila.artefacto_modelo is not None
        assert fila.artefacto_poisson is not None

    def test_pesan_poco(self, db, artefactos):
        """Si esto crece a megabytes, guardarlos en la base deja de ser sano."""
        fila = db.execute(select(VersionModelo)).scalar_one()
        assert len(fila.artefacto_modelo) < 500_000

    def test_sin_fila_de_version_no_explota(self, db, tmp_path):
        """El entrenamiento pudo fallar antes de crear la fila; no debe romper."""
        guardar_en_base(db, "v-inexistente", tmp_path)


class TestCargaEnCascada:
    def test_lee_del_disco_cuando_esta(self, db, artefactos):
        cargado = cargar_modelo(db, artefactos)
        assert cargado is not None
        assert cargado[1] == VERSION

    def test_rehidrata_desde_la_base_con_el_disco_vacio(self, db, artefactos):
        """El caso de produccion: el servicio arranca sin ningun artefacto."""
        _borrar_disco(artefactos)
        assert not list(artefactos.iterdir())

        cargado = cargar_modelo(db, artefactos)

        assert cargado is not None
        modelo, version = cargado
        assert version == VERSION
        assert modelo.entrenado

    def test_la_rehidratacion_deja_el_disco_como_cache(self, db, artefactos):
        _borrar_disco(artefactos)
        cargar_modelo(db, artefactos)

        nombres = {a.name for a in artefactos.iterdir()}
        assert f"modelo_{VERSION}.joblib" in nombres
        assert ARCHIVO_PUNTERO in nombres

    def test_el_modelo_rehidratado_predice_igual(self, db, artefactos):
        vector = [[1, 2, 0, 0, 0, 7, 7, 1, 1, 1, 1, 1600, 1500]]
        antes = cargar_modelo(db, artefactos)[0].predecir_probabilidades(np.array(vector))

        _borrar_disco(artefactos)
        despues = cargar_modelo(db, artefactos)[0].predecir_probabilidades(np.array(vector))

        assert np.allclose(antes, despues)

    def test_el_poisson_tambien_se_rehidrata(self, db, artefactos):
        _borrar_disco(artefactos)
        poisson = cargar_poisson_activo(db, artefactos)
        assert poisson is not None
        assert poisson.ajustado

    def test_sin_modelo_entrenado_devuelve_none(self, db, tmp_path):
        assert cargar_modelo(db, tmp_path) is None
        assert cargar_poisson_activo(db, tmp_path) is None

    def test_una_version_sin_artefacto_no_se_puede_rehidratar(self, db, tmp_path):
        """Modelos entrenados antes de esta migracion: no rompen, solo no cargan."""
        db.add(VersionModelo(version="v-vieja", algoritmo="logistica", activa=True))
        db.flush()
        assert cargar_modelo(db, tmp_path) is None
