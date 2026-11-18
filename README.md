# Brazil IBGE Geodemographics, Municipal GDP, CNAE & GeoJSON (`apify-brazil-ibge-geodemographics`)

Extract authoritative territorial, demographic, economic, and geographic data directly from the official **IBGE (Instituto Brasileiro de Geografia e Estatística)** REST & SIDRA APIs (`servicodados.ibge.gov.br`), with zero residential proxies and zero external API keys.

## Dataset Modes

- **`municipalities`:** Complete municipal catalog filtered by state (`uf`) or keyword (`query`) with 7-digit IBGE codes, microregions, mesoregions, and immediate regions.
- **`population`:** Estimated resident population (`Agregado 6579 / Variável 9324`) by 7-digit municipality codes (`ibgeIds`) or across an entire state's municipalities (`uf`).
- **`municipal_gdp`:** Municipal GDP at current prices in thousand BRL (`Agregado 5938 / Variável 37`) by `ibgeIds` or across an entire state (`uf`).
- **`cnae_classes`:** Full CNAE 2.3 industry taxonomy lookup by `cnaeCode` or keyword filter (`query`), returning Class, Group, Division, and Section descriptions.
- **`geojson_mesh`:** Official IBGE territorial polygon boundary as standard GeoJSON (`FeatureCollection`) at `minima`, `intermediaria`, or `maxima` geometry detail for any state (`uf`) or municipality (`ibgeIds`).

## Example Input

```json
{
  "mode": "municipal_gdp",
  "uf": "AL",
  "query": "Maceió",
  "maxResults": 20
}
```

## MCP & Standby Ready

Runs as a batch Apify Actor, HTTP Standby server (`GET /`, `GET /health`, `POST /`), or **MCP Server** (`POST /mcp`, tool `query_brazil_ibge`).
