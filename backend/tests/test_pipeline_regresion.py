"""Regresion del pipeline de prediccion, de punta a punta.

Se genera un historico sintetico con semilla fija, se entrena, se predice y se
verifican las invariantes que el producto no puede romper nunca:

- las probabilidades son una distribucion valida (suman 1, cada una en [0, 1]);
- el mismo dataset produce el mismo modelo (reproducibilidad);
- la validacion walk-forward nunca entrena con partidos posteriores;
- el modelo aprende senal real: supera a predecir al azar sobre datos con senal.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from app.ml.features import NOMBRES_FEATURES, PartidoHistorico
from app.ml.modelo import CLASES, ModeloPrediccion
from app.ml.poisson import ModeloPoissonBivariado, pmf_bivariada
from app.ml.validacion import (
    brier_multiclase,
    linea_base_siempre_local,
    log_loss_multiclase,
    validacion_walk_forward,
)
from app.servicios.entrenamiento import construir_dataset, entrenar_modelo
from app.servicios.metricas import recalcular_metricas_por_jornada, resumen_global
from app.servicios.predicciones import backfill_historico, generar_predicciones, modelo_activo
from tests.conftest import crear_partido

BASE = datetime(2024, 1, 1, tzinfo=timezone.utc)
SEMILLA = 20260807


def historico_sintetico(n_equipos: int = 10, jornadas: int = 60) -> list[PartidoHistorico]:
    """Liga simulada donde la fuerza de cada equipo determina los goles.

    Hay senal real que aprender: si el modelo no la encuentra, algo se rompio.
    """
    rng = random.Random(SEMILLA)
    fuerza = {e: 0.7 + 0.09 * e for e in range(1, n_equipos + 1)}
    partidos: list[PartidoHistorico] = []
    identificador = 0

    for jornada in range(jornadas):
        ids = list(range(1, n_equipos + 1))
        rng.shuffle(ids)
        for local, visitante in zip(ids[::2], ids[1::2], strict=False):
            identificador += 1
            lam_local = 1.4 * fuerza[local] / fuerza[visitante]
            lam_visitante = 1.0 * fuerza[visitante] / fuerza[local]
            partidos.append(
                PartidoHistorico(
                    id=identificador,
                    equipo_local_id=local,
                    equipo_visitante_id=visitante,
                    fecha=BASE + timedelta(days=7 * jornada),
                    goles_local=_poisson(rng, lam_local),
                    goles_visitante=_poisson(rng, lam_visitante),
                )
            )
    return partidos


def _poisson(rng: random.Random, lam: float) -> int:
    limite, k, producto = np.exp(-lam), 0, 1.0
    while producto > limite and k <= 12:
        producto *= rng.random()
        k += 1
    return max(0, k - 1)


@pytest.fixture(scope="module")
def dataset():
    X, y, ids, _ = construir_dataset(historico_sintetico())
    return X, y, ids


class TestDataset:
    def test_forma_y_orden_de_columnas(self, dataset):
        X, y, ids = dataset
        assert X.shape[1] == len(NOMBRES_FEATURES)
        assert len(X) == len(y) == len(ids)
        assert X.shape[0] > 100

    def test_etiquetas_validas(self, dataset):
        _, y, _ = dataset
        assert set(y) <= set(CLASES)
        assert len(set(y)) == 3  # aparecen las tres clases

    def test_sin_nan_ni_infinitos(self, dataset):
        X, _, _ = dataset
        assert np.isfinite(X).all()

    def test_reproducible(self):
        primera, _, _, _ = construir_dataset(historico_sintetico())
        segunda, _, _, _ = construir_dataset(historico_sintetico())
        assert np.array_equal(primera, segunda)

    def test_ids_en_orden_cronologico(self, dataset):
        _, _, ids = dataset
        assert ids == sorted(ids)


class TestModelo:
    def test_probabilidades_son_distribucion_valida(self, dataset):
        X, y, _ = dataset
        modelo = ModeloPrediccion().entrenar(X[:200], y[:200])
        probs = modelo.predecir_probabilidades(X[200:])
        assert probs.shape[1] == 3
        assert np.allclose(probs.sum(axis=1), 1.0)
        assert ((probs >= 0) & (probs <= 1)).all()

    def test_columnas_en_orden_local_empate_visitante(self, dataset):
        """sklearn ordena las clases alfabeticamente (E, L, V); nosotros L, E, V."""
        X, y, _ = dataset
        modelo = ModeloPrediccion().entrenar(X[:200], y[:200])
        crudas = modelo.pipeline.predict_proba(X[200:201])[0]
        clases = list(modelo.pipeline.named_steps["clasificador"].classes_)
        ordenadas = modelo.predecir_probabilidades(X[200:201])[0]
        assert ordenadas[0] == pytest.approx(crudas[clases.index("L")])
        assert ordenadas[1] == pytest.approx(crudas[clases.index("E")])
        assert ordenadas[2] == pytest.approx(crudas[clases.index("V")])

    def test_entrenamiento_determinista(self, dataset):
        X, y, _ = dataset
        uno = ModeloPrediccion(semilla=42).entrenar(X[:200], y[:200])
        otro = ModeloPrediccion(semilla=42).entrenar(X[:200], y[:200])
        assert np.allclose(
            uno.predecir_probabilidades(X[200:]), otro.predecir_probabilidades(X[200:])
        )

    def test_predecir_una_coincide_con_el_lote(self, dataset):
        X, y, _ = dataset
        modelo = ModeloPrediccion().entrenar(X[:200], y[:200])
        individual = modelo.predecir_una(list(X[201]))
        lote = modelo.predecir_probabilidades(X[201:202])[0]
        assert individual.como_tupla() == pytest.approx(tuple(lote))

    def test_modelo_sin_entrenar_falla_explicito(self, dataset):
        X, _, _ = dataset
        with pytest.raises(RuntimeError, match="no fue entrenado"):
            ModeloPrediccion().predecir_probabilidades(X[:1])

    def test_entrenar_sin_datos_falla(self):
        with pytest.raises(ValueError, match="No hay datos"):
            ModeloPrediccion().entrenar(np.empty((0, len(NOMBRES_FEATURES))), np.array([]))

    def test_algoritmo_desconocido_falla(self):
        with pytest.raises(ValueError, match="no soportado"):
            ModeloPrediccion(algoritmo="magia-negra")

    def test_random_forest_tambien_funciona(self, dataset):
        X, y, _ = dataset
        probs = (
            ModeloPrediccion(algoritmo="random_forest")
            .entrenar(X[:200], y[:200])
            .predecir_probabilidades(X[200:])
        )
        assert np.allclose(probs.sum(axis=1), 1.0)

    def test_guardar_y_cargar_preserva_las_predicciones(self, dataset, artefactos_limpios):
        X, y, _ = dataset
        original = ModeloPrediccion().entrenar(X[:200], y[:200])
        original.guardar(artefactos_limpios, "vtest")

        recuperado = ModeloPrediccion.cargar_activo(artefactos_limpios)
        assert recuperado is not None
        assert recuperado.version == "vtest"
        assert np.allclose(
            original.predecir_probabilidades(X[200:]),
            recuperado.predecir_probabilidades(X[200:]),
        )

    def test_cargar_activo_sin_artefacto_devuelve_none(self, artefactos_limpios):
        assert ModeloPrediccion.cargar_activo(artefactos_limpios) is None


class TestWalkForward:
    def test_metricas_en_rangos_validos(self, dataset):
        X, y, _ = dataset
        resultado = validacion_walk_forward(X, y, minimo_entrenamiento=100)
        assert 0.0 <= resultado.accuracy <= 1.0
        assert resultado.log_loss > 0
        assert 0.0 <= resultado.brier <= 2.0
        assert len(resultado.pliegues) >= 2

    def test_cada_pliegue_entrena_solo_con_el_pasado(self, dataset):
        """El tamano de entrenamiento crece y nunca se solapa con la evaluacion."""
        X, y, _ = dataset
        resultado = validacion_walk_forward(X, y, minimo_entrenamiento=100)
        tamanos = [p.n_entrenamiento for p in resultado.pliegues]
        assert tamanos == sorted(tamanos)
        assert len(set(tamanos)) == len(tamanos)
        for pliegue in resultado.pliegues:
            assert pliegue.n_entrenamiento + pliegue.n_evaluacion <= len(X)

    def test_evaluaciones_cubren_el_conjunto_sin_repetir(self, dataset):
        X, y, _ = dataset
        resultado = validacion_walk_forward(X, y, minimo_entrenamiento=100)
        evaluados = sum(p.n_evaluacion for p in resultado.pliegues)
        assert evaluados == resultado.n_total_evaluado == len(X) - 100

    def test_falla_con_pocos_datos_en_vez_de_dar_un_numero_falso(self):
        X = np.random.default_rng(0).normal(size=(30, len(NOMBRES_FEATURES)))
        y = np.array(["L"] * 15 + ["V"] * 15, dtype=object)
        with pytest.raises(ValueError, match="al menos"):
            validacion_walk_forward(X, y)

    def test_el_modelo_supera_al_azar(self, dataset):
        """Sobre datos con senal, el modelo tiene que ganarle al 1/3."""
        X, y, _ = dataset
        resultado = validacion_walk_forward(X, y, minimo_entrenamiento=100)
        assert resultado.accuracy > 1 / 3

    def test_datos_sin_senal_no_producen_accuracy_alta(self):
        """Control negativo: con ruido puro, el walk-forward no debe inventar aciertos.

        Si este test empieza a fallar, es senal de fuga de informacion en el
        pipeline (el modelo estaria "adivinando" demasiado bien).
        """
        rng = np.random.default_rng(SEMILLA)
        X = rng.normal(size=(400, len(NOMBRES_FEATURES)))
        y = np.array(rng.choice(["L", "E", "V"], size=400), dtype=object)
        resultado = validacion_walk_forward(X, y, minimo_entrenamiento=150)
        assert resultado.accuracy < 0.55

    def test_linea_base(self, dataset):
        _, y, _ = dataset
        base = linea_base_siempre_local(y)
        assert 0.0 < base < 1.0
        assert base == pytest.approx(float(np.mean(y == "L")))


class TestMetricas:
    def test_log_loss_castiga_la_confianza_equivocada(self):
        y = np.array(["L"], dtype=object)
        acertada = np.array([[0.9, 0.05, 0.05]])
        equivocada = np.array([[0.05, 0.05, 0.9]])
        assert log_loss_multiclase(y, acertada) < log_loss_multiclase(y, equivocada)

    def test_log_loss_no_explota_con_probabilidad_cero(self):
        y = np.array(["L"], dtype=object)
        assert np.isfinite(log_loss_multiclase(y, np.array([[0.0, 0.5, 0.5]])))

    def test_brier_perfecto_es_cero(self):
        y = np.array(["E"], dtype=object)
        assert brier_multiclase(y, np.array([[0.0, 1.0, 0.0]])) == pytest.approx(0.0)

    def test_brier_peor_caso_es_dos(self):
        y = np.array(["L"], dtype=object)
        assert brier_multiclase(y, np.array([[0.0, 0.0, 1.0]])) == pytest.approx(2.0)


class TestPoisson:
    def test_pmf_es_una_distribucion(self):
        total = sum(pmf_bivariada(x, y, 1.3, 1.0, 0.1) for x in range(25) for y in range(25))
        assert total == pytest.approx(1.0, abs=1e-6)

    def test_sin_termino_comun_colapsa_a_poisson_independiente(self):
        import math

        l1, l2 = 1.5, 1.2
        esperado = (math.exp(-l1) * l1**2 / 2) * (math.exp(-l2) * l2**1 / 1)
        assert pmf_bivariada(2, 1, l1, l2, 0.0) == pytest.approx(esperado)

    def test_marcador_negativo_tiene_probabilidad_cero(self):
        assert pmf_bivariada(-1, 2, 1.0, 1.0, 0.0) == 0.0

    def test_ajuste_y_prediccion(self):
        modelo = ModeloPoissonBivariado()
        modelo.ajustar(historico_sintetico())
        assert modelo.ajustado

        local, empate, visitante = modelo.probabilidades_1x2(10, 1)
        assert local + empate + visitante == pytest.approx(1.0, abs=1e-6)
        # El equipo 10 es el mas fuerte y juega de local contra el mas debil.
        assert local > visitante

    def test_marcador_mas_probable_es_coherente(self):
        modelo = ModeloPoissonBivariado()
        modelo.ajustar(historico_sintetico())
        gl, gv, prob = modelo.marcador_mas_probable(10, 1)
        assert gl >= 0 and gv >= 0
        assert 0 < prob < 1
        assert gl >= gv  # el favorito no deberia tener el marcador perdedor como modal

    def test_sin_datos_no_queda_ajustado(self):
        modelo = ModeloPoissonBivariado()
        modelo.ajustar([])
        assert not modelo.ajustado

    def test_equipo_desconocido_usa_fuerza_neutra(self):
        modelo = ModeloPoissonBivariado()
        modelo.ajustar(historico_sintetico())
        probs = modelo.probabilidades_1x2(9999, 8888)
        assert sum(probs) == pytest.approx(1.0, abs=1e-6)


class TestPipelineCompletoEnBase:
    """Recorrido completo contra la base: entrenar -> predecir -> transparencia."""

    def _sembrar(self, db, equipos, jornadas: int = 55) -> None:
        rng = random.Random(SEMILLA)
        fuerza = {e.id: 0.7 + 0.2 * i for i, e in enumerate(equipos)}
        externo = 0
        for jornada in range(jornadas):
            ids = [e.id for e in equipos]
            rng.shuffle(ids)
            mapa = {e.id: e for e in equipos}
            for local, visitante in zip(ids[::2], ids[1::2], strict=False):
                externo += 1
                crear_partido(
                    db,
                    mapa[local],
                    mapa[visitante],
                    BASE + timedelta(days=7 * jornada),
                    goles_local=_poisson(rng, 1.4 * fuerza[local] / fuerza[visitante]),
                    goles_visitante=_poisson(rng, 1.0 * fuerza[visitante] / fuerza[local]),
                    jornada=jornada + 1,
                    externo=f"seed-{externo}",
                )

    def test_entrenar_predecir_y_publicar_metricas(self, db, equipos, partido_futuro):
        self._sembrar(db, equipos)

        resumen = entrenar_modelo(db, registrar_job=False)
        assert resumen.partidos_entrenamiento >= 200
        assert 0.0 <= resumen.accuracy <= 1.0
        assert resumen.version.startswith("v")

        # El artefacto quedo activo y se puede recargar.
        modelo, version = modelo_activo(db)
        assert version == resumen.version
        assert modelo.entrenado

        # Predicciones para el partido futuro.
        assert generar_predicciones(db) == 1
        from app.modelos.prediccion import Prediccion

        prediccion = db.query(Prediccion).filter(Prediccion.partido_id == partido_futuro.id).one()
        total = prediccion.prob_local + prediccion.prob_empate + prediccion.prob_visitante
        assert total == pytest.approx(1.0)
        assert prediccion.resultado_predicho in CLASES
        assert prediccion.confianza == max(
            prediccion.prob_local, prediccion.prob_empate, prediccion.prob_visitante
        )

        # Backtest walk-forward: llena el historial de aciertos.
        creadas = backfill_historico(db, minimo_entrenamiento=150)
        assert creadas > 0
        assert recalcular_metricas_por_jornada(db) > 0

        global_ = resumen_global(db)
        assert global_.partidos_evaluados == creadas
        assert global_.aciertos <= global_.partidos_evaluados
        assert global_.accuracy == pytest.approx(global_.aciertos / global_.partidos_evaluados)

    def test_el_backtest_no_predice_dos_veces_el_mismo_partido(self, db, equipos):
        self._sembrar(db, equipos)
        primera = backfill_historico(db, minimo_entrenamiento=150)
        segunda = backfill_historico(db, minimo_entrenamiento=150)
        assert primera > 0
        assert segunda == 0  # idempotente

    def test_generar_predicciones_sin_modelo_falla_explicito(self, db, equipos, partido_futuro):
        from app.servicios.predicciones import ModeloNoDisponible

        with pytest.raises(ModeloNoDisponible):
            generar_predicciones(db)

    def test_entrenar_con_pocos_partidos_falla_explicito(self, db, equipos):
        from app.servicios.entrenamiento import DatosInsuficientes

        self._sembrar(db, equipos, jornadas=3)
        with pytest.raises(DatosInsuficientes):
            entrenar_modelo(db, registrar_job=False)

    def test_transparencia_expone_el_historial(self, db, equipos, cliente):
        self._sembrar(db, equipos)
        backfill_historico(db, minimo_entrenamiento=150)
        recalcular_metricas_por_jornada(db)

        resumen = cliente.get("/transparencia/resumen").json()
        assert resumen["partidos_evaluados"] > 0
        assert 0.0 <= resumen["accuracy_real"] <= 1.0
        assert "no son garantias" in resumen["aviso"] or "no garantias" in resumen["aviso"]

        jornadas = cliente.get("/transparencia/jornadas").json()
        assert len(jornadas) > 0
        for jornada in jornadas:
            assert jornada["aciertos"] <= jornada["partidos_evaluados"]
            assert jornada["accuracy"] == pytest.approx(
                jornada["aciertos"] / jornada["partidos_evaluados"]
            )
