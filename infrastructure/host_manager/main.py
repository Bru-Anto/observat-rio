'''
Esse é Host Manager, ele é a parte visível para o usuário, onde pode ser ver os dados e onde pode-se controlar e realizar ações no sistema 
'''
''' Bibliotecas '''

import streamlit as st # Montar a interface
import docker # Biblioteca de uso do docker no python
import time # Usado para pausas e para recarregar a página
import requests # Usado para pedidos HTTP para o grafana e sequenciador 
import os # Variáveis de ambiente
from datetime import datetime # Formatar os dados dos alertas

''' Configurações do sistema '''

SEQUENCER_URL = os.getenv("SEQUENCER_URL", "http://sequencer:8000") # URL interna do sequenciador 
GRAFANA_URL = os.getenv("GRAFANA_URL", "http://grafana:3000") # URL interna do grafana 
GRAFANA_TOKEN = os.getenv("GRAFANA_TOKEN", "") # Pega o token do grafana para usar para alertas 
TIMEOUT = 5 # Tempo de espera de 5 segundos 
TIMEOUT_GRAFANA = 3 # Tempo de espera somente do grafana de 3 segundos 

ALLOWED = [ # Lista de containers que são reconhecidos e exibidos pelo sistema 
    "sequencer", "alpaca_sim", "mosquitto", "redis",
    "influxdb", "telegraf", "grafana", "loki",
    "promtail", "host_manager", "nginx", "node_exporter", "mqtt_logger"
]

OPERATIONAL_SERVICES = [
    "alpaca_sim", "mosquitto", "redis", "influxdb", "sequencer",
    "telegraf", "grafana", "loki", "promtail", "node_exporter", "mqtt_logger"
]
CONFIG_RELOAD_SERVICES = ["sequencer", "telegraf", "mqtt_logger", "promtail"] # Lista de serviços que serão reiniciados pelo botão reload

''' Configurações da Interface do sistema '''

st.set_page_config(page_title="Sistema de Controle - Observatório do Pico dos Dias", layout="wide") # Título da página 
# Estilo da página 
st.markdown("""
<style>
:root{
  --bg:#0b1220;
  --panel:#0f172a;
  --panel2:#0b1326;
  --border:#1e293b;
  --text:#e5e7eb;
  --muted:#9ca3af;
  --ok:#22c55e;
  --warn:#f59e0b;
  --crit:#ef4444;
  --chip:#111827;
}

.block-container { padding-top: 1.0rem; }
section[data-testid="stSidebar"] { background: var(--panel2); border-right: 1px solid var(--border); }
h1,h2,h3,h4 { color: var(--text) !important; }
small, .muted { color: var(--muted); }

.card{
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px 14px 10px 14px;
}

.card-title{
  display:flex; align-items:center; justify-content:space-between;
  font-weight:700; margin-bottom:10px;
}

.hr{ height:1px; background:var(--border); margin: 10px 0 12px 0; }

.chip{
  display:inline-flex; align-items:center; gap:8px;
  padding: 4px 10px; border-radius: 999px;
  background: var(--chip); border:1px solid var(--border);
  font-size: 12px;
}

.dot{ width:9px; height:9px; border-radius:99px; display:inline-block; }
.dot-ok{ background: var(--ok); }
.dot-warn{ background: var(--warn); }
.dot-crit{ background: var(--crit); }
.dot-muted{ background: #64748b; }

.kpi{
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
}

.small { font-size: 0.85rem; color: var(--muted); }
table { width: 100% !important; }

</style>
""", unsafe_allow_html=True) # Permite HTML e CSS no Streamlit

def chip(label: str, level: str = "muted") -> str: # Cria um chip visual 
    cls = {"ok":"dot-ok","warn":"dot-warn","crit":"dot-crit","muted":"dot-muted"}[level] # Escolha e classe CSS conforme o nível
    return f'<span class="chip"><span class="dot {cls}"></span>{label}</span>' # Retorna em HTML

def docker_list(): # Função para conectar ao docker 
    client = docker.from_env() # Cria um cliente docker usando o ambiente local
    return client, client.containers.list(all=True) # Retorna o cliente e lista os containers

def sequencer_get(path: str, timeout: float = 3.0): # Função auxiliar para o GET do sequencer 
    return requests.get(f"{SEQUENCER_URL}{path}", timeout=timeout) # Faz pedidos usando o URL do sequenciador 

def sequencer_post(path: str, timeout: float = 5.0): # Função auxiliar para o POST do sequencer
    return requests.post(f"{SEQUENCER_URL}{path}", timeout=timeout) # Faz entregas usando o URL do sequenciador

def grafana_alerts(): # Função que busca alertas ativos no Grafana
    if not GRAFANA_TOKEN: # Verifica se existe token
        return None, "GRAFANA_TOKEN não configurado no host_manager" # Se não existir o token, retorna esse erro
    headers = {"Authorization": f"Bearer {GRAFANA_TOKEN}", "Accept": "application/json"} # Monta cabeçalho
    url = f"{GRAFANA_URL}/api/alertmanager/grafana/api/v2/alerts" # Endpoint dos alertas
    params = {"active": "true", "silenced": "false", "inhibited": "false"} # Filtra alertas ativos
    r = requests.get(url, headers=headers, params=params, timeout=TIMEOUT_GRAFANA) # Requisição HTTP
    r.raise_for_status() # Erro caso a resposta não seja 2xx
    return r.json(), None # Retorna o JSON dos alertas

def fmt_ts(ts: str) -> str: # Função que formata os timestamps
    if not ts: 
        return "" # Se não tiver data vai retornar vazio 
    try:
        dt = datetime.fromisoformat(ts.replace("Z","+00:00")) # Converte de ISO para datetime
        return dt.strftime("%Y-%m-%d %H:%M:%S") # Formata como YYYY-MM-DD HH:MM:SS
    except Exception:
        return ts # Se der erro em transformar ele retorna o texto original 

def containers_by_name(): # Cria um mapa de containers
    return {c.name: c for c in containers if c.name in ALLOWED} # Inclui nele somente os containers permitidos

def apply_container_action(names, action: str): # Função para aplicar star, stop e restart 
    available = containers_by_name() # Buscar conatiners disponíveis 
    changed = [] # Cria uma lista de mudanças
    errors = [] # Cria uma lista de erros

    for name in names:
        container = available.get(name) # Percorre os containers que estão disponívies
        if container is None: # Se não estiver disponível ignora e continua
            continue

        try: # Executa start, stop e restart baseado no status do container
            if action == "start" and container.status != "running":
                container.start()
                changed.append(name)
            elif action == "stop" and container.status == "running":
                container.stop()
                changed.append(name)
            elif action == "restart" and container.status == "running":
                container.restart()
                changed.append(name)
        except Exception as e: 
            errors.append(f"{name}: {e}") # Se tiver algum erro, registra ele e mostra em qual container é 

    return changed, errors # Retorna o que mudou e se possui algum erro

def show_action_result(changed, errors, success_message: str): # Função para mostrar resultados 
    if changed:
        st.success(f"{success_message}: {', '.join(changed)}") # Mostra se obteve sucesso em alguma mudança
    elif not errors:
        st.info("Nenhuma mudança necessária.") # Mostra se nada precisa mudar 

    if errors:
        st.error("Falhas: " + " | ".join(errors)) # Mostra as falhas 
    else:
        time.sleep(1) # Espera 1 segundo
        st.rerun() # Recarrega a página

''' Conexões com o Docker'''

docker_ok = False # Começa assumindo que o Docker não está conectado
docker_client = None # Começa vazio a lista dos clientes
containers = [] # Começa a lista de container
docker_err = None # Começa a vazia a lista de erros

try: # Tenta conectar com o Docker 
    docker_client, containers = docker_list() # Define ps clientes e começa a lista de containers
    docker_ok = True # Se a conexão funcionou, marca como ok
except Exception as e: 
    docker_err = str(e) # Se der erro, salva uma mensagem de erro
# O Host manager depende do socket do docker para poder realizar as ações

''' Barra lateral'''

st.sidebar.markdown("### Sistema de Controle") # Títula da barra lateral
page = st.sidebar.selectbox("Main", ["Main", "Agents", "Alerts", "Configs"], index=0) # Cria um seletor de página com 4 opções -> main, agents, alerts, configs

st.sidebar.markdown("#### Agentes") # Subtítulo agentes na barra lateral
if docker_ok: # Se está tudo certo com a conexão com o Docker, retorna a lista de containers
    for c in sorted([x for x in containers if x.name in ALLOWED], key=lambda x: x.name): # Filtra somente os containers permitidos 
        level = "ok" if c.status == "running" else "crit" # Se está rodando aparece running, se não está aparece o crit
        st.sidebar.markdown(f"- {c.name}  {chip(c.status.upper(), level)}", unsafe_allow_html=True) # Nome do container e o status 
else: # Se o docker não estiver conectado
    st.sidebar.markdown(chip("Docker offline", "crit"), unsafe_allow_html=True) # Mostra Docker offline
    st.sidebar.caption(docker_err or "") # Mostra o erro que está acontecendo

st.sidebar.markdown("---") # Divisória 
st.sidebar.caption("Dica: use /grafana/ para dashboards e alerting.") # Dica sobre o caminho para o grafana para ver melhor o erro

def render_agents_page(): # Função que renderiza a página de agentes
    st.markdown("# Agentes") # Título da página
    if not docker_ok: # Se no docker não está conectando 
        st.error(f"Erro ao conectar ao Docker: {docker_err}") # Motra erro 
        return

    for c in [x for x in containers if x.name in ALLOWED]: # Percorre os containers permitidos
        status_icon = "🟢" if c.status == "running" else "🔴" # Ícones para o status atual 
        status_level = "ok" if c.status == "running" else "crit" # Nível 

        st.markdown('<div class="card">', unsafe_allow_html=True) # Card em HTML
        st.markdown( # Título, nome do container e chip de status 
            f'<div class="card-title">{status_icon} {c.name}<span>{chip(c.status.upper(), status_level)}</span></div>',
            unsafe_allow_html=True 
        )
        st.markdown(f'<div class="small">Imagem: {c.image.tags[0] if c.image.tags else "N/A"}</div>', unsafe_allow_html=True) # Mostra a imagem que é usada pelo container

        b1, b2, b3 = st.columns(3) # 3 colunas para botões
        with b1: # Primeira coluna
            if st.button("🔄 Restart", key=f"page_restart_{c.name}", use_container_width=True): # Botão de restart
                c.restart() # Reinicia o container
                time.sleep(1) # Espera 1 segundo
                st.rerun() # Recarrega a interface
        with b2: # Segunda coluna
            if st.button("⏹ Stop", key=f"page_stop_{c.name}", use_container_width=True, disabled=(c.status != "running")): # Botão de stop, é desabilitado caso o container não esteja rodando
                c.stop() # Para o container
                time.sleep(1) # Espera 1 segundo
                st.rerun() # Recarrega a interface
        with b3: # Terceira coluna 
            if st.button("▶ Start", key=f"page_start_{c.name}", use_container_width=True, disabled=(c.status == "running")): # Botão de start, é desabilitado caso o container já esteja rodando
                c.start() # Inicia o container
                time.sleep(1) # Espera 1 segundo
                st.rerun() # Recarrega a interface

        st.markdown('</div>', unsafe_allow_html=True) # Fecha o card

def render_alerts_page(): # Página de alertas 
    st.markdown("# Alertas") # Título da página
    alerts = None # Começa as variáveis como vazias
    err = None
    try: # Tenta buscae alertas no grafana 
        alerts, err = grafana_alerts() # Chama a função de alertas 
    except Exception as e:
        err = str(e) # Se der erro, salva a mensagem de erro

    if err: # Caso tenha ocorrido algum erro
        st.markdown(chip("Grafana alerts unavailable", "warn"), unsafe_allow_html=True) # Chip de alerta como indisponível
        st.markdown(f'<div class="small">{err}</div>', unsafe_allow_html=True) # Detalhes do erro
        return

    if not alerts: # Caso não tenha alertas
        st.markdown(chip("No active alerts", "ok"), unsafe_allow_html=True) # Mostra que não existem alertas
        return

    st.markdown(f'<div class="small">Ativos: <b>{len(alerts)}</b></div>', unsafe_allow_html=True) # Quantidade de alertas ativos
    st.markdown("")
    for a in alerts: # Percorre os alertas 
        labels = a.get("labels", {}) or {} # Label do alerta
        annotations = a.get("annotations", {}) or {} # Anotações do alerta
        status = a.get("status", {}) or {} # Status do alerta
        name = labels.get("alertname", "Sem nome") # Nome do alerta
        severity = (labels.get("severity", "warning") or "warning").lower() # Severidade do alerta 
        lvl = "crit" if severity in ("critical", "high", "p1") else "warn" # Se for grave usa o nível crítico, se não for usa apenas aviso
        state = status.get("state", "unknown") # Estado do alerta
        starts_at = fmt_ts(a.get("startsAt", "")) # Data de início
        summary = annotations.get("summary") or annotations.get("description") or "" # Resumo do alerta

        st.markdown(f"**{name}**  {chip(severity.upper(), lvl)}", unsafe_allow_html=True) # Nome do alerta e chip de severidade
        st.markdown(f'<div class="small">state: <b>{state}</b> • since: {starts_at}</div>', unsafe_allow_html=True) # Mostra o estado e desde quando está ativo
        if summary: # Caso o alerta tenha resumo
            st.markdown(f'<div class="small">{summary}</div>', unsafe_allow_html=True) # Mostra o resumo
        st.markdown('<div class="hr"></div>', unsafe_allow_html=True) # Separação entre os alertas

def render_configs_page(): # Página de configurações
    # Sequenciador 
    st.markdown("# Configurações") # Título da página 
    st.markdown("### Sequencer") # Subtítulo -> Sequenciador 
    try: # Tenta consultar o sequenciador 
        r = sequencer_get("/health") # Chama a função que verifica a saúde
        r.raise_for_status() # Valida o status HTTP
        st.json(r.json()) # Mostra a JSON do estado do sequenciador
    except Exception as e: # Se não funcionar define como erro
        st.error(f"Sequencer offline: {e}") # Mostra o erro
    # Telemetria
    st.markdown("### Telemetria Recebida") # Subtítulo de telemetria
    try: # Tenta se conectar com a telemetria
        r = sequencer_get("/telemetry") # Consulta a função de telemetria 
        r.raise_for_status() # Valida o status com o HTTP
        st.json(r.json()) # Mostra o JSON
    except Exception as e: # Se não funcionar define como erro
        st.warning(f"Telemetria indisponível: {e}") # Mostra o erro

# Página internas 
if page == "Agents":
    render_agents_page() # Se o usuário escolheu agentes, abre a página de agentes 
    st.stop()
if page == "Alerts":
    render_alerts_page() # Se o usuário escolheu alertas, abre a página de alertas
    st.stop()
if page == "Configs":
    render_configs_page() # Se o usuário escolheu configurações, abre a página de configurações
    st.stop()

''' Página principal'''
# Topo da Página principal
st.markdown("# Host Manager") # Título principal

if docker_ok: # Se a conexão com o docker está funcionando
    running = len([c for c in containers if c.status == "running" and c.name in ALLOWED]) # Conta os container que são permitidos o acesso que estão rodando 
    total = len([c for c in containers if c.name in ALLOWED]) # Conta os containers que são permitidos
    stopped = total - running # Calcula os containers que estão parados 
else: # Se não tiver acesso ao docker
    running, stopped, total = 0, 0, 0 # Zera os contadores

k1, k2, k3, k4 = st.columns([1,1,1,1.3], gap="large") # Cria 4 colunas, sendo a última um pouco mais larga
with k1:
    st.markdown(f'<div class="kpi"><div class="small">Containers Ativos</div><div style="font-size:28px;font-weight:800;">{running}</div></div>', unsafe_allow_html=True) # Primeira coluna: mostra o número de containers ativos 
with k2:
    st.markdown(f'<div class="kpi"><div class="small">Parados</div><div style="font-size:28px;font-weight:800;">{stopped}</div></div>', unsafe_allow_html=True) # Segunda coluna: mostra o número de containers parados
with k3:
    st.markdown(f'<div class="kpi"><div class="small">Total</div><div style="font-size:28px;font-weight:800;">{total}</div></div>', unsafe_allow_html=True) # Terceira coluna: mostra o número total de containers
with k4:
    st.markdown(f'<div class="kpi"><div class="small">Acesso</div><div class="small">Grafana em <b>/grafana/</b> • Sequencer em <b>/api/docs</b></div></div>', unsafe_allow_html=True) # Quarta coluna: Atalhos para o grafna e API

st.markdown("")

# Layout pricipal
colA, colB, colC = st.columns([2.2, 1.2, 1.6], gap="large") # Cria 3 colunas principais 

with colA: # Conexão com o host manager 
    st.markdown('<div class="card">', unsafe_allow_html=True) # Abre um card
    st.markdown('<div class="card-title">Host Manager Connection</div>', unsafe_allow_html=True) # Título do card 

    st.text_input("Address", value="observatory_net / host_manager", disabled=True) # Campo desabilitado com o endereço do host manager
    st.markdown(chip("OK" if docker_ok else "Docker error", "ok" if docker_ok else "crit"), unsafe_allow_html=True) # Chip verde se está tudo bem e vermelho se deu erro

    if st.button("Refresh", use_container_width=True): # Botão de atualização
        st.rerun() # Se clicar no botão vai recarregar a página 
    st.markdown('</div>', unsafe_allow_html=True) # Fecha o card 

with colB: # Ações globais
    st.markdown('<div class="card">', unsafe_allow_html=True) # Abre um card
    st.markdown('<div class="card-title">manager</div>', unsafe_allow_html=True) # Título de manager 

    confirm = st.checkbox("Confirm actions", value=False) # Botão que confirma realizar ações no sistema

    b1, b2 = st.columns(2) # Duas colunas -> start, stop
    with b1:
        if st.button("Start", use_container_width=True, disabled=(not confirm or not docker_ok)): # Botão de start , fica desabilitado caso não tenha confirmado a conexão com o docker 
            changed, errors = apply_container_action(OPERATIONAL_SERVICES, "start") # Tenta iniciar todos os serviços que estão no OPERATIONAL_SERVICES
            show_action_result(changed, errors, "Serviços iniciados") # Mostra o resultado da ação
    with b2:
        if st.button("Stop", use_container_width=True, disabled=(not confirm or not docker_ok)): # Botão de stop
            changed, errors = apply_container_action(list(reversed(OPERATIONAL_SERVICES)), "stop") # Para os serviços operacionais na ordem inversa que foram iniciados 
            show_action_result(changed, errors, "Serviços parados") # Mostra o resultado da ação

    st.markdown('<div class="hr"></div>', unsafe_allow_html=True) # Divisão

    if st.button("Reload Config", use_container_width=True, disabled=(not confirm or not docker_ok)): # Botão para recarregar as configurações
        changed, errors = apply_container_action(CONFIG_RELOAD_SERVICES, "restart") # Reinicia os serviços do CONFIG_RELOAD_SERVICES
        show_action_result(changed, errors, "Serviços reiniciados") # Mostra o resultado da ação

    st.markdown('</div>', unsafe_allow_html=True) # Fecha o card

with colC: # Estado do observatório
    st.markdown('<div class="card">', unsafe_allow_html=True) # Abre o card 
    st.markdown('<div class="card-title">Observatory Status</div>', unsafe_allow_html=True) # Define o nome 

    state = {} # Começa o estado como vazio
    state_ok = False # Marca o estado inicial como inválido 
    try: # Tenta conexão com o sequenciador 
        r = sequencer_get("/health") # Verfifica a saúde 
        r.raise_for_status() # Verifica o status 
        state = r.json() # Lê o JSON do estado
        state_ok = True # Define que o estado está ok
    except Exception as e: # Caso ocorra falha 
        st.markdown(chip("Sequencer offline", "crit"), unsafe_allow_html=True) # Mostra que o sequenciador não está respondendo
        st.markdown(f'<div class="small">{e}</div>', unsafe_allow_html=True) # Mostra os detalhes do erro 

    if state_ok: # Se está tudo certo
        lock = bool(state.get("weather_lock")) # Lê o bloqueador de tempo
        st.markdown(chip("WEATHER LOCK" if lock else "WEATHER OK", "crit" if lock else "ok"), unsafe_allow_html=True)  # Chip vermelho se o clima está ruim e verde se está tudo certo

        a,b,c,d = st.columns(4) # Cria 4 colunas 
        a.metric("Vento", f"{state.get('wind_speed', 0)}") # Vento 
        b.metric("Chuva", f"{state.get('rain_rate', 0)}") # Taxa de chuva
        c.metric("Umidade", f"{state.get('humidity', 0)}") # Umidade 
        d.metric("Lock", "SIM" if lock else "NÃO") # Se o bloqueio está ativo

    st.markdown('</div>', unsafe_allow_html=True) # Fecha o card

''' Controle '''

st.markdown("") # Espaço
st.markdown("## Controle Operacional") # Título para o controle 
st.caption("Ações críticas exigem confirmação para evitar cliques acidentais.") # Legenda que avisa que comandos críticos exigem comfirmação

op1, op2, op3 = st.columns(3, gap="large") # Cria 3 coluna de operação
with op1: # Comandos do domo 
    st.markdown('<div class="card">', unsafe_allow_html=True) # Abre um card 
    st.markdown('<div class="card-title">Dome</div>', unsafe_allow_html=True) # Título de Dome 
    if st.button(" FECHAR DOMO", use_container_width=True, disabled=not(confirm and state_ok)): # Botão apra fechar o domo, só fica ativo se o botão de confirmção de ações estiver ativo
        try:  # Tenta realizar a ação de fechar o domo
            r = sequencer_post("/dome/close") # Faz o POST para o sequenciador 
            st.success(" Comando enviado: FECHAR DOMO") # Mensagem de confirmação de envio 
            st.json(r.json()) # Mensagem de resposta do sequenciador
        except Exception as e: # Se der erro
            st.error(f" Erro ao fechar domo: {e}") # Registra o erro e mostra a mensagem 
    disabled_open = (not confirm) or (not state_ok) or bool(state.get("weather_lock")) # Verifica se o botão de abrir o domo deve ficar desabilitado. evita so domo ser aberto com clima inseguro
    if st.button("ABRIR DOMO", use_container_width=True, disabled=disabled_open): # Botão para abrir o domo
        try:
            r = sequencer_post("/dome/open") # Faz o POST para o sequenciador
            st.success(" Comando enviado: ABRIR DOMO") # Mensagem de confirmação de envio
            st.json(r.json()) # Mensagem do sequenciador 
        except Exception as e: # Se der erro
            st.error(f"Erro ao abrir domo: {e}") # Registra o erro e mostra a mensagem 
    st.markdown('</div>', unsafe_allow_html=True) # Fecha o card

with op2: # Comandos para a camera
    st.markdown('<div class="card">', unsafe_allow_html=True) # Abre o card
    st.markdown('<div class="card-title">Camera</div>', unsafe_allow_html=True) # Define o título como câmera
    seconds = st.number_input("⏱️ Exposição (s)", min_value=0.1, max_value=600.0, value=5.0, step=0.5) # Duração da exposição
    disabled_exp = (not confirm) or (not state_ok) or bool(state.get("weather_lock")) # Verifica se o botão se exposição deve estar desabilitado
    if st.button("INICIAR EXPOSIÇÃO", use_container_width=True, disabled=disabled_exp): # Botão para iniciar a exposição
        try: # Tenta executar a ação de exposição
            r = sequencer_post(f"/camera/expose/{seconds}") # Chama a função de exposição  
            st.success(f"Exposição iniciada ({seconds}s)") # Mostra que a exposição foi realizada e sua duração
            st.json(r.json()) # Mostra o JSON de resposta 
        except Exception as e: # Se der erro
            st.error(f"Erro ao iniciar exposição: {e}") # Mensagem de erro na exposição
    st.markdown('</div>', unsafe_allow_html=True) # Fecha o card

with op3: # Links rápidos 
    st.markdown('<div class="card">', unsafe_allow_html=True) # Abre o card
    st.markdown('<div class="card-title">Links úteis</div>', unsafe_allow_html=True) # Define o título
    st.link_button("Grafana", "/grafana/") # Link para o grafana
    st.link_button("Sequencer API", "/api/docs") # Link para o Sequenciador 
    st.markdown('</div>', unsafe_allow_html=True) # Fecha o card

''' Alertas e Agentes '''
st.markdown("") # Espaço
left, right = st.columns([2.3, 1.2], gap="large") # Duas colunas, uma na esquerda e outra na direita

with left: # Coluna da esquerda
    st.markdown('<div class="card">', unsafe_allow_html=True) # Abre o card
    st.markdown('<div class="card-title">Agentes</div>', unsafe_allow_html=True) # Define o título 

    rows = [] # Lista de linhas
    if docker_ok: # Se o docker estiver saudável de conectado
        for c in sorted([x for x in containers if x.name in ALLOWED], key=lambda x: x.name): # Percorre os containers permitidos 
            current = "UP" if c.status == "running" else "DOWN" # Estado atual como up ou down 
            target = "UP"  # Define o alvo como up, a internção é que todos estejam rodando
            rows.append({ # Adiciona dicionário
                "instance-id": c.name, # Nome do container
                "agent-class": "DockerService", # Classe do agente 
                "current": current, # Estado atual
                "target": target, # Estado desejado
            }) 
    if rows: # Se tiverem linhas 
        st.dataframe(rows, use_container_width=True, hide_index=True) # Mostra a tabela
    else: # Se não tiverem linhas
        st.markdown('<div class="small">Nenhum agente detectado.</div>', unsafe_allow_html=True) # Mensagem de vazio

    st.markdown('</div>', unsafe_allow_html=True) # Fecha o card

with right: # Coluna da direita
    st.markdown('<div class="card">', unsafe_allow_html=True) # Abre o card
    st.markdown('<div class="card-title">Alertas ativos</div>', unsafe_allow_html=True) # Título 

    alerts = None # Inicializa variáveis
    err = None
    try: # Tenta consultar alertas 
        alerts, err = grafana_alerts() # Chama a função que consulta os alertas no grafana
    except Exception as e: # Se tiver erro
        err = str(e) # Guarda a mensagem de erro

    if err: # Se tiver erro
        st.markdown(chip("Grafana alerts unavailable", "warn"), unsafe_allow_html=True) # Chip de alerta indisponível
        st.markdown(f'<div class="small">{err}</div>', unsafe_allow_html=True) # Mostra detalhes do erro
    else: # Se não tem erros 
        if not alerts: # Se a lista de alertas está vazia
            st.markdown(chip("No active alerts", "ok"), unsafe_allow_html=True) # Mostra que não há alertas ativos
        else: # Se tiverem alertas 
            st.markdown(f'<div class="small">Ativos: <b>{len(alerts)}</b></div>', unsafe_allow_html=True) # Mostra quantos alertas 
            st.markdown('<div class="hr"></div>', unsafe_allow_html=True) # Divisória

            def sev_rank(a): # Função que ordena os alertas
                sev = (a.get("labels", {}) or {}).get("severity", "warning").lower() # Severidade do alerta
                return 0 if sev in ("critical", "high", "p1") else 1 # Define que os alertas críticoa vem primeiro

            for a in sorted(alerts, key=sev_rank)[:12]: # Ordena os alertas por severidade
                labels = a.get("labels", {}) or {} # Label
                annotations = a.get("annotations", {}) or {} # Anotações
                status = a.get("status", {}) or {} # Status
                name = labels.get("alertname", "Sem nome") # Nome do alerta
                severity = (labels.get("severity", "warning") or "warning").lower() # Severidade
                lvl = "crit" if severity in ("critical", "high", "p1") else "warn" # Nível visual
                state = status.get("state", "unknown") # Estado
                starts_at = fmt_ts(a.get("startsAt", "")) # Data
                summary = annotations.get("summary") or annotations.get("description") or "" # Resumo do alerta

                st.markdown(f"**{name}**  {chip(severity.upper(), lvl)}", unsafe_allow_html=True) # Mostra o nome e o chip
                st.markdown(f'<div class="small">state: <b>{state}</b> • since: {starts_at}</div>', unsafe_allow_html=True) # Estado e início
                if summary:
                    st.markdown(f'<div class="small">{summary}</div>', unsafe_allow_html=True) # Mostra o resumo se ele existir 
                st.markdown('<div class="hr"></div>', unsafe_allow_html=True) # Separação entre os alertas 

            st.link_button("Abrir Alertas no Grafana", "/grafana/alerting/list") # Botão para abir a lista de alertas no grafana 

    st.markdown('</div>', unsafe_allow_html=True) # Fecha o card


''' Serviços do observatório '''
st.markdown("") # Espaço
st.markdown("## Serviços do Observatório") # Título

if not docker_ok: # Se o docker não estiver ativo
    st.error(f"Erro ao conectar ao Docker: {docker_err}") # Mensagem de que o docker está com erro
else: # Se o dockee estiver ok
    for c in [x for x in containers if x.name in ALLOWED]: # Percorrer os conatiners permitidos 
        status_icon = "🟢" if c.status == "running" else "🔴" # Ícone para o status 
        status_level = "ok" if c.status == "running" else "crit" # Nível 

        st.markdown('<div class="card">', unsafe_allow_html=True) # Abre o card
        st.markdown(
            f'<div class="card-title">{status_icon} {c.name}<span>{chip(c.status.upper(), status_level)}</span></div>', # Mostra o nome, ícone e chip do container 
            unsafe_allow_html=True
        )
        st.markdown(f'<div class="small">Imagem: {c.image.tags[0] if c.image.tags else "N/A"}</div>', unsafe_allow_html=True) # Imagem do docker

        b1, b2, b3 = st.columns(3) # Cria 3 colunas de botões
        with b1:
            if st.button("Restart", key=f"restart_{c.name}", use_container_width=True): # Reiniciar 
                c.restart() # Se clicado reinicia o container
                time.sleep(1) # Espera 1 segundo
                st.rerun() # Recarrega a página
        with b2:
            if st.button("⏹ Stop", key=f"stop_{c.name}", use_container_width=True, disabled=(c.status != "running")): # Botão de stop, fica desabilitaddo caso o container não esteja rodando 
                c.stop() # Se clicado para o container
                time.sleep(1) # Espera 1 segundo
                st.rerun() # Recarrega a página
        with b3:
            if st.button("▶ Start", key=f"start_{c.name}", use_container_width=True, disabled=(c.status == "running")) :# Botão de start, fica desabilitaddo caso o container esteja rodando 
                c.start() # Se clicado inicia o container
                time.sleep(1) # Espera 1 segundo
                st.rerun() # Recarrega a página 

        st.markdown('</div>', unsafe_allow_html=True) # Fecha o card
