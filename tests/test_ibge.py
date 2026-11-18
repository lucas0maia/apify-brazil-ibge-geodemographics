"""Unit tests for Brazil IBGE Geodemographics, GDP, CNAE & GeoJSON Actor."""

import unittest

from src.main import (
    fetch_cnae_classes,
    fetch_geojson_mesh,
    fetch_municipal_gdp,
    fetch_municipalities,
    fetch_population,
    run_query,
)


class TestIbgeActor(unittest.TestCase):
    def test_municipalities_filter(self) -> None:
        sample = [
            {
                "id": 2704302,
                "nome": "Maceió",
                "microrregiao": {
                    "nome": "Maceió",
                    "mesorregiao": {
                        "nome": "Leste Alagoano",
                        "UF": {"sigla": "AL", "nome": "Alagoas", "regiao": {"nome": "Nordeste"}},
                    },
                },
                "regiao-imediata": {"nome": "Maceió"},
            },
            {
                "id": 2700300,
                "nome": "Arapiraca",
                "microrregiao": {
                    "nome": "Arapiraca",
                    "mesorregiao": {
                        "nome": "Agreste Alagoano",
                        "UF": {"sigla": "AL", "nome": "Alagoas", "regiao": {"nome": "Nordeste"}},
                    },
                },
                "regiao-imediata": {"nome": "Arapiraca"},
            },
        ]
        rows = fetch_municipalities(uf="AL", query="maceió", fetcher=lambda _u, _t: sample)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ibgeId"], "2704302")
        self.assertEqual(rows[0]["uf"], "AL")

    def test_population_sidra_parsing(self) -> None:
        sample = [
            {
                "id": "9324",
                "variavel": "População residente estimada",
                "unidade": "Pessoas",
                "resultados": [
                    {
                        "series": [
                            {"localidade": {"id": "2704302", "nome": "Maceió - AL"}, "serie": {"2026": "995134"}}
                        ]
                    }
                ],
            }
        ]
        rows = fetch_population(ibge_ids=["2704302"], fetcher=lambda _u, _t: sample)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["numericValue"], 995134.0)
        self.assertEqual(rows[0]["uf"], "AL")
        self.assertEqual(rows[0]["period"], "2026")

    def test_municipal_gdp_parsing_via_uf(self) -> None:
        sample = [
            {
                "id": "37",
                "variavel": "Produto Interno Bruto a preços correntes",
                "unidade": "Mil Reais",
                "resultados": [
                    {
                        "series": [
                            {"localidade": {"id": "2704302", "nome": "Maceió - AL"}, "serie": {"2023": "32100450"}}
                        ]
                    }
                ],
            }
        ]
        rows = fetch_municipal_gdp(
            uf="AL",
            fetcher=lambda url, _t: (self.assertIn("N6[N3[27]]", url), sample)[-1],
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["numericValue"], 32100450.0)
        self.assertEqual(rows[0]["unit"], "Mil Reais")

    def test_cnae_and_geojson_router(self) -> None:
        cnae_sample = {
            "id": "62015",
            "descricao": "DESENVOLVIMENTO DE PROGRAMAS DE COMPUTADOR SOB ENCOMENDA",
            "grupo": {
                "descricao": "TI",
                "divisao": {"descricao": "SERVICOS DE TI", "secao": {"id": "J", "descricao": "INFORMACAO"}},
            },
        }
        cnae_rows = run_query({"mode": "cnae_classes", "cnaeCode": "6201-5"}, fetcher=lambda _u, _t: cnae_sample)
        self.assertEqual(len(cnae_rows), 1)
        self.assertEqual(cnae_rows[0]["ibgeId"], "62015")

        geo_sample = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "Polygon"}}]}
        geo_rows = fetch_geojson_mesh(uf="AL", fetcher=lambda _u, _t: geo_sample)
        self.assertEqual(len(geo_rows), 1)
        self.assertEqual(geo_rows[0]["numericValue"], 1)
        self.assertEqual(geo_rows[0]["geojson"]["type"], "FeatureCollection")


if __name__ == "__main__":
    unittest.main()
