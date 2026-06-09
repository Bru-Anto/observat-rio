# Observatory Control System

Sistema conteinerizado para controle e monitoramento de um observatório, com simulador ASCOM Alpaca, sequenciador operacional, coleta de telemetria via Telegraf/MQTT, persistência de estado em Redis, séries temporais em InfluxDB, painéis Grafana e interface Host Manager em Streamlit.

## Componentes

- `alpaca_sim`: simulador de câmera, domo e estação meteorológica compatível com rotas Alpaca.
- `sequencer`: API FastAPI que aplica regras de segurança, recebe telemetria MQTT e envia comandos ao Alpaca.
- `telegraf`: coleta endpoints HTTP Alpaca e publica métricas em MQTT/InfluxDB.
- `mosquitto`: broker MQTT.
- `redis`: armazenamento do estado operacional atual.
- `influxdb`: armazenamento histórico das métricas.
- `grafana`: visualização e alertas.
- `host_manager`: painel Streamlit para status e comandos operacionais.
- `nginx`: proxy autenticado para a interface, Grafana, InfluxDB e API.

## Como Executar

1. Copie o arquivo de ambiente:

```powershell
Copy-Item infrastructure\.env.example infrastructure\.env
```

2. Edite `infrastructure\.env` e preencha senhas e tokens reais.

3. Crie o arquivo `infrastructure\nginx\.htpasswd` com o usuário de acesso HTTP Basic.

4. Suba os serviços:

```powershell
cd infrastructure
docker compose up --build -d
```

5. Acesse:

- Host Manager: `http://localhost:8080/`
- Sequencer API: `http://localhost:8080/api/docs`
- Grafana: `http://localhost:8080/grafana/`
- InfluxDB: `http://localhost:8080/influx/`

## Telemetria

O sequenciador aceita mensagens MQTT em JSON no formato usado pelo projeto, por exemplo:

```json
{
  "name": "wind",
  "fields": {
    "Value": 12.5
  },
  "tags": {},
  "timestamp": 1710000000
}
```

Também são aceitos modelos com múltiplos campos, desde que os nomes dos campos ou medições tenham aliases reconhecíveis, como `windSpeed`, `rainRate`, `dome_azimuth`, `coolerOn` ou equivalentes. Telemetrias desconhecidas não são descartadas: elas ficam registradas em `/telemetry` como telemetria genérica.

O fallback Alpaca é controlado pela atualização das telemetrias meteorológicas reconhecidas. Assim, uma telemetria genérica desconhecida não impede o sequenciador de buscar vento e chuva diretamente no Alpaca quando necessário.

O broker MQTT aceita conexões anônimas dentro da rede Docker do projeto. Para um ambiente exposto fora da máquina local, revise essa configuração antes de publicar ou operar em rede aberta.

## Host Manager

O Host Manager possui páginas para operação principal, agentes, alertas e configurações. Os comandos globais executam ações reais nos containers monitorados:

- `Start`: inicia serviços operacionais parados.
- `Stop`: para os serviços operacionais sem derrubar o próprio Host Manager/Nginx.
- `Reload Config`: reinicia serviços que leem configuração em runtime, como `sequencer`, `telegraf`, `mqtt_logger` e `promtail`.

## Testes

```powershell
python -m unittest discover infrastructure/sequencer -p test_*.py
python -m py_compile infrastructure\sequencer\main.py infrastructure\sequencer\telemetry.py
```

## GitHub

Este repositório ignora arquivos sensíveis como `.env` e `.htpasswd`. Antes de publicar, confira:

```powershell
git status --short
git add .
git commit -m "Initial observatory control system"
```

Depois crie um repositório vazio no GitHub e conecte o remoto:

```powershell
git remote add origin https://github.com/SEU_USUARIO/NOME_DO_REPOSITORIO.git
git branch -M main
git push -u origin main
```
